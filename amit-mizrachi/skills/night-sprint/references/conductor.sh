#!/usr/bin/env bash
# night-sprint conductor id - append THIS session's id to <WS>/state/CONDUCTOR.session.
#
#   conductor.sh <WS>
#
# One session id per line, newest last. The conductor runs it at kickoff, and every fresh
# conductor runs it first after a relay, so the file always ends with the conductor now in
# charge. Project Studio reads it to offer "Open conductor" on the run: the session waiting for
# the user's picks, or the one to ask what the sprint is doing. The id is $CLAUDE_CODE_SESSION_ID,
# the one `context-used.sh --self` reads. The same id twice in a row is written once.

set -uo pipefail

WS="${1:?usage: conductor.sh <WS>}"
SID="${CLAUDE_CODE_SESSION_ID:-}"
[ -n "$SID" ] || { echo "conductor: no session id (CLAUDE_CODE_SESSION_ID unset?)" >&2; exit 1; }
mkdir -p "$WS/state" || exit 1
f="$WS/state/CONDUCTOR.session"
[ "$(tail -n 1 "$f" 2>/dev/null)" = "$SID" ] || printf '%s\n' "$SID" >> "$f" || exit 1
echo "conductor: $SID"
