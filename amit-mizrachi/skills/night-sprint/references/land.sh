#!/usr/bin/env bash
# night-sprint land - a blitz ticket puts its finished branch onto the sprint branch.
#
#   land.sh <WORKSPACE> <TAG> merge     take the landing lock, merge the sprint branch INTO the
#                                       ticket's branch, in the ticket's own worktree
#   land.sh <WORKSPACE> <TAG> publish   fast-forward the sprint branch to the ticket's tip, push,
#                                       release the lock
#   land.sh <WORKSPACE> <TAG> abort     abandon a merge in progress and release the lock
#
# In blitz mode tickets build side by side, each in its own worktree on its own branch
# (<BRANCH>--<TAG>, see launch.sh). Two tickets can each be green alone and still break the
# build together, so a ticket is not landed when its own checks pass. It is landed when the
# COMBINED tree passes, and the sprint branch only ever moves by a fast-forward to a tree that
# did. The ticket's session resolves its own conflicts: it wrote its side and still has it in
# its window, which no separate merge session would.
#
# Between `merge` and `publish` the session runs the static checks on the merged tree and
# commits what they need. The lock is held all that time, so the sprint branch cannot move
# under it and `publish` is always a fast-forward.
#
# The lock is state/land.lock/, owned by the ticket (T03c2 holds it as T03, so a relay
# mid-merge keeps it). A lock whose owner has ended without releasing it, or that is older than
# LAND_STALE_MIN (90), is taken over and logged. `merge` waits up to LAND_WAIT seconds (240,
# under a session's shell timeout) and then exits 75: run it again.
#
# In a multi-repo sprint a ticket lands on ITS repo's sprint branch (state/<TAG>.repo, see
# repos.sh), under that repo's own lock, state/land-<key>.lock: two repos share no branch, so a
# landing in one never waits on a landing in another.
#
# Exit codes: 0 ok; 2 the ticket tree is not clean - commit first; 3 CONFLICT, resolve and
# commit, then check and publish; 4 you do not hold the lock - run merge; 5 publish found the
# sprint branch not inside the ticket branch - run merge again; 6 landed locally but the push
# failed twice, after taking in what the remote gained; 8 origin's sprint branch has commits that
# do not merge cleanly into the local one; 75 busy - another ticket is landing, run merge again.

set -uo pipefail

WS="${1:?usage: land.sh <WORKSPACE> <TAG> merge|publish|abort}"
TAG="${2:?usage: land.sh <WORKSPACE> <TAG> merge|publish|abort}"
VERB="${3:?usage: land.sh <WORKSPACE> <TAG> merge|publish|abort}"

STATE="$WS/state"
# shellcheck source=repos.sh
. "$WS/repos.sh"
REPO_KEY="$(repo_of "$WS" "$TAG")"
LOCK="$STATE/land.lock"
[ -n "$REPO_KEY" ] && LOCK="$STATE/land-$REPO_KEY.lock"
LAND_WAIT="${LAND_WAIT:-240}"
LAND_STALE_MIN="${LAND_STALE_MIN:-90}"
WAIT="$LAND_WAIT"
STALE_MIN="$LAND_STALE_MIN"

note() { printf '%s land %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TAG" "$*" >> "$STATE/EVENTS.log"; }
die()  { echo "land: $2" >&2; note "$VERB rc=$1 $2"; exit "$1"; }

OWNER="$(printf '%s' "$TAG" | sed -E 's/c[0-9]+$//')"
WT="$(repo_fact "$WS" "$REPO_KEY" WORKTREE)"
BRANCH="$(repo_fact "$WS" "$REPO_KEY" BRANCH)"
TW="$(tr -d '[:space:]' < "$STATE/$TAG.cwd" 2>/dev/null || true)"
[ -n "$TW" ] && [ "$TW" != "$WT" ] || die 1 "$TAG has no worktree of its own (state/$TAG.cwd) - only a blitz ticket lands"

holder() { cat "$LOCK/owner" 2>/dev/null || echo; }

ended() {   # has this tag, or the session it relayed to, ended? (the lock holder may be gone)
  local t="$1" s n=0
  while [ "$n" -lt 20 ]; do
    s="$(head -1 "$STATE/$t.status" 2>/dev/null || true)"
    case "$s" in
      "") return 1 ;;
      RELAYED*) t="$(printf '%s' "${s#RELAYED}" | tr -d ':[:space:]')"; [ -n "$t" ] || return 1 ;;
      *) return 0 ;;
    esac
    n=$((n + 1))
  done
  return 1
}

