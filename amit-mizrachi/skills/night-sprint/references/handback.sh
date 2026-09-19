#!/usr/bin/env bash
# night-sprint handback - give a small fix set back to the session that wrote the code.
#
#   handback.sh <WORKSPACE> <FIX_TAG> <IMPL_TAG> <FINDINGS_FILE>
#
# Resumes <IMPL_TAG>'s conversation, under the new name <FIX_TAG>, with the findings file as
# its instruction. Exits non-zero, having done nothing, when a handback is the wrong move -
# and the caller then launches a fresh fixer instead.
#
# WHY THIS EXISTS. Every review used to end by starting a brand new session to do the fixing,
# whatever the fixing was. Across one night that was seven fresh windows for seven reviews:
# 103M tokens, a quarter of the whole sprint, much of it spent re-reading the code the
# previous session had just written. For a one-line fix in a file the implementer had open
# twenty minutes ago, a fresh window is the most expensive possible way to make the change.
#
# It refuses in three cases, each of which makes the fresh session the cheaper option:
#   - the implementer's window is already past the relay line, so it has no room to work in;
#   - its conversation is gone, or the session is somehow still running;
#   - the fix set is too big to be a patch-up, which the CALLER decides before calling.
#
# The findings never go through GitHub to get here. A finder posting its own notes to a PR so
# that a fixer can fetch them back is two network round trips and a general-purpose
# review-reading skill, in place of reading a local file.

set -uo pipefail

WS="${1:?usage: handback.sh <WORKSPACE> <FIX_TAG> <IMPL_TAG> <FINDINGS_FILE>}"
FIX_TAG="${2:?usage: handback.sh <WORKSPACE> <FIX_TAG> <IMPL_TAG> <FINDINGS_FILE>}"
IMPL_TAG="${3:?usage: handback.sh <WORKSPACE> <FIX_TAG> <IMPL_TAG> <FINDINGS_FILE>}"
FINDINGS="${4:?usage: handback.sh <WORKSPACE> <FIX_TAG> <IMPL_TAG> <FINDINGS_FILE>}"

# shellcheck source=agents.sh
. "$WS/agents.sh"

STATE="$WS/state"
mkdir -p "$STATE"

refuse() { echo "handback: $*" >&2; exit 1; }

[ -f "$STATE/PAUSED" ] && refuse "sprint is paused ($(head -1 "$STATE/PAUSED"))"
[ -f "$FINDINGS" ] || refuse "no findings file at $FINDINGS"
[ -f "$STATE/$FIX_TAG.status" ] && refuse "$FIX_TAG already reported $(head -1 "$STATE/$FIX_TAG.status")"

# NEVER HAND BACK A TAG WHOSE RENDERED PROMPT CARRIES OBLIGATIONS THIS ONE DOES NOT.
#
# The prompt below is a generic "fix these, verify, push, advance" contract. FIX-FINAL's rendered
# prompt is not: it also runs accept.sh, gets one bounded repair pass on a red result, writes
# state/ACCEPTANCE.verdict, and only takes the PR out of draft on PASS. Resuming an implementer
# with the generic prompt silently drops every one of those, so a one-line final fix could end
# the sprint - or launch TEST and WIZARD - with nothing having checked CI at all.
#
# The test is mechanical rather than a name match, so it keeps holding if the acceptance step
# moves to another tag: if the tag's own rendered prompt mentions accept.sh, that prompt is the
# contract and the caller must launch it.
if [ -f "$WS/prompt-$FIX_TAG.txt" ] && grep -q 'accept\.sh' "$WS/prompt-$FIX_TAG.txt"; then
  refuse "$FIX_TAG's rendered prompt has an acceptance gate this handback would drop - launch it instead"
fi

WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"
MODE="$(tr -d '[:space:]' < "$WS/PERMISSION_MODE" 2>/dev/null || echo auto)"
SLUG="$(tr -d '[:space:]' < "$WS/SLUG" 2>/dev/null || echo sprint)"
WINDOW="$(tr -d '[:space:]' < "$WS/CONTEXT_WINDOW" 2>/dev/null || echo 200000)"
RELAY_AT="$(tr -d '[:space:]' < "$WS/RELAY_AT_USED" 2>/dev/null || echo 30)"
VERIFY="$(cat "$WS/VERIFY" 2>/dev/null || echo)"
BRANCH="$(tr -d '[:space:]' < "$WS/BRANCH" 2>/dev/null || echo)"

