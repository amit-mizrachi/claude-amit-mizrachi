#!/usr/bin/env bash
# night-sprint transition owner - decide what runs next, and start it. Nothing else does.
#
#   advance.sh <WORKSPACE> <TAG>
#
# Exit codes, because callers act on them:
#   0  advanced, or the chain ended here, or the successor was already running
#   2  the tag is BLOCKED - a human or the conductor decides, this script will not guess
#   3  the tag has not reported a terminal status yet, so there is nothing to advance
#   4  the sprint is PAUSED (quota) - launching more work now only burns refused requests
#
# WHY ONE OWNER. Two things used to decide what ran next: the finishing session, out of its
# own prompt, and the conductor, off a watcher event. They read different files at different
# moments, and one of those races cost a night - a review finder wrote `DONE` and only THEN
# worked out whether its fixer had anything to do, while the conductor, seeing `DONE
# REVIEW-01`, had already launched the fixer. Now every terminal decision a session makes
# lands in `state/<TAG>.next` BEFORE its status file exists, and this script is the only
# thing that reads the pair. Both the session and the watcher may call it; they get the same
# answer because it comes from the same code.
#
# Reads:
#   state/<TAG>.status  - DONE | SKIPPED: <why> | RELAYED: <CONT> | BLOCKED: <why>
#   state/<TAG>.next    - the successor tag, wired at setup, overwritable by the session
#                         before it writes its status. Empty means the chain ends here.
#   state/PAUSED        - present while the sprint is waiting on quota
# Appends one line to state/EVENTS.log for the morning ledger, always.

set -uo pipefail

WS="${1:?usage: advance.sh <WORKSPACE> <TAG>}"
TAG="${2:?usage: advance.sh <WORKSPACE> <TAG>}"

STATE="$WS/state"
mkdir -p "$STATE"

note() {
  printf '%s advance %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TAG" "$*" >> "$STATE/EVENTS.log"
  printf 'advance: %s %s\n' "$TAG" "$*"
}

STATUS_FILE="$STATE/$TAG.status"
[ -f "$STATUS_FILE" ] || { echo "advance: $TAG has not reported a status yet - nothing to do" >&2; exit 3; }
status="$(head -1 "$STATUS_FILE")"

case "$status" in
  BLOCKED*)
    note "blocked - launching nothing (${status#BLOCKED})"
    exit 2
    ;;
  RELAYED*)
    # The ticket is STILL IN FLIGHT. Its continuation tag wins over the wired successor,
    # every time. Reading RELAYED as DONE is what once launched the next ticket on top of
    # half of the previous one, with both sessions committing to the same branch.
    next="${status#RELAYED}"; next="${next#:}"; next="$(printf '%s' "$next" | tr -d '[:space:]')"
    reason="relay"
    ;;
  DONE*|SKIPPED*)
    next=""
    [ -f "$STATE/$TAG.next" ] && next="$(tr -d '[:space:]' < "$STATE/$TAG.next")"
    reason="$(printf '%s' "$status" | cut -d: -f1 | tr '[:upper:]' '[:lower:]')"
    ;;
  *)
    # An unrecognised status is a terminal state all the same - a session wrote something.
    # Treat it as done for chaining, and say plainly that it was not one of the four words.
    next=""
    [ -f "$STATE/$TAG.next" ] && next="$(tr -d '[:space:]' < "$STATE/$TAG.next")"
    reason="unrecognised-status"
    ;;
esac

if [ -z "$next" ]; then
  note "$reason - no successor wired, the chain ends here"
  exit 0
fi

if [ -f "$STATE/PAUSED" ]; then
  note "$reason -> $next HELD: sprint paused ($(head -1 "$STATE/PAUSED" 2>/dev/null))"
  exit 4
fi

# Already finished, or already running. Either way this is not ours to start. The atomic
# claim inside launch.sh is the real guard against a double start; this is just quieter.
if [ -f "$STATE/$next.status" ]; then
  note "$reason -> $next already terminal ($(head -1 "$STATE/$next.status"))"
  exit 0
fi

note "$reason -> launching $next"
exec bash "$WS/launch.sh" "$WS" "$next"