take_lock() {
  local start h t
  start="$(date +%s)"
  while true; do
    if mkdir "$LOCK" 2>/dev/null; then
      printf '%s\n' "$OWNER" > "$LOCK/owner"
      note "lock taken"
      return 0
    fi
    h="$(holder)"
    [ "$h" = "$OWNER" ] && return 0
    t="$(stat -f %m "$LOCK" 2>/dev/null || stat -c %Y "$LOCK" 2>/dev/null || echo 0)"
    if { [ -n "$h" ] && ended "$h"; } || [ $(( $(date +%s) - t )) -ge $(( STALE_MIN * 60 )) ]; then
      rm -rf "$LOCK"
      note "took over a stale landing lock from '${h:-unknown}'"
      continue
    fi
    [ $(( $(date +%s) - start )) -ge "$WAIT" ] && \
      die 75 "BUSY - $h is landing. Run 'land.sh $WS $TAG merge' again."
    sleep 5
  done
}

release() { [ "$(holder)" = "$OWNER" ] && rm -rf "$LOCK"; return 0; }

# Commits someone else pushed to the sprint branch (the i18n bot, the user, a CI fix) come into
# the shared tree BEFORE a ticket merges it. Without this the next push is rejected as
# non-fast-forward, the landing exits 6 "the next landing pushes it", and every later landing
# fails the same way: on 2026-11-19 four tickets ended DONE with their work on the laptop only,
# behind one bot commit, until the conductor merged it by hand.
sync_remote() {
  git -C "$WT" remote get-url origin >/dev/null 2>&1 || return 0
  git -C "$WT" fetch -q origin "$BRANCH" 2>/dev/null || return 0
  local remote out
  remote="$(git -C "$WT" rev-parse -q --verify FETCH_HEAD 2>/dev/null)" || return 0
  git -C "$WT" merge-base --is-ancestor "$remote" "$BRANCH" 2>/dev/null && return 0
  heal_shared_tree "$remote"
  if out="$(git -C "$WT" merge -q --no-edit "$remote" 2>&1)"; then
    note "took in $(git -C "$WT" rev-parse --short "$remote") from origin/$BRANCH (pushed by someone else)"
    return 0
  fi
  git -C "$WT" merge --abort >/dev/null 2>&1
  release
  die 8 "origin/$BRANCH has commits that do not merge cleanly into the local sprint branch in $WT: $out - merge them there by hand, then run merge again"
}

# The shared tree must hold no uncommitted edit when the sprint branch moves. A session that works
# there (FIX-FINAL, TEST) and leaves an edit uncommitted blocks every later landing. An edit whose
# content is EXACTLY what the incoming commit holds for that file is a stale copy of work that is
# already committed, so it is safe to drop (2026-11-19: a doc line FIX-FINAL left uncommitted, and
# T08 carried the same line). Anything else is someone's unsaved work: it is left alone, and the
# fast-forward below names it.
heal_shared_tree() {
  local target="$1" f want have healed=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    want="$(git -C "$WT" rev-parse -q --verify "$target:$f" 2>/dev/null)" || continue
    have="$(git -C "$WT" hash-object -- "$f" 2>/dev/null)" || continue
    [ "$want" = "$have" ] || continue
    if git -C "$WT" cat-file -e "HEAD:$f" 2>/dev/null; then
      git -C "$WT" checkout -q HEAD -- "$f" 2>/dev/null && healed="$healed $f"
    else   # new in the incoming commit: the copy here only stands in the way of the fast-forward
      git -C "$WT" rm -q --cached -- "$f" >/dev/null 2>&1
      rm -f "$WT/$f" && healed="$healed $f"
    fi
  done <<EOF
$(git -C "$WT" diff --name-only HEAD 2>/dev/null; git -C "$WT" ls-files --others --exclude-standard 2>/dev/null)
EOF
  [ -n "$healed" ] && note "dropped stale uncommitted copies in the shared tree, identical to $target:$healed"
  return 0
}

