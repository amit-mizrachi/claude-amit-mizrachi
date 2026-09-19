#!/usr/bin/env bash
# night-sprint runner - owns the routine, escalates only what needs a judgement.
#
#   watch.sh <WORKSPACE> [POLL_SECONDS] [STALL_MINUTES] [--observe]
#
# Every line it prints becomes a Monitor event in the conductor's context, so what it prints
# is a budget. It used to print everything it saw: 28 routine heartbeats and 21 successful
# handoffs in one night, each of which the conductor read, logged and answered with the same
# scripted `launch.sh` call it could not have answered any other way. That is a model doing a
# script's job with a model's context.
#
# So this script now DOES the routine and reports the exceptions:
#
#   it does     advance the chain on a terminal status (via advance.sh)
#               revive a dead or stalled session (via revive.sh, whose ladder bounds it)
#               pause the sprint on a quota failure, wait out the limit, resume afterwards
#   it reports  a real blocker, two agents on one tag, an auth failure, a budget that never
#               came back, the first PR that needs opening, and the end of the sprint
#
# EVERYTHING it does lands in state/EVENTS.log, timestamped. That file is the ledger the
# morning report is built from, and it costs the conductor nothing until it reads it once at
# the end. Silence from this script means the sprint is running, not that it has died: a
# heartbeat follows any full hour with nothing to say.
#
# `--observe` turns the acting off and prints every verdict instead, which is the old
# behaviour. Useful for debugging a sprint by hand; never what a night run wants.
#
# Reads, per tag, in state/:
#   <tag>.session  - the launcher's background session id
#   <tag>.status   - the session's own terminal word: DONE | BLOCKED: r | RELAYED: t | SKIPPED: r
#   <tag>.next     - its successor, wired at setup, and rewritable by the session BEFORE it
#                    writes its status. advance.sh is the only thing that reads the pair.
#
# Exits 0 when every tag with a .session also has a .status - nothing is left running.

set -uo pipefail

WS="${1:?usage: watch.sh <WORKSPACE> [POLL_SECONDS] [STALL_MINUTES] [--observe]}"
POLL="${2:-120}"
STALL_MIN="${3:-25}"
ACT=1
for a in "$@"; do [ "$a" = "--observe" ] && ACT=0; done

# shellcheck source=agents.sh
. "$WS/agents.sh"

STATE="$WS/state"
SEEN="$STATE/.watch-seen"
EVENTS="$STATE/EVENTS.log"
mkdir -p "$STATE"
: > "$SEEN"

WT=""
[ -f "$WS/WORKTREE" ] && WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"
SLUG=""
[ -f "$WS/SLUG" ] && SLUG="$(tr -d '[:space:]' < "$WS/SLUG")"

# CONTEXT_WINDOW cannot be read off a transcript - a 1M model records the same name as the
# 200k one - so it is pinned at kickoff. CEILING_USED is the only context reading anything
# out here acts on, and even then it only logs: see the `working` case.
CONTEXT_WINDOW=200000
[ -f "$WS/CONTEXT_WINDOW" ] && CONTEXT_WINDOW="$(tr -d '[:space:]' < "$WS/CONTEXT_WINDOW")"
CEILING_USED=60
[ -f "$WS/CEILING_USED" ] && CEILING_USED="$(tr -d '[:space:]' < "$WS/CEILING_USED")"
GAUGE="$WS/context-used.sh"

now_epoch() { date +%s; }
mtime_of() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null; }
hhmm_of()  { date -r "$1" '+%H:%M' 2>/dev/null || date -d "@$1" '+%H:%M' 2>/dev/null; }

LAST_SPOKE="$(now_epoch)"

# log  - durable, free, goes in the ledger and nowhere near the conductor's window
# say  - a Monitor event. Costs context. Only for things a model has to decide.
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$EVENTS"; }
say() { LAST_SPOKE="$(now_epoch)"; log "EMIT $*"; printf '%s\n' "$*"; }

emit_once() {
  local key="$1"; shift
  grep -qxF "$key" "$SEEN" 2>/dev/null && return 0
  printf '%s\n' "$key" >> "$SEEN"
  say "$@"
}

# Same at-most-once bookkeeping, but for work this script performs rather than reports.
did_once() {
  local key="$1"
  grep -qxF "$key" "$SEEN" 2>/dev/null && return 1
  printf '%s\n' "$key" >> "$SEEN"
  return 0
}

