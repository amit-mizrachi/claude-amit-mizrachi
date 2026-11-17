#!/usr/bin/env bash
# night-sprint conductor retirement - take a conductor that relayed off the agent list.
#
#   retire.sh <WORKSPACE> --self [SESSION_FILE]   the relaying conductor records itself
#   retire.sh <WORKSPACE> [--wait SECONDS]        remove every recorded conductor whose turn ended
#
# Exit codes:
#   0  nothing is left to remove
#   1  not yet - a retired conductor is still finishing its last turn, or it would not go away
#
# WHY THIS EXISTS. A conductor relays itself through `next-prompt` every time its window fills.
# The old conductor ends its turn and then sits on the agent list for good: nothing ever closed
# it, because close.sh closes TAGS and a conductor has no tag. A night of nine relays left nine
# conductor rows (2026-11-17), all but the last one finished. One sprint should end as one
# session.
#
# A session cannot remove itself - the removal would kill the turn that is running it. So the
# relaying conductor only RECORDS itself here, as the last thing before it launches its successor,
# and somebody else removes it once its turn has ended: the runner, every sweep and on its way
# out, and the successor conductor on arrival, for the relay that happens after the runner exited.
#
# THE RULES, the same ones close.sh keeps:
#   - never mid-turn. The relaying conductor launches its successor inside its last turn; removing
#     it there can kill the launch. It is left until its turn has closed, or until it was recorded
#     longer ago than the stall window, which means it is hung, not finishing.
#   - never the caller. A conductor that sweeps skips its own id.
#   - never a session something still watches. A phase conductor (night-marathon) passes its
#     phase's session file with --self. Until the successor has repointed that file, the phase
#     runner still follows the old id, and removing it would read as a death and be revived.
#
# `claude rm` keeps the transcript, so a removed conductor is still reopened with
# `claude --resume <sessionId>`.
#
# Reads and writes, in state/:
#   conductors.retired   - one line per relay: `<session id> <epoch> [session file]`
#   .retired-<short id>  - so each conductor is removed once
#   EVENTS.log           - one line per removal, for the morning ledger

set -uo pipefail

WS="${1:?usage: retire.sh <WORKSPACE> [--self [SESSION_FILE] | --wait SECONDS]}"
STATE="$WS/state"
LIST="$STATE/conductors.retired"
STALL_MIN=25   # matches close.sh and watch.sh's default STALL_MINUTES
ME="${CLAUDE_CODE_SESSION_ID:-}"

note() {
  printf '%s retire %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$STATE/EVENTS.log"
  printf 'retire: %s\n' "$*"
}

if [ "${2:-}" = "--self" ]; then
  [ -n "$ME" ] || { echo "retire: no session id (CLAUDE_CODE_SESSION_ID unset?)" >&2; exit 1; }
  mkdir -p "$STATE"
  grep -q "^$ME " "$LIST" 2>/dev/null || printf '%s %s %s\n' "$ME" "$(date +%s)" "${3:-}" >> "$LIST"
  note "recorded conductor $ME - removed once its turn has ended"
  exit 0
fi

WAIT=0
[ "${2:-}" = "--wait" ] && WAIT="${3:-60}"

[ -s "$LIST" ] || exit 0

# shellcheck source=agents.sh
. "$WS/agents.sh"

sweep() {
  local pending=0 rows sid at sfile mark row age
  if ! rows="$(agents_json)"; then
    echo "retire: cannot read the agent list - nothing removed; the next sweep retries" >&2
    return 1
  fi
  while read -r sid at sfile; do
    [ -n "$sid" ] || continue
    mark="$STATE/.retired-${sid%%-*}"
    [ -f "$mark" ] && continue
    [ "$sid" = "$ME" ] && continue
    if [ -n "$sfile" ] && [ "$(tr -d '[:space:]' < "$sfile" 2>/dev/null)" = "$sid" ]; then
      pending=1   # its successor has not taken the phase over yet
      continue
    fi
    row="$(printf '%s' "$rows" | python3 -c 'import json,sys
sid=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: print("unknown"); sys.exit(0)
for r in rows:
    if r.get("sessionId")==sid or r.get("id")==sid[:8]:
        print("live" if r.get("pid") else "exited"); break' "$sid")"
    if [ -z "$row" ]; then
      : > "$mark"
      note "conductor $sid already off the list"
      continue
    fi
    case "$at" in ''|*[!0-9]*) at=0 ;; esac
    age=$(( ( $(date +%s) - at ) / 60 ))
    if [ "$row" != "exited" ] && [ "$age" -lt "$STALL_MIN" ] && ! turn_ended "$sid"; then
      pending=1
      continue
    fi
    if remove_session "$sid"; then
      : > "$mark"
      note "removed conductor $sid"
    else
      note "FAILED to remove conductor $sid"
      pending=1
    fi
  done < "$LIST"
  return "$pending"
}

deadline=$(( $(date +%s) + WAIT ))
while true; do
  sweep && exit 0
  [ "$(date +%s)" -ge "$deadline" ] && exit 1
  sleep 5
done