push_sprint_branch() {   # push; on a rejection, take in what the remote gained and try once more
  local out
  out="$(git -C "$WT" push -q -u origin "$BRANCH" 2>&1)" && return 0
  git -C "$WT" fetch -q origin "$BRANCH" 2>/dev/null
  local remote; remote="$(git -C "$WT" rev-parse -q --verify FETCH_HEAD 2>/dev/null)"
  if [ -n "$remote" ] && ! git -C "$WT" merge-base --is-ancestor "$remote" "$BRANCH" 2>/dev/null \
     && git -C "$WT" merge -q --no-edit "$remote" >/dev/null 2>&1; then
    note "push rejected; took in $(git -C "$WT" rev-parse --short "$remote") from origin/$BRANCH and pushed again"
    out="$(git -C "$WT" push -q -u origin "$BRANCH" 2>&1)" && return 0
  else
    git -C "$WT" merge --abort >/dev/null 2>&1
  fi
  printf '%s' "$out"
  return 1
}

case "$VERB" in
  merge)
    [ -z "$(git -C "$TW" status --porcelain --untracked-files=no)" ] || \
      die 2 "the ticket tree has uncommitted changes - commit them first"
    take_lock
    if git -C "$TW" rev-parse -q --verify MERGE_HEAD >/dev/null; then
      die 3 "CONFLICT - a merge is already in progress in $TW. Resolve, 'git add', 'git commit --no-edit', run the static checks, then 'land.sh $WS $TAG publish'."
    fi
    sync_remote
    if out="$(git -C "$TW" merge --no-edit "$BRANCH" 2>&1)"; then
      note "merged $BRANCH into $TAG: $(printf '%s' "$out" | tail -1)"
      echo "MERGED - the sprint branch is merged into your branch. Run the static checks on the combined tree, commit any fix, then: land.sh $WS $TAG publish"
      exit 0
    fi
    files="$(git -C "$TW" diff --name-only --diff-filter=U | tr '\n' ' ')"
    [ -n "$files" ] || { git -C "$TW" merge --abort >/dev/null 2>&1; release; die 1 "merge failed without conflicts: $out"; }
    die 3 "CONFLICT in: $files- keep BOTH intents (the other side is a ticket that already landed). Resolve, 'git add', 'git commit --no-edit', run the static checks, then 'land.sh $WS $TAG publish'."
    ;;
  publish)
    [ "$(holder)" = "$OWNER" ] || die 4 "you do not hold the landing lock - run 'land.sh $WS $TAG merge' first"
    git -C "$TW" rev-parse -q --verify MERGE_HEAD >/dev/null && \
      die 3 "the merge is not committed yet - 'git commit --no-edit' first"
    [ -z "$(git -C "$TW" status --porcelain --untracked-files=no)" ] || \
      die 2 "the ticket tree has uncommitted changes - commit them first"
    git -C "$TW" merge-base --is-ancestor "$BRANCH" HEAD || \
      die 5 "the sprint branch is not inside your branch - run 'land.sh $WS $TAG merge' again"
    sha="$(git -C "$TW" rev-parse HEAD)"
    heal_shared_tree "$sha"
    out="$(git -C "$WT" merge -q --ff-only "$sha" 2>&1)" || \
      die 1 "could not fast-forward $BRANCH in $WT to $sha: $out - an uncommitted edit in the shared tree ($(git -C "$WT" diff --name-only HEAD | tr '\n' ' ')) is in the way; the session that worked there left it"
    note "landed $sha on $BRANCH"
    if git -C "$WT" remote get-url origin >/dev/null 2>&1; then
      out="$(push_sprint_branch)" || { release; die 6 "LANDED $sha locally, but the push failed twice: $out"; }
    fi
    release
    echo "LANDED $sha on $BRANCH"
    ;;
  abort)
    git -C "$TW" rev-parse -q --verify MERGE_HEAD >/dev/null && git -C "$TW" merge --abort
    release
    note "aborted, lock released"
    echo "ABORTED - lock released"
    ;;
  *) die 1 "unknown verb '$VERB' - merge, publish or abort" ;;
esac
