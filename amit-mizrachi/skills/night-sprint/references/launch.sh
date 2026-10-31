#!/usr/bin/env bash
# night-sprint launcher - atomically claims a tag, starts its session, records the id.
#
#   launch.sh <WORKSPACE> <TAG> [--reclaim]
#
# Both the conductor and the previous ticket's session may try to start the next
# ticket at the same moment. `mkdir` is atomic on POSIX, so exactly one of them
# wins the claim and the loser exits 0 without launching. Never launch a session
# any other way during a sprint - the claim is what keeps two agents out of the
# same worktree.
#
# Expects in <WORKSPACE>:
#   WORKTREE          - absolute path to the single shared worktree
#   PERMISSION_MODE   - `auto` unless the user chose otherwise at kickoff. Not `acceptEdits`:
#                       that still prompts on shell commands and a background session cannot
#                       answer a prompt, so it sits in `blocked` until the conductor revives it.
#                       Not `bypassPermissions` either, unless the user has already accepted its
#                       one-time interactive disclaimer - `claude --bg` refuses without it.
#   SLUG              - sprint slug, used for the session display name
#   prompt-<TAG>.txt  - the prompt to run
#   state/<TAG>.cwd   - optional: where THIS tag runs, instead of WORKTREE. A phase chain (see
#                       phase-chain.sh) runs each phase conductor in its own repo or workspace.
#   state/<TAG>.isolate  - optional, blitz tickets: give the tag its OWN worktree at
#                       <WORKTREE>-<TAG> on a new branch <BRANCH>--<TAG>, cut from the sprint
#                       branch as it stands now (so it holds every blocker that already landed).
#                       Two agents in one worktree is the DUP incident; concurrency needs trees.
#   state/<TAG>.snapshot - optional, async review finders: a DETACHED worktree at
#                       <WORKTREE>-<TAG>, frozen at the sprint branch's tip, so the finder reads
#                       one fixed commit while the next ticket keeps changing the shared tree.
#                     Either one is created once, by the claimer, and recorded as state/<TAG>.cwd,
#                     which a relay copies on (advance.sh) and a revive resumes in (revive.sh).
#   state/<TAG>.repo  - optional, multi-repo sprints: the repo key the tag works in. Its worktree
#                       and branch then come from repos/<key>/ instead of WORKTREE and BRANCH,
#                       for the tag itself and for any tree of its own. See repos.sh.
# Writes:
#   state/claim-<TAG>/ - the claim
#   state/<TAG>.session - the resolved background session id
#   state/EVENTS.log    - one durable line per launch, for the morning ledger
#
# Refuses (exit 4) while state/PAUSED exists - see the check below.
#
# A launch that fails writes `BLOCKED: could not ...` and RELEASES the claim, so retrying is just
# running launch.sh again: the retry wins the claim and clears that status itself. Nothing else is
# needed, and nobody types `rm` - an org policy can make `rm` ask for confirmation even in auto
# mode, and at 3am nobody answers it.

set -uo pipefail

WS="${1:?usage: launch.sh <WORKSPACE> <TAG>}"
TAG="${2:?usage: launch.sh <WORKSPACE> <TAG>}"

# shellcheck source=agents.sh
. "$WS/agents.sh"
# shellcheck source=repos.sh
. "$WS/repos.sh"

STATE="$WS/state"
mkdir -p "$STATE"

note() {
  printf '%s launch %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TAG" "$*" >> "$STATE/EVENTS.log"
}

# NOTHING LAUNCHES WHILE THE SPRINT IS OUT OF CAPACITY. A spend or session limit refuses every
# request equally, so starting a fresh session against one does not get the work done - it
# just spends another refused request and leaves a dead tag for the reviver to clean up. The
# reviver writes this file when it classifies a quota failure; the watcher clears it once the
# capacity is back. Refuse and leave the claim alone so the tag can still be started later.
if [ -f "$STATE/PAUSED" ]; then
  echo "launch: refusing to start $TAG - sprint paused ($(head -1 "$STATE/PAUSED"))" >&2
  note "refused: paused"
  exit 4
fi

PROMPT="$WS/prompt-$TAG.txt"
[ -f "$PROMPT" ] || { echo "launch: no prompt file at $PROMPT" >&2; exit 1; }

REPO_KEY="$(repo_of "$WS" "$TAG")"
WT="$( { tr -d '[:space:]' < "$STATE/$TAG.cwd"; } 2>/dev/null || true)"
[ -n "$WT" ] || WT="$(repo_fact "$WS" "$REPO_KEY" WORKTREE)"
MODE="$(tr -d '[:space:]' < "$WS/PERMISSION_MODE" 2>/dev/null || echo auto)"
SLUG="$(tr -d '[:space:]' < "$WS/SLUG" 2>/dev/null || echo sprint)"
NAME="ns-$SLUG-$TAG"

# --- STRANDED: a claim with no session and no status (the launch died between the two). Only the
#     conductor passes --reclaim, and never for a tag with a session - that one is revive.sh's.
if [ "${3:-}" = "--reclaim" ]; then
  if [ -s "$STATE/$TAG.session" ]; then
    echo "launch: refusing --reclaim - $TAG has a session ($(head -1 "$STATE/$TAG.session")); revive it instead" >&2
    exit 1
  fi
  rmdir "$STATE/claim-$TAG" 2>/dev/null && note "reclaim: released a stale claim"
fi

# --- the claim. Exactly one caller gets past this line. ---
if ! mkdir "$STATE/claim-$TAG" 2>/dev/null; then
  echo "launch: $TAG already claimed by another session - nothing to do"
  note "no-op: already claimed"
  exit 0
