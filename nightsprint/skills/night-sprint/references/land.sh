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
# Exit codes: 0 ok; 2 the ticket tree is not clean - commit first; 3 CONFLICT, resolve and
# commit, then check and publish; 4 you do not hold the lock - run merge; 5 publish found the
# sprint branch not inside the ticket branch - run merge again; 6 landed locally but the push
# failed (the next landing pushes it); 75 busy - another ticket is landing, run merge again.

set -uo pipefail

WS="${1:?usage: land.sh <WORKSPACE> <TAG> merge|publish|abort}"
TAG="${2:?usage: land.sh <WORKSPACE> <TAG> merge|publish|abort}"
VERB="${3:?usage: land.sh <WORKSPACE> <TAG> merge|publish|abort}"

STATE="$WS/state"
LOCK="$STATE/land.lock"
LAND_WAIT="${LAND_WAIT:-240}"
LAND_STALE_MIN="${LAND_STALE_MIN:-90}"
WAIT="$LAND_WAIT"
STALE_MIN="$LAND_STALE_MIN"

note() { printf '%s land %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TAG" "$*" >> "$STATE/EVENTS.log"; }
die()  { echo "land: $2" >&2; note "$VERB rc=$1 $2"; exit "$1"; }

OWNER="$(printf '%s' "$TAG" | sed -E 's/c[0-9]+$//')"
WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"
BRANCH="$(tr -d '[:space:]' < "$WS/BRANCH")"
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

case "$VERB" in
  merge)
    [ -z "$(git -C "$TW" status --porcelain --untracked-files=no)" ] || \
      die 2 "the ticket tree has uncommitted changes - commit them first"
    take_lock
    if git -C "$TW" rev-parse -q --verify MERGE_HEAD >/dev/null; then
      die 3 "CONFLICT - a merge is already in progress in $TW. Resolve, 'git add', 'git commit --no-edit', run the static checks, then 'land.sh $WS $TAG publish'."
    fi
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
    out="$(git -C "$WT" merge -q --ff-only "$sha" 2>&1)" || \
      die 1 "could not fast-forward $BRANCH in $WT to $sha: $out"
    release
    note "landed $sha on $BRANCH"
    if git -C "$WT" remote get-url origin >/dev/null 2>&1; then
      out="$(git -C "$WT" push -q -u origin "$BRANCH" 2>&1)" || \
        die 6 "LANDED $sha locally, but the push failed: $out - the next landing pushes it"
    fi
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
