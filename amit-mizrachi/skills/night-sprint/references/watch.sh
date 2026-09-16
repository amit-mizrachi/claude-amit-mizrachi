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
#                                           BY ITSELF. This is the healthy path, not an alarm
#   OVERDUE  <tag> used-<N>pct <id>       - far past its own handoff line and STILL has not handed
#                                           off, so the self-managed handoff did not happen.
#                                           Nothing to run: a live session cannot be interrupted.
#                                           Log it, expect a death or an auto-compact, carry on
#   DUP      <tag> <id> <id> ...          - MORE THAN ONE live session on one tag. Two agents in
#                                           one worktree: a stop failed and the resume forked
#                                           instead of replacing. Stop all but the one doing the
#                                           work, repoint state/<tag>.session at it, and audit
#                                           the overlap - see "one tag, one session" in SKILL.md
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

# The sprint slug, so a tag's sessions can be recognised by display name. launch.sh names every
# session `ns-<SLUG>-<TAG>`, and revive/relay/remind suffix that (`-r1`, `-relay`, `-nudge`), so
# `ns-<SLUG>-<TAG>` plus `ns-<SLUG>-<TAG>-*` is exactly the set of sessions belonging to one tag.
SLUG=""
[ -f "$WS/SLUG" ] && SLUG="$(tr -d '[:space:]' < "$WS/SLUG")"

# Context thresholds, pinned by the conductor at kickoff. BOTH ARE PERCENT USED, the way
# `/context` reports it: 0 is a fresh session, 100 is a full one. They count UP.
#
# WARN_AT_USED and RELAY_AT_USED are NOT read here. They are the session's own rungs, applied
# from its own prompt, and the watcher has no lever at either of them - see the `working` case.
#
#   CONTEXT_WINDOW   - total tokens the sprint's model can hold. Cannot be read off the
#                      transcript (a 1M model records the same name as the 200k one), so it is
#                      a pinned fact or the 200k default.
#   CEILING_USED     - how full a session has to be before "it has not handed off yet" stops
#                      being a session mid-handoff and starts being one that never will. The
#                      only context reading this watcher acts on.
CONTEXT_WINDOW=200000
[ -f "$WS/CONTEXT_WINDOW" ] && CONTEXT_WINDOW="$(tr -d '[:space:]' < "$WS/CONTEXT_WINDOW")"
CEILING_USED=60
[ -f "$WS/CEILING_USED" ] && CEILING_USED="$(tr -d '[:space:]' < "$WS/CEILING_USED")"
GAUGE="$WS/context-used.sh"

now_epoch() { date +%s; }

# THE FLOOR used to live here, as a gate on the relay event: do not hand a ticket on until the
# session has produced something, because a session that hands off having only READ gives its
# successor a list of files and nothing else, and the ticket loops all night being re-read.
#
# That rule has not gone away - it moved to where it can actually be applied. The session itself
# decides whether to hand off, so the session applies its own floor, from its prompt: "if you have
# not changed a single file, do NOT hand off, keep going until you have something real to pass
# on", with CEILING_USED as the escape hatch for a ticket that turned out too big. The watcher
# cannot make that judgement from outside and no longer pretends to.

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

    # 2. ONE TAG, ONE SESSION. Nothing should be able to break this now: `launch.sh` claims a tag
    # atomically, a session hands its own tag on rather than being interrupted, and `revive.sh`
    # refuses any session whose transcript is still growing. The one remaining way in is a revive
    # of a session that looked dead and was not, so the check stays - cheaply, and here.
    #
    # It is worth keeping for what it costs. Two agents in one worktree edit each other's files
    # blind, and this watcher follows only ONE session id per tag, so the other one commits to the
    # branch unwatched. That went unnoticed for whole nights before it was an event.
    if [ -n "$SLUG" ]; then
      dup="$(printf '%s' "$agents" | python3 -c 'import json,sys
pre=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
live=[r for r in rows
      if r.get("pid") and r.get("state")!="done"
      and (r.get("name")==pre or str(r.get("name") or "").startswith(pre+"-"))]
if len(live)>1: print(" ".join(sorted(str(r.get("id") or "?") for r in live)))' "ns-$SLUG-$tag" 2>/dev/null)"
      [ -n "$dup" ] && emit_once "$tag:DUP" "DUP $tag $dup"
    fi

    # 3. No status file. Ask the harness what the process is doing.
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
        # HOW FULL IS IT - and this is a REPORT, not a lever.
        #
        # Every session manages its own window. It measures itself with the same gauge, narrows
        # at WARN_AT_USED and hands its tag to a fresh session at RELAY_AT_USED, all from its own
        # prompt. The sprint cannot send a message into a running session, and it no longer tries:
        # the old `WARN` and `FAT` events drove scripts that did `claude stop` + `--bg --resume`,
        # which forked the session whenever the stop failed and put two agents in one worktree.
        #
        # So the watcher says nothing at the two rungs - the session is already handling them, and
        # an event nobody can act on is noise. It speaks up only when the session is FAR past its
        # own line and still has not handed off, which means the self-managed handoff did not
        # happen. There is no fix for that from out here. It is a line for the morning report, and
        # a hint to expect this tag to die or auto-compact.
        #
        # The margin matters: a session that hits RELAY_AT_USED spends real time consolidating and
        # writing its continuation prompt, and it is ABOVE the line for all of it. Firing at the
        # line itself would flag every correct handoff. CEILING_USED is far enough past it that a
        # session still there is genuinely not handing off.
        if [ -x "$GAUGE" ]; then
          used="$(bash "$GAUGE" "$sid" "$CONTEXT_WINDOW" 2>/dev/null)"
          case "$used" in
            ''|*[!0-9]*) : ;;   # no reading this round - say nothing rather than guess
            *)
              if [ "$used" -ge "$CEILING_USED" ]; then
                emit_once "$tag:OVERDUE" "OVERDUE $tag used-${used}pct $sid"
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