session_last_activity() {
  local sid="$1" f
  f="$(ls -t "$HOME"/.claude/projects/*/"$sid".jsonl 2>/dev/null | head -1)"
  [ -n "$f" ] && mtime_of "$f"
}

# WHAT KILLED IT, not merely THAT something did. One classifier, shared with revive.sh, so
# the two can never disagree - and they used to. A `grep isApiErrorMessage` answers "was
# there an error", which lumped a dropped socket in with a spending cap and sent the reviver
# after a wall it could not climb.
classify() {
  local sid="$1"
  [ -x "$WS/classify-error.sh" ] || { echo none; return 0; }
  bash "$WS/classify-error.sh" "$sid" 2>/dev/null || echo none
}

# ------------------------------------------------------------------- doing the routine
#
# Bounded by construction. advance.sh will not start a tag that is already claimed, and
# revive.sh owns its own ladder (2 resumes, 1 restart, then abandon) and refuses outright to
# touch a session whose transcript is still growing. This loop adds one more bound: a tag it
# just acted on is left alone for a few minutes, so a resume that takes a moment to register
# is never mistaken for a second death.
ACT_COOLDOWN=$(( 5 * 60 ))

recently_acted() {
  # TWO `local`s, deliberately. In a single `local a=$1 b=$a`, the second assignment does not
  # see the first, so this read `$STATE/.acted-` with no tag on it - a path mark_acted never
  # writes. The guard returned "not recently acted" every time and the cooldown did nothing.
  local tag="$1"
  local f="$STATE/.acted-$tag" t
  [ -f "$f" ] || return 1
  t="$(mtime_of "$f")"
  [ -n "$t" ] || return 1
  [ $(( $(now_epoch) - t )) -lt "$ACT_COOLDOWN" ]
}
mark_acted() { : > "$STATE/.acted-$1"; }

# The chain moves. advance.sh decides, this just reacts to its verdict - and stays quiet
# unless the verdict is one a script cannot settle.
do_advance() {
  local tag="$1" out rc
  out="$(bash "$WS/advance.sh" "$WS" "$tag" 2>&1)"; rc=$?
  log "advance($tag) rc=$rc $out"
  case "$rc" in
    2) : ;;   # BLOCKED - the status itself is emitted below, no need to say it twice
    4) emit_once "$tag:held" "HELD $tag - sprint is paused on budget, successor not launched" ;;
  esac
  return "$rc"
}

# A dead session comes back, and the conductor hears about it only when a script cannot
# finish the job.
do_revive() {
  local tag="$1" cause="$2" out rc
  recently_acted "$tag" && { log "revive($tag) skipped - acted < ${ACT_COOLDOWN}s ago"; return 0; }
  mark_acted "$tag"
  out="$(bash "$WS/revive.sh" "$WS" "$tag" "$cause" 2>&1)"; rc=$?
  log "revive($tag,$cause) rc=$rc $out"
  case "$rc" in
    5) # Out of capacity. state/PAUSED now carries the retry time; nothing new launches until
       # it clears. Worth one event, because it is the single biggest thing that can happen to
       # a night's wall-clock and the morning report has to explain the gap.
       local at; at="$(sed -n 's/.*retry-at=\([0-9]*\).*/\1/p' "$STATE/PAUSED" 2>/dev/null)"
       say "BUDGET $tag $(head -1 "$STATE/PAUSED" 2>/dev/null | cut -d' ' -f1) retry-at $(hhmm_of "${at:-0}")"
       ;;
    6) say "AUTH $tag - re-authenticate; no retry can fix this" ;;
    7) say "BUDGET-EXHAUSTED $tag - capacity never returned" ;;
    1) emit_once "$tag:revive-refused" "REVIVE-REFUSED $tag - see EVENTS.log" ;;
  esac
  return "$rc"
}

