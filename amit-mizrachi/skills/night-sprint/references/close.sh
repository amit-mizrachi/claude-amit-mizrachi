#!/usr/bin/env bash
# night-sprint closer - take a session that has already finished its ticket off the agent list.
#
#   close.sh <WORKSPACE> <TAG> [--force]
#
# Exit codes, because the watcher acts on them:
#   0  closed, or there was nothing left to close
#   1  not yet - the session is still finishing its last turn, or it would not go away
#   3  the tag has not reported a terminal status, so it is not ours to close
#
# WHY THIS EXISTS. A session that writes its status and ends its turn does not exit. It sits
# in the harness as `state:done status:idle` with a live process, and a night of twenty tags
# left twenty of those behind - every ticket, every review, every fixer, every continuation -
# so the morning agent view was a wall of finished sessions with the conductor somewhere in
# it. Once a tag is terminal its session has nothing left to do: the chain has moved on and
# the work is on the branch. Only the conductor should be left on the list at the end.
#
# Stopping is not enough. A stopped session is still a listed job (`state:done`, no pid), so
# the first version of this script, which only ran `claude stop`, ended the processes and still
# left the wall of rows. So it removes: `remove_session` in agents.sh stops the session and then
# runs `claude rm`.
#
# THE ONE RULE: never stop a session in the middle of a turn. A session writes its status
# and THEN, still inside that turn, calls advance.sh, which launches the successor. Stopping
# it there can kill the launch between the claim and the session id, and strand the chain.
# So a `busy` session is left alone - unless its status is older than the stall window,
# which means it is hung, not finishing. `--force` skips the wait; the watcher uses it only
# on its way out, when every tag is terminal and nothing is left to launch.
#
# `claude rm` does not touch the shared worktree - it deletes only a worktree the session
# created itself, and sprint sessions are launched inside one they did not create (see
# agents.sh). The transcript stays on disk, so a removed BLOCKED session is still reopened with
# `cd <worktree> && claude --resume <sessionId>`, and revive.sh can still `--resume` it.
#
# Writes:
#   state/.closed-<TAG> - so each tag is closed once
#   state/EVENTS.log    - one line per close, for the morning ledger

set -uo pipefail

WS="${1:?usage: close.sh <WORKSPACE> <TAG> [--force]}"
TAG="${2:?usage: close.sh <WORKSPACE> <TAG> [--force]}"
FORCE=0
[ "${3:-}" = "--force" ] && FORCE=1

# shellcheck source=agents.sh
. "$WS/agents.sh"

STATE="$WS/state"
STALL_MIN=25   # matches watch.sh's default STALL_MINUTES
MARK="$STATE/.closed-$TAG"

note() {
  printf '%s close %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TAG" "$*" >> "$STATE/EVENTS.log"
  printf 'close: %s %s\n' "$TAG" "$*"
}

[ -f "$STATE/$TAG.status" ] || { echo "close: $TAG has no status yet - not closing a live ticket" >&2; exit 3; }
[ -f "$MARK" ] && exit 0

sid="$(tr -d '[:space:]' < "$STATE/$TAG.session" 2>/dev/null || echo)"
case "$sid" in
  ""|unresolved) : > "$MARK"; note "no session id to close"; exit 0 ;;
esac

# The harness's own word for it: does it still hold a process, and is a model call running?
row="$(agents_json | python3 -c 'import json,sys
sid=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: print("unknown -"); sys.exit(0)
for r in rows:
    if r.get("sessionId")==sid or r.get("id")==sid[:8]:
        print("live" if r.get("pid") else "exited", r.get("status") or "-"); break' "$sid")"
live="${row%% *}"
status="${row#* }"

if [ -z "$row" ]; then
  : > "$MARK"
  note "already off the list ($sid)"
  exit 0
fi

if [ "$live" = "live" ] && [ "$status" = "busy" ] && [ "$FORCE" -eq 0 ]; then
  written="$(stat -f %m "$STATE/$TAG.status" 2>/dev/null || stat -c %Y "$STATE/$TAG.status" 2>/dev/null)"
  age=$(( ( $(date +%s) - ${written:-0} ) / 60 ))
  if [ "$age" -lt "$STALL_MIN" ]; then
    echo "close: $TAG ($sid) is still finishing its last turn - leaving it for the next sweep"
    exit 1
  fi
fi

if remove_session "$sid"; then
  : > "$MARK"
  note "removed $sid ($(head -1 "$STATE/$TAG.status"))"
  exit 0
fi
note "FAILED to remove $sid"
exit 1
