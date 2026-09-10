#!/usr/bin/env bash
# night-sprint launcher - atomically claims a tag, starts its session, records the id.
#
#   launch.sh <WORKSPACE> <TAG>
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
# Writes:
#   state/claim-<TAG>/ - the claim
#   state/<TAG>.session - the resolved background session id

set -uo pipefail

WS="${1:?usage: launch.sh <WORKSPACE> <TAG>}"
TAG="${2:?usage: launch.sh <WORKSPACE> <TAG>}"

STATE="$WS/state"
mkdir -p "$STATE"

PROMPT="$WS/prompt-$TAG.txt"
[ -f "$PROMPT" ] || { echo "launch: no prompt file at $PROMPT" >&2; exit 1; }

WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"
MODE="$(tr -d '[:space:]' < "$WS/PERMISSION_MODE" 2>/dev/null || echo auto)"
SLUG="$(tr -d '[:space:]' < "$WS/SLUG" 2>/dev/null || echo sprint)"
NAME="ns-$SLUG-$TAG"

# --- the claim. Exactly one caller gets past this line. ---
if ! mkdir "$STATE/claim-$TAG" 2>/dev/null; then
  echo "launch: $TAG already claimed by another session - nothing to do"
  exit 0
fi

# Record the branch tip as this tag starts. The watcher diffs against it to tell whether the
# session has produced any work yet, and holds the context relay until it has - a session
# relayed before it changed anything hands its successor nothing but a list of files to re-read.
git -C "$WT" rev-parse HEAD > "$STATE/$TAG.headsha" 2>/dev/null || true

echo "launch: claimed $TAG, starting session '$NAME' in $WT"
( cd "$WT" && claude --bg -n "$NAME" --permission-mode "$MODE" "$(cat "$PROMPT")" ) \
  > "$STATE/$TAG.launch.log" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
  echo "launch: FAILED to start $TAG (rc=$rc). See $STATE/$TAG.launch.log" >&2
  echo "BLOCKED: could not start session (rc=$rc)" > "$STATE/$TAG.status"
  exit $rc
fi

# Resolve the session id by its display name - the launch output format is not a
# stable contract, but `claude agents --json` reporting `name` is.
sid=""
for _ in $(seq 1 15); do
  sid="$(claude agents --json --all --cwd "$WT" 2>/dev/null \
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

if [ -z "$sid" ]; then
  # The session may still be up; we just cannot watch it by id. Say so loudly
  # rather than silently leaving an unwatched agent running all night.
  echo "launch: started $TAG but could not resolve its session id by name '$NAME'" >&2
  echo "unresolved" > "$STATE/$TAG.session"
  exit 0
fi

printf '%s\n' "$sid" > "$STATE/$TAG.session"
echo "launch: $TAG running as $sid ($NAME)"
