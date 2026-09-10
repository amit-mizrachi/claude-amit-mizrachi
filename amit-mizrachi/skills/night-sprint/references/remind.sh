#!/usr/bin/env bash
# night-sprint context nudge - tell a session that is filling up to stop opening new fronts.
#
#   remind.sh <WORKSPACE> <TAG> [USED_PCT]
#
# USED_PCT is the watcher's reading (the N in `WARN <tag> used-Npct <id>`).
#
# WHY THIS IS SEPARATE FROM relay.sh. The two rungs do different jobs. The relay ENDS a session:
# it consolidates, writes a handoff, and a fresh session takes the ticket over. The nudge does
# not end anything - the session keeps its ticket and keeps working. It only changes what the
# session is allowed to START.
#
# The reason the nudge exists at all is that the expensive mistake is not running out of window,
# it is running out of window HALFWAY THROUGH SOMETHING. A session that begins a new subsystem,
# a wide refactor, or a fresh review fan-out at 22% used will be at the handoff line before that
# work reaches a state anybody can hand over, and its successor inherits a half-finished thing
# plus a description of it. Told at 20% to open no new fronts, the same session arrives at 30%
# holding a clean, completed unit of work, and the handoff is a paragraph instead of an
# archaeology report.
#
# HOW A SESSION IS TOLD. There is no way to push a message into a running background session, so
# this does what relay.sh and revive.sh do: `claude stop` (the conversation survives on disk in
# full), then `claude --bg --resume` with the nudge as the next turn. The session keeps
# everything it knows.
#
# ONE NUDGE PER TAG, EVER. The `.warned` marker below is what enforces it. A session nagged
# twice about its context spends more window reading nudges than it saves.

set -uo pipefail

WS="${1:?usage: remind.sh <WORKSPACE> <TAG> [USED_PCT]}"
TAG="${2:?usage: remind.sh <WORKSPACE> <TAG> [USED_PCT]}"
USED="${3:-unknown}"

STATE="$WS/state"
SEEN="$STATE/.watch-seen"
SESSION_FILE="$STATE/$TAG.session"

# A session that already reported a terminal status has nothing to be reminded about.
if [ -f "$STATE/$TAG.status" ]; then
  echo "remind: $TAG already reported '$(head -1 "$STATE/$TAG.status")' - nothing to remind"
  exit 0
fi

# Already relaying? The relay instruction supersedes the nudge in every respect.
if [ -f "$STATE/$TAG.relayed" ]; then
  echo "remind: $TAG is already relaying to $(head -1 "$STATE/$TAG.relayed") - nudge would be noise"
  exit 0
fi

if [ -f "$STATE/$TAG.warned" ]; then
  echo "remind: $TAG was already nudged at $(head -1 "$STATE/$TAG.warned")% used - one per tag"
  exit 0
fi

WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"
MODE="$(tr -d '[:space:]' < "$WS/PERMISSION_MODE" 2>/dev/null || echo auto)"
SLUG="$(tr -d '[:space:]' < "$WS/SLUG" 2>/dev/null || echo sprint)"
RELAY_AT_USED=30
[ -f "$WS/RELAY_AT_USED" ] && RELAY_AT_USED="$(tr -d '[:space:]' < "$WS/RELAY_AT_USED")"

OLD_SID=""
[ -f "$SESSION_FILE" ] && OLD_SID="$(tr -d '[:space:]' < "$SESSION_FILE")"

if [ -z "$OLD_SID" ] || [ "$OLD_SID" = "unresolved" ]; then
  echo "remind: $TAG has no resolvable session id - cannot nudge it" >&2
  exit 1
fi

NUDGE_PROMPT="CONTEXT CHECK - you have used about ${USED}% of your context window.

Nothing is wrong and you are not being relayed. Keep your ticket, keep working, and finish what
you are in the middle of. This is a heads-up about what you START from here.

You hand off at ${RELAY_AT_USED}% used. That is close enough that anything you begin now is
unlikely to reach a state somebody else could pick up. So, from this point:

- Do NOT open a new front. No new subsystem, no refactor beyond what your ticket needs, no fresh
  review fan-out, no broad exploratory reading of files you have not already opened.
- DO drive the thing you are on right now to a finished, committed state. A completed unit of
  work is what makes a handoff cheap; a half-finished one is what makes it expensive.
- Prefer targeted reads over wide ones. You already have the context you built up; spending the
  rest of the window rediscovering the codebase is the specific waste this warning exists to stop.
- If your ticket is nearly done, just finish it. Finishing beats handing off, always.

When you do reach ${RELAY_AT_USED}% used, follow the CONTEXT RELAY steps in your original prompt.
Measure, do not estimate:
  bash $WS/context-used.sh --self \$(cat $WS/CONTEXT_WINDOW 2>/dev/null || echo 200000)

Carry on. Still an autonomous night run - nobody is awake to answer a question."

echo "remind: $TAG used=${USED}pct -> nudging $OLD_SID (start nothing new)"

# Stop the running session first. The conversation stays resumable; this is the only way to get
# a new instruction in front of a background session.
claude stop "$OLD_SID" >/dev/null 2>&1

NAME="ns-$SLUG-$TAG-nudge"
( cd "$WT" && claude --bg --resume "$OLD_SID" -n "$NAME" --permission-mode "$MODE" "$NUDGE_PROMPT" ) \
  > "$STATE/$TAG.remind.log" 2>&1
rc=$?

# A resumed session gets a NEW session id and does not inherit its display name. Repoint the
# watcher at it, or the sprint spends the rest of the night watching a corpse.
new_sid=""
if [ $rc -eq 0 ]; then
  for _ in $(seq 1 15); do
    new_sid="$(claude agents --json --all --cwd "$WT" 2>/dev/null \
      | python3 -c 'import json,sys
want=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
best=None
for r in rows:
    if r.get("name")==want and (best is None or r.get("startedAt",0)>best.get("startedAt",0)):
        best=r
if best: print(best.get("sessionId",""))' "$NAME")"
    [ -n "$new_sid" ] && break
    sleep 2
  done
fi

if [ $rc -ne 0 ] || [ -z "$new_sid" ]; then
  # Not fatal, and not even close to it. The session is doing fine - it just did not get a
  # piece of advice. Mark it warned anyway so the watcher does not retry the stop/resume every
  # poll, which WOULD hurt: each failed attempt still stops a working session.
  echo "remind: $TAG nudge FAILED (rc=$rc, see $STATE/$TAG.remind.log) - session carries on unnudged" >&2
  printf '%s\n' "$USED" > "$STATE/$TAG.warned"
  echo "nudge-failed $USED $OLD_SID -" >> "$STATE/$TAG.reminds"
  exit 1
fi

printf '%s\n' "$new_sid" > "$SESSION_FILE"
printf '%s\n' "$USED" > "$STATE/$TAG.warned"
echo "nudge $USED $OLD_SID $new_sid" >> "$STATE/$TAG.reminds"

# The watcher emits each (tag, verdict) once. Clear this tag's rows so the LATER rungs - the
# relay, and any death - are still reported for the new session id. The `.warned` marker above
# is what stops the nudge itself from refiring.
if [ -f "$SEEN" ]; then
  grep -v "^$TAG:" "$SEEN" > "$SEEN.tmp" 2>/dev/null || true
  [ -f "$SEEN.tmp" ] && mv "$SEEN.tmp" "$SEEN"
fi

echo "remind: $TAG nudged, now running as $new_sid ($NAME)"