SID="$(tr -d '[:space:]' < "$STATE/$IMPL_TAG.session" 2>/dev/null || echo)"
case "$SID" in ""|unresolved) refuse "$IMPL_TAG has no resolved session to resume" ;; esac

# A conversation with no room left in it cannot take on fixes. Resuming it would put the
# session straight over its own relay line, and it would hand the work on before touching it.
used="$(bash "$WS/context-used.sh" "$SID" "$WINDOW" 2>/dev/null || echo)"
case "$used" in
  ''|*[!0-9]*) refuse "cannot measure $IMPL_TAG's window - not resuming it blind" ;;
esac
[ "$used" -ge "$RELAY_AT" ] && \
  refuse "$IMPL_TAG is at ${used}% used, past the ${RELAY_AT}% relay line - launch a fresh fixer"

# It must be genuinely finished. A live session is never interrupted, for the same reason as
# everywhere else in this sprint: resuming one forks it, and two agents share one worktree.
live="$(agents_json "$WT" | python3 -c 'import json,sys
sid=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
for r in rows:
    if r.get("sessionId")==sid or r.get("id")==sid[:8]:
        if r.get("pid") and r.get("state")!="done": print("live")
        break' "$SID")"
[ "$live" = "live" ] && refuse "$IMPL_TAG ($SID) is still running - never resume a live session"

mkdir "$STATE/claim-$FIX_TAG" 2>/dev/null || { echo "handback: $FIX_TAG already claimed"; exit 0; }

NAME="ns-$SLUG-$FIX_TAG"
PROMPT="FIX YOUR OWN WORK - you are now tag $FIX_TAG.

An independent review read the diff you built and found the items below. You wrote this code,
it is still in your window, and that is exactly why the sprint brought you back rather than
starting a fresh session to re-read it all.

$(cat "$FINDINGS")

RULES:
- Work the list in severity order: BLOCKER, HIGH, MEDIUM, LOW.
- Fix, or reject in ONE line with the reason. A reasoned rejection is a legitimate outcome; a
  silent one is not. You do NOT get to reject a finding because you already thought about it.
- Do NOT run a review of any kind. You are not re-reviewing; the review already happened.
- Do NOT widen the change. Smallest edit that actually resolves each item.
- Nobody is awake. Never ask a question - decide, and say what you decided.

THEN, in this order:
1. $VERIFY
   Green before you commit. Never --no-verify. If one fix cannot go green, revert THAT fix,
   record it as rejected with the failure text, and keep the rest.
2. Re-check the specific lines you changed against the findings, and re-run the ticket's own
   acceptance criteria. \"I made an edit\" is not \"the finding is resolved\".
3. Commit to $BRANCH with 'SIGNAL: $FIX_TAG-DONE' in the body, and push.
4. Reply on any PR comment thread that an external reviewer or bot opened, saying what
   happened. The review items above are internal and need no thread.
5. echo '<n fixed, n rejected and why, in one line>' > $WS/state/$FIX_TAG.summary
6. echo 'DONE' > $WS/state/$FIX_TAG.status        (or 'BLOCKED: <reason>')
7. bash $WS/advance.sh $WS $FIX_TAG

Post a summary as your last message: what you fixed, what you rejected and why, anything left
for a human."

echo "handback: resuming $IMPL_TAG ($SID, ${used}% used) as $FIX_TAG"
( cd "$WT" && claude --bg --resume "$SID" -n "$NAME" --permission-mode "$MODE" "$PROMPT" ) \
  > "$STATE/$FIX_TAG.launch.log" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
  # Leave no claim behind: the caller's fallback is to launch a fresh fixer on this same tag.
  rm -rf "$STATE/claim-$FIX_TAG"
  echo "handback: resume FAILED (rc=$rc, see $STATE/$FIX_TAG.launch.log)" >&2
  exit 1
fi

# A resumed session gets a NEW id and does not inherit the name. Record the new one or the
# watcher spends the rest of the night reading a transcript that stopped growing.
for _ in $(seq 1 15); do
  sid="$(agents_json "$WT" | python3 -c 'import json,sys
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

if [ -z "${sid:-}" ]; then
  echo "handback: started $FIX_TAG but could not resolve its session id by name '$NAME'" >&2
  echo unresolved > "$STATE/$FIX_TAG.session"
  exit 0
fi

printf '%s\n' "$sid" > "$STATE/$FIX_TAG.session"
printf '%s handback %s resumed %s as %s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$FIX_TAG" "$IMPL_TAG" "$sid" >> "$STATE/EVENTS.log"
echo "handback: $FIX_TAG running as $sid ($NAME)"
