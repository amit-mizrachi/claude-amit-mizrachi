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
# session is alive, stuck, gone, or filling up, and emits an event the moment that changes.
#
# Event vocabulary (first token is the verdict, second is the tag, third is the cause you
# hand to revive.sh):
#   DONE     <tag>                        - session finished and said so
#   BLOCKED  <tag> <reason>               - session finished and reported a blocker
#   RELAYED  <tag> <cont-tag>             - session ran low on context and handed its ticket on
#   WARN     <tag> used-<N>pct <id>       - crossed WARN_AT_USED. Nudge it with remind.sh:
#                                           start nothing new, finish what is in flight
#   FAT      <tag> used-<N>pct <id>       - crossed RELAY_AT_USED. Hand it to relay.sh
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

# Context thresholds, pinned by the conductor at kickoff. ALL THREE ARE PERCENT USED, the way
# `/context` reports it: 0 is a fresh session, 100 is a full one. They count UP.
#
#   CONTEXT_WINDOW   - total tokens the sprint's model can hold. Cannot be read off the
#                      transcript (a 1M model records the same name as the 200k one), so it is
#                      a pinned fact or the 200k default.
#   WARN_AT_USED     - the nudge. The session is still comfortable but has spent enough that
#                      opening a new front is a bad bet. remind.sh tells it to start nothing new.
#   RELAY_AT_USED    - the handoff. Deliberately early: a session that hands off at 30% used
#                      still has 70% of a window to write a handoff its successor can act on,
#                      and the successor gets a full window for the rest of the ticket. Several
#                      sessions per ticket is the intended shape, not a failure.
#   CEILING_USED     - the floor guard's ceiling, read by relay.sh. See the note there.
CONTEXT_WINDOW=200000
[ -f "$WS/CONTEXT_WINDOW" ] && CONTEXT_WINDOW="$(tr -d '[:space:]' < "$WS/CONTEXT_WINDOW")"
WARN_AT_USED=20
[ -f "$WS/WARN_AT_USED" ] && WARN_AT_USED="$(tr -d '[:space:]' < "$WS/WARN_AT_USED")"
RELAY_AT_USED=30
[ -f "$WS/RELAY_AT_USED" ] && RELAY_AT_USED="$(tr -d '[:space:]' < "$WS/RELAY_AT_USED")"
CEILING_USED=60
[ -f "$WS/CEILING_USED" ] && CEILING_USED="$(tr -d '[:space:]' < "$WS/CEILING_USED")"
GAUGE="$WS/context-used.sh"

now_epoch() { date +%s; }

# THE FLOOR. A relay is only worth doing once the session has something to hand over.
#
# At 30% used the handoff line sits close to a session's startup cost: reading PLAN.md, the
# ticket, LOG.md, `git log`, and the two or three files whose pattern the ticket must mirror can
# spend that much on its own, especially on a 200k window. A session relayed at that point hands
# its successor nothing but a list of files it read - and the successor starts by reading them
# again. Do that twice and the ticket never gets built; the sprint just re-reads itself all night.
#
# So the relay waits for evidence of work: a commit that was not there when this tag launched, or
# an uncommitted change in the worktree. Only one session touches the worktree at a time, so any
# dirt in it is this session's.
#
# CEILING_USED is the escape hatch. A session that has burned that much window without changing a
# single file is not about to start; the ticket is bigger than the plan thought, or it is stuck in
# a reading loop. Relaying there at least passes the reading on, and the resulting chain of
# continuations is exactly the signal the morning report should carry: this ticket was too big.
tag_has_produced_work() {
  local tag="$1" base
  [ -n "$WT" ] || return 0                       # no worktree pinned - do not block the relay
  base="$STATE/$tag.headsha"
  [ -f "$base" ] || return 0                     # launched before the floor existed - same
  [ -n "$(git -C "$WT" status --porcelain 2>/dev/null)" ] && return 0
  [ "$(git -C "$WT" rev-parse HEAD 2>/dev/null)" != "$(tr -d '[:space:]' < "$base")" ] && return 0
  return 1
}

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
        # Ran out of room, not out of road. The ticket is still in flight under the
        # continuation tag, so this must never be read as the ticket being finished.
        RELAYED*) cont="${line#RELAYED}"; cont="${cont#:}"
                  emit_once "$tag:RELAYED" "RELAYED $tag ${cont# }" ;;
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
        # How full is it? Checked before the stall check, because a session with no window
        # left is worth relaying while it can still explain itself - waiting until it goes
        # quiet means it has already lost the reasoning the successor needs.
        #
        # Two rungs, and the ORDER MATTERS. A session can jump from 12% to 35% used in a
        # single poll (one big read), and in that case the nudge is pointless - it is already
        # past the handoff line. So the relay rung is tested FIRST, and firing it also burns
        # the nudge so no remind.sh call chases a session that is already relaying.
        #
        # `.relayed` and `.warned` are the one-shot guards: relay.sh and remind.sh drop them.
        # They are separate files from the seen-list because relay.sh CLEARS this tag's rows
        # out of the seen-file (so a later death is still reported), which would otherwise let
        # both rungs refire.
        if [ -x "$GAUGE" ] && [ ! -f "$STATE/$tag.relayed" ]; then
          used="$(bash "$GAUGE" "$sid" "$CONTEXT_WINDOW" 2>/dev/null)"
          case "$used" in
            ''|*[!0-9]*) : ;;   # no reading this round - say nothing rather than guess
            *)
              if [ "$used" -ge "$RELAY_AT_USED" ]; then
                # Past the handoff line - but hold the relay until this session has actually
                # produced something, unless it is past the ceiling. See tag_has_produced_work.
                if tag_has_produced_work "$tag" || [ "$used" -ge "$CEILING_USED" ]; then
                  grep -qxF "$tag:WARN" "$SEEN" 2>/dev/null \
                    || printf '%s\n' "$tag:WARN" >> "$SEEN"
                  emit_once "$tag:FAT" "FAT $tag used-${used}pct $sid"
                elif [ ! -f "$STATE/$tag.warned" ]; then
                  # Still worth the nudge: it has read a third of its window and changed
                  # nothing, so "start nothing new" is exactly the advice it needs.
                  emit_once "$tag:WARN" "WARN $tag used-${used}pct $sid"
                fi
              elif [ "$used" -ge "$WARN_AT_USED" ] && [ ! -f "$STATE/$tag.warned" ]; then
                emit_once "$tag:WARN" "WARN $tag used-${used}pct $sid"
              fi
              ;;
          esac
        fi

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