# The wait is over, or it is not. Nothing here sleeps: the poll interval IS the wait, which
# is why a two-hour spending-limit outage costs one file read per poll and no context at all.
check_pause() {
  [ -f "$STATE/PAUSED" ] || return 0
  local head at
  head="$(head -1 "$STATE/PAUSED")"
  at="$(printf '%s' "$head" | sed -n 's/.*retry-at=\([0-9]*\).*/\1/p')"

  case "$head" in
    auth*) emit_once "sprint:auth-pause" "AUTH-PAUSE $head - the sprint is stopped until a human re-authenticates"
           return 0 ;;
  esac

  [ -n "$at" ] || { log "PAUSED with no retry-at: $head"; return 0; }
  [ "$(now_epoch)" -ge "$at" ] || { log "paused ($head), $(( (at - $(now_epoch)) / 60 ))m to go"; return 0; }

  # Capacity should be back. Clear the pause FIRST so the resumed sessions can launch their
  # successors, then bring every parked tag back on the conversation it already had.
  rm -f "$STATE/PAUSED"
  local parked="" bf tag
  for bf in "$STATE"/*.budget-blocked; do
    [ -e "$bf" ] || continue
    tag="$(basename "$bf" .budget-blocked)"
    rm -f "$bf" "$STATE/.acted-$tag"
    parked="$parked $tag"
    do_revive "$tag" budget-retry || true
  done
  say "BUDGET-CLEARED resumed${parked:- nothing}"
}

sweep=0
quiet=0
QUIET_LIMIT=3
HEARTBEAT_AFTER=$(( 60 * 60 ))   # only if a whole hour passed with nothing worth saying

while true; do
  sweep=$((sweep + 1))
  [ "$ACT" -eq 1 ] && check_pause

  agents="$(agents_json "$WT")"

  open_tags=""
  open_n=0
  any_done=0

  for sf in "$STATE"/*.session; do
    [ -e "$sf" ] || continue
    tag="$(basename "$sf" .session)"
    sid="$(tr -d '[:space:]' < "$sf")"
    st="$STATE/$tag.status"

    # 1. The session reported its own outcome. That always wins, and it is also the moment
    #    the chain moves - through advance.sh, which reads `.next` (written BEFORE the status)
    #    so a session's last-minute decision about its successor is never raced.
    if [ -f "$st" ]; then
      line="$(head -1 "$st")"
      case "$line" in
        DONE*|SKIPPED*) any_done=1 ;;
      esac
      if [ "$ACT" -eq 1 ]; then
        # Advance exactly once per tag - unless it was HELD by a pause, in which case the
        # chain still has to move when capacity comes back, so leave the marker off.
        if [ ! -f "$STATE/.advanced-$tag" ]; then
          do_advance "$tag"; arc=$?
          [ "$arc" -ne 4 ] && : > "$STATE/.advanced-$tag"
        fi
        # A blocker is the one terminal state a script must not absorb: a ticket stopped for a
        # real reason, its dependents have to be skipped, and only a model can decide which.
        case "$line" in
          BLOCKED*) reason="${line#BLOCKED}"; reason="${reason#:}"
                    emit_once "$tag:BLOCKED" "BLOCKED $tag ${reason# }" ;;
          *)        log "terminal $tag: $line" ;;
        esac
      else
        case "$line" in
          DONE*)    emit_once "$tag:DONE"    "DONE $tag" ;;
          BLOCKED*) reason="${line#BLOCKED}"; reason="${reason#:}"
                    emit_once "$tag:BLOCKED" "BLOCKED $tag ${reason# }" ;;
          RELAYED*) cont="${line#RELAYED}"; cont="${cont#:}"
                    emit_once "$tag:RELAYED" "RELAYED $tag ${cont# }" ;;
          SKIPPED*) emit_once "$tag:SKIPPED" "SKIPPED $tag ${line#SKIPPED*: }" ;;
          *)        emit_once "$tag:STATUS"  "DONE $tag ($line)" ;;
        esac
      fi
      continue
    fi

    open_n=$((open_n + 1))
    open_tags="$open_tags $tag"

    # 2. ONE TAG, ONE SESSION. Never auto-fixed: picking the live session out of two and
    #    auditing which files they overwrote in each other's blind spot is judgement, and
    #    nothing else this watcher says about the tag can be trusted until it is settled.
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
        # Sitting on a permission prompt no background session can ever answer.
        if [ "$ACT" -eq 1 ]; then
          log "STUCK $tag permission-prompt $sid"
          do_revive "$tag" permission-prompt || true
        else
          emit_once "$tag:STUCK" "STUCK $tag permission-prompt $sid"
        fi
        ;;
      working)
        # HOW FULL IS IT - and this is a LOG LINE, not a lever. Every session measures itself
        # and hands its own tag on; there is no way to message a running session and the
        # scripts that faked one forked sessions into duplicates. So a session past its own
        # ceiling is something the morning report should mention and nothing anybody can act
        # on tonight, which makes it exactly the wrong thing to spend a Monitor event on.
        if [ -x "$GAUGE" ]; then
          used="$(bash "$GAUGE" "$sid" "$CONTEXT_WINDOW" 2>/dev/null)"
          case "$used" in
            ''|*[!0-9]*) : ;;
            *) if [ "$used" -ge "$CEILING_USED" ]; then
                 if [ "$ACT" -eq 1 ]; then
                   did_once "$tag:OVERDUE" && log "OVERDUE $tag used-${used}pct $sid"
                 else
                   emit_once "$tag:OVERDUE" "OVERDUE $tag used-${used}pct $sid"
                 fi
               fi ;;
          esac
        fi

        last="$(session_last_activity "$sid")"
        if [ -n "$last" ]; then
          idle=$(( ( $(now_epoch) - last ) / 60 ))
          if [ "$idle" -ge "$STALL_MIN" ]; then
            cls="$(classify "$sid")"
            case "$cls" in
              transient*) cause=api-error ;;
              quota*|auth*) cause="${cls%% *}" ;;
              *) cause=idle ;;
            esac
            if [ "$ACT" -eq 1 ]; then
              log "STALLED $tag idle-${idle}m class=$cls $sid"
              do_revive "$tag" "$cause" || true
            else
              emit_once "$tag:STALLED" "STALLED $tag idle-${idle}m class=$cls $sid"
            fi
          fi
        fi
        ;;
      done|"")
        # The process is gone and it never wrote a status. One grace poll first, because a
        # filesystem write and a process exit do not land in the same instant.
        if grep -qxF "$tag:maybe-died" "$SEEN" 2>/dev/null; then
          cls="$(classify "$sid")"
          case "$cls" in
            transient*) cause=api-error ;;
            quota*|auth*) cause="${cls%% *}" ;;
            *) cause=ended-without-signal ;;
          esac
          if [ "$ACT" -eq 1 ]; then
            if did_once "$tag:DIED"; then
              log "DIED $tag class=$cls $sid"
              do_revive "$tag" "$cause" || true
            fi
          else
            emit_once "$tag:DIED" "DIED $tag $cause $sid (class=$cls)"
          fi
        else
          printf '%s\n' "$tag:maybe-died" >> "$SEEN"
        fi
        ;;
    esac
  done

  # The one thing the conductor owns at a DONE boundary: the draft PR. Early CI and early bot
  # review are why it opens after the first ticket rather than at the end, and writing a PR
  # body is not a script's job. Asked once, then never again.
  if [ "$any_done" -eq 1 ] && [ -n "$WT" ] && [ ! -f "$STATE/.pr-asked" ]; then
    if [ -z "$(cd "$WT" 2>/dev/null && gh pr view --json number -q .number 2>/dev/null)" ]; then
      : > "$STATE/.pr-asked"
      emit_once "sprint:needs-pr" "NEEDS-PR - a ticket has landed and the branch has no PR yet; open the draft"
    else
      : > "$STATE/.pr-asked"
    fi
  fi

  if [ "$open_n" -eq 0 ] && ls "$STATE"/*.session >/dev/null 2>&1; then
    quiet=$((quiet + 1))
    if [ "$quiet" -ge "$QUIET_LIMIT" ]; then
      say "SWEEP 0 tags= all-sessions-terminal (quiet for $quiet sweeps)"
      exit 0
    fi
  else
    quiet=0
  fi

  # A heartbeat ONLY after a full hour of having nothing to say. A busy night is silent
  # because the runner is handling it; a quiet night still proves the watcher is alive.
  if [ $(( $(now_epoch) - LAST_SPOKE )) -ge "$HEARTBEAT_AFTER" ]; then
    paused=""
    [ -f "$STATE/PAUSED" ] && paused=" PAUSED($(head -1 "$STATE/PAUSED"))"
    say "SWEEP $open_n tags=${open_tags# }$paused"
  fi

  sleep "$POLL"
done