fi

# A retry after a failed launch: the status that failure wrote is launch.sh's own, not a session's
# result, so clear it - left in place, the runner would read the tag as finished while it runs.
case "$(head -1 "$STATE/$TAG.status" 2>/dev/null)" in
  "BLOCKED: could not start session"*|"BLOCKED: could not create its worktree"*)
    rm -f "$STATE/$TAG.status"
    note "retry: cleared the earlier launch failure" ;;
esac

# --- a tree of its own, for a blitz ticket or a review snapshot. Only the claimer gets here. ---
if [ ! -f "$STATE/$TAG.cwd" ] && { [ -f "$STATE/$TAG.isolate" ] || [ -f "$STATE/$TAG.snapshot" ]; }; then
  BR="$(repo_fact "$WS" "$REPO_KEY" BRANCH)"
  OWN="$WT-$TAG"
  if git -C "$OWN" rev-parse --git-dir >/dev/null 2>&1; then
    out="reused"
  elif [ -f "$STATE/$TAG.isolate" ]; then
    if git -C "$WT" rev-parse -q --verify "refs/heads/$BR--$TAG" >/dev/null; then
      out="$(git -C "$WT" worktree add -q "$OWN" "$BR--$TAG" 2>&1)"
    else
      out="$(git -C "$WT" worktree add -q -b "$BR--$TAG" "$OWN" "$BR" 2>&1)"
    fi
  else
    out="$(git -C "$WT" worktree add -q --detach "$OWN" "$BR" 2>&1)"
  fi
  if ! git -C "$OWN" rev-parse --git-dir >/dev/null 2>&1; then
    echo "launch: could not create $TAG's own worktree at $OWN: $out" >&2
    echo "BLOCKED: could not create its worktree at $OWN" > "$STATE/$TAG.status"
    rmdir "$STATE/claim-$TAG" 2>/dev/null
    note "FAILED worktree $OWN: $out - claim released"
    exit 1
  fi
  printf '%s\n' "$OWN" > "$STATE/$TAG.cwd"
  note "worktree $OWN ($out)"
  WT="$OWN"
fi

# Record the branch tip as this tag starts. The watcher diffs against it to tell whether the
# session has produced any work yet, and holds the context relay until it has - a session
# relayed before it changed anything hands its successor nothing but a list of files to re-read.
git -C "$WT" rev-parse HEAD > "$STATE/$TAG.headsha" 2>/dev/null || true

# A folder the run created must be trusted, or `claude --bg` refuses it ("Workspace not trusted")
# and the tag never starts - every product-research run stalled on T01 this way. That is the
# workspace itself, anything under it (a research sprint's <WS>/work and its own trees), and its
# direct parent (a night-marathon conductor runs in <WS>, its phase chain lives in <WS>/phases).
# The user's repo is never one of these: they opened it in Claude Code themselves.
# A folder already trusted costs one read. If marking fails, say so and launch anyway: the CLI
# then decides exactly as it did before this step existed, and a refusal takes the failure path.
ws_real="$(cd "$WS" && pwd -P)"
wt_real="$(cd "$WT" 2>/dev/null && pwd -P)"
case "$wt_real" in
  "$ws_real"|"$ws_real"/*|"$(dirname "$ws_real")")
    if [ -f "$WS/trust.sh" ] && ! out="$(bash "$WS/trust.sh" "$WT" 2>&1)"; then
      echo "launch: warning - could not mark $WT trusted, launching anyway: $out" >&2
      note "warning: could not mark $WT trusted"
    fi ;;
esac

echo "launch: claimed $TAG, starting session '$NAME' in $WT"
( cd "$WT" && claude --bg -n "$NAME" --permission-mode "$MODE" "$(cat "$PROMPT")" ) \
  > "$STATE/$TAG.launch.log" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
  echo "launch: FAILED to start $TAG (rc=$rc). See $STATE/$TAG.launch.log" >&2
  echo "        Fix the cause, then retry with: bash $WS/launch.sh $WS $TAG" >&2
  echo "BLOCKED: could not start session (rc=$rc)" > "$STATE/$TAG.status"
  rmdir "$STATE/claim-$TAG" 2>/dev/null
  note "FAILED rc=$rc - claim released"
  exit $rc
fi

# Resolve the session id by its display name - the launch output format is not a
# stable contract, but `claude agents --json` reporting `name` is.
sid=""
for _ in $(seq 1 15); do
  rows="$(agents_json "$WT")" || break
  sid="$(printf '%s' "$rows" \
    | python3 -c 'import json,sys
want=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
best=None
for r in rows:
    if r.get("name")==want and (best is None or r.get("startedAt",0)>best.get("startedAt",0)):
        best=r
if best: print(best.get("sessionId",""))' "$NAME")"
  [ -n "$sid" ] && break
  sleep 2
done

# The banner names the short id whatever `claude agents` does. The watcher matches a row on
# `sessionId` OR its first 8 characters, so even the bare short id keeps the tag watched.
[ -n "$sid" ] || sid="$(sid_from_launch_log "$STATE/$TAG.launch.log")" || sid=""

if [ -z "$sid" ]; then
  # The session may still be up; we just cannot watch it by id. Say so loudly
  # rather than silently leaving an unwatched agent running all night.
  echo "launch: started $TAG but could not resolve its session id by name '$NAME'" >&2
  echo "unresolved" > "$STATE/$TAG.session"
  exit 0
fi

printf '%s\n' "$sid" > "$STATE/$TAG.session"
note "started $sid ($NAME)"
echo "launch: $TAG running as $sid ($NAME)"
