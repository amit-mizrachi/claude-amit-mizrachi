#!/usr/bin/env bash
# night-sprint watcher - emits ONE line per state change; each line becomes a Monitor event.
#
#   watch.sh <WORKSPACE> [POLL_SECONDS] [STALL_MINUTES]
#
# Reads two kinds of files the sessions write into <WORKSPACE>/state/:
#   <tag>.session  - the launcher writes the background session id here, one line
#   <tag>.status   - the session writes its own terminal status here: "DONE" or "BLOCKED: reason"
#
# For every tag that has a .session but no .status yet, it decides whether that
# session is alive, stuck, or gone, and emits an event the moment that changes.
#
# Event vocabulary (first token is the verdict, second is the tag, third is the cause you
# hand to revive.sh):
#   DONE     <tag>                        - session finished and said so
#   BLOCKED  <tag> <reason>               - session finished and reported a blocker
#   STUCK    <tag> permission-prompt <id> - sitting on a prompt nobody can answer
#   DIED     <tag> api-error <id>         - the API dropped it. RESUMABLE - the conversation is intact
#   DIED     <tag> ended-without-signal <id> - process gone, no status written, no API error
#   STALLED  <tag> api-error <id> (idle <N>m) - hit an API error and never came back
#   STALLED  <tag> idle-<N>m <id>         - alive but no transcript activity for N minutes
#   SWEEP    <n-open> tags=<...>          - heartbeat, once every 10 polls, so silence != dead watcher
#
# Each (tag, verdict) is emitted at most once. Exits 0 when every tag that has a
# .session also has a .status - i.e. nothing is left running.

set -uo pipefail

WS="${1:?usage: watch.sh <WORKSPACE> [POLL_SECONDS] [STALL_MINUTES]}"
POLL="${2:-120}"
STALL_MIN="${3:-25}"

STATE="$WS/state"
SEEN="$STATE/.watch-seen"
mkdir -p "$STATE"
: > "$SEEN"

# Resolve the worktree once so we can scope `claude agents` to this sprint only.
WT=""
[ -f "$WS/WORKTREE" ] && WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"

now_epoch() { date +%s; }

# mtime of a file, portable across macOS (BSD stat) and Linux (GNU stat)
mtime_of() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null; }

# Last activity of a background session = mtime of its transcript jsonl.
session_last_activity() {
  local sid="$1" f
  f="$(ls -t "$HOME"/.claude/projects/*/"$sid".jsonl 2>/dev/null | head -1)"
  [ -n "$f" ] && mtime_of "$f"
}

# Was this session's last breath an API error rather than a clean end? The transcript records
# one as its own line with "isApiErrorMessage":true - a dropped connection, a stalled stream,
# a 529 or a 500. Those are infrastructure, not mistakes, and the conversation on disk is still
# good, so the conductor should resume it rather than restart the ticket from the top.
session_hit_api_error() {
  local sid="$1" f
  f="$(ls -t "$HOME"/.claude/projects/*/"$sid".jsonl 2>/dev/null | head -1)"
  [ -n "$f" ] || return 1
  tail -n 5 "$f" 2>/dev/null | grep -qE '"isApiErrorMessage": ?true'
}

emit_once() {
  local key="$1"; shift
  grep -qxF "$key" "$SEEN" 2>/dev/null && return 0
  printf '%s\n' "$key" >> "$SEEN"
  printf '%s\n' "$*"
}

sweep=0
quiet=0
QUIET_LIMIT=3   # consecutive all-terminal sweeps required before the watcher gives up
while true; do
  sweep=$((sweep + 1))

  # One `claude agents` call per poll, scoped to the sprint worktree. Never let a
  # transient failure kill the watcher - fall back to an empty list for this round.
  agents=""
  if [ -n "$WT" ]; then
    agents="$(claude agents --json --all --cwd "$WT" 2>/dev/null || true)"
  else
    agents="$(claude agents --json --all 2>/dev/null || true)"
  fi
  [ -z "$agents" ] && agents='[]'

  open_tags=""
  open_n=0

  for sf in "$STATE"/*.session; do
    [ -e "$sf" ] || continue
    tag="$(basename "$sf" .session)"
    sid="$(tr -d '[:space:]' < "$sf")"
    st="$STATE/$tag.status"

    # 1. The session reported its own outcome - that always wins.
    if [ -f "$st" ]; then
      line="$(head -1 "$st")"
      case "$line" in
        DONE*)    emit_once "$tag:DONE"    "DONE $tag" ;;
        BLOCKED*) reason="${line#BLOCKED}"; reason="${reason#:}"
                  emit_once "$tag:BLOCKED" "BLOCKED $tag ${reason# }" ;;
        *)        emit_once "$tag:STATUS"  "DONE $tag ($line)" ;;
      esac
      continue
    fi

    open_n=$((open_n + 1))
    open_tags="$open_tags $tag"

    # 2. No status file. Ask the harness what the process is doing.
    state="$(printf '%s' "$agents" \
      | python3 -c 'import json,sys
sid=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
for r in rows:
    if r.get("sessionId")==sid or r.get("id")==sid[:8]:
        print(r.get("state","")); break' "$sid" 2>/dev/null)"

    case "$state" in
      blocked)
        # Waiting on a permission prompt. A background session can never answer one.
        emit_once "$tag:STUCK" "STUCK $tag permission-prompt $sid"
        ;;
      working)
        last="$(session_last_activity "$sid")"
        if [ -n "$last" ]; then
          idle=$(( ( $(now_epoch) - last ) / 60 ))
          if [ "$idle" -ge "$STALL_MIN" ]; then
            if session_hit_api_error "$sid"; then
              emit_once "$tag:STALLED" "STALLED $tag api-error $sid (idle ${idle}m)"
            else
              emit_once "$tag:STALLED" "STALLED $tag idle-${idle}m $sid"
            fi
          fi
        fi
        ;;
      done|"")
        # Process finished or is gone entirely, but it never wrote a status file.
        # Give the filesystem one grace poll before calling it dead.
        if grep -qxF "$tag:maybe-died" "$SEEN" 2>/dev/null; then
          if session_hit_api_error "$sid"; then
            emit_once "$tag:DIED" "DIED $tag api-error $sid"
          else
            emit_once "$tag:DIED" "DIED $tag ended-without-signal $sid"
          fi
        else
          printf '%s\n' "$tag:maybe-died" >> "$SEEN"
        fi
        ;;
    esac
  done

  # Nothing left running. Do NOT exit on the first quiet sweep: a handoff has a gap
  # between one session writing its status and the next one registering its .session,
  # and an early exit would leave the conductor blind exactly at the handoff. Require
  # the quiet to hold for QUIET_LIMIT consecutive sweeps.
  if [ "$open_n" -eq 0 ] && ls "$STATE"/*.session >/dev/null 2>&1; then
    quiet=$((quiet + 1))
    if [ "$quiet" -ge "$QUIET_LIMIT" ]; then
      echo "SWEEP 0 tags= all-sessions-terminal (quiet for $quiet sweeps)"
      exit 0
    fi
  else
    quiet=0
  fi

  # Heartbeat so a quiet watcher is distinguishable from a dead one.
  if [ $(( sweep % 10 )) -eq 1 ]; then
    echo "SWEEP $open_n tags=${open_tags# }"
  fi

  sleep "$POLL"
done
