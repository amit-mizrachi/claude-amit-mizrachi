#!/usr/bin/env bash
# night-sprint shared helper - ask the harness about background sessions, reliably.
#
# Sourced, not run:  . "$WS/agents.sh"
# Provides:          agents_json [WORKTREE]   -> a JSON array on stdout, never empty output
#                    turn_ended SID|FILE      -> 0 if its last turn closed (it waits for a message)
#                    session_pid SID          -> the pid of a LIVE session, or nothing
#                    stop_session SID         -> stop it, and return 0 only once it is gone
#                    remove_session SID       -> stop it and take it off the agent list
#
# WHY THIS EXISTS. Three scripts need the same list, and they used to each call
# `claude agents --json --all --cwd "$WT"` their own way. That filter has been observed to
# return `[]` for a worktree whose sessions are demonstrably running under exactly that cwd.
# Every caller then drew the same wrong conclusion: no rows for this tag, so the session is
# gone. The watcher reported healthy sessions as DIED, and the reviver could not resolve the
# id of a session it had just started. One sprint patched it locally and the fix never
# reached the skill, which is the other half of the bug.
#
# So: ask with the filter, and if that comes back empty ask again without it. An unfiltered
# list is never wrong, only broader - and every caller here already matches on the session
# name or id, which is what actually narrows the answer. The filter is an optimisation; it
# is not allowed to be the source of truth.

# shellcheck shell=bash

agents_json() {
  # PATCHED (machina-feedback sprint, 2026-09-23): the WORKTREE argument is accepted and IGNORED.
  # `claude agents --cwd <wt>` has returned `[]` on this harness, and has also returned ONE
  # UNRELATED row - a non-empty answer the old fallback trusted, which made the runner call the
  # sprint's own live sessions dead. Every caller already matches rows by name or session id, so
  # the unfiltered list is both sufficient and correct.
  local out=""
  out="$(claude agents --json --all 2>/dev/null || true)"
  out="$(printf '%s' "$out" | tr -d '\000')"
  case "$(printf '%s' "$out" | tr -d '[:space:]')" in
    "") printf '[]' ;;
    *)  printf '%s' "$out" ;;
  esac
}

# ---------------------------------------------------------------- did it end its own turn?
#
# turn_ended SID|TRANSCRIPT -> 0 when the session's last turn CLOSED: the transcript's last
# conversation record is the harness's `turn_duration` marker, written when a turn finishes and
# the session goes back to waiting for its next message.
#
# This is the one signal that tells a conductor that is WAITING from one that is stuck or dead,
# and the harness's own labels cannot. Seen on 2026-10-02: a review-mode conductor that posted
# the plan link and ended its turn to wait for the user's picks showed as `state:blocked` - the
# same label as a permission prompt and as a session that ended on an API error. A conductor
# waiting on its Monitor showed as `status:busy` - the same label as a model call that hung. The
# runner read both as stuck, stopped the conductor the user was about to answer, and restarted it.
#
# A real permission prompt, a hung call and a process killed mid-step all stop MID-turn: the last
# record is a tool call or a message, never the marker. An API error also ends the turn, so the
# callers pair this with classify-error.sh: no error AND a closed turn is a session that waits.
turn_ended() {
  local f="$1"
  [ -f "$f" ] || f="$(ls -t "$HOME"/.claude/projects/*/"$1".jsonl 2>/dev/null | head -1)"
  [ -n "$f" ] || return 1
  tail -n 200 "$f" 2>/dev/null | python3 -c 'import json,sys
last=None
for line in sys.stdin:
    try: r=json.loads(line)
    except Exception: continue
    if r.get("isSidechain"): continue
    t=r.get("type")
    if t in ("user","assistant"): last="turn"
    elif t=="system" and r.get("subtype")=="turn_duration": last="ended"
sys.exit(0 if last=="ended" else 1)'
}

# ---------------------------------------------------------------- stopping a session, for real
#
# `claude stop` takes the SHORT session id - the `id` field of `claude agents --json`, the eight
# characters the launch banner echoes back. Handed the FULL session UUID that
# state/<TAG>.session holds, it matches nothing, prints "No job matching ..." and exits 1
# WITHOUT stopping anything.
#
# That is how a sprint ends up with two agents in one worktree. The stop silently did nothing -
# its output was discarded and its exit status never read - the `claude --bg --resume` below
# forked a SECOND live session off the same conversation, and the original process carried on
# working. Unwatched, too: state/<TAG>.session had already been repointed at the fork, so the
# watcher followed the new session while the real work went on in the one nobody was reading.
# Both then committed to the same branch.
#
# So: stop by short id, and treat "still alive" as a hard failure. Nothing may be resumed or
# launched for a tag whose previous session is still running.

# The pid the harness holds for a LIVE session. A finished one carries no pid and `state:done`.
session_pid() {
  agents_json | python3 -c 'import json,sys
sid=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
for r in rows:
    if r.get("sessionId")==sid or r.get("id")==sid[:8]:
        if r.get("pid") and r.get("state")!="done": print(r["pid"])
        break' "$1"
}

# stop_session SID -> 0 once the process is gone (or there was none), 1 if it will not stop.
# Stop a session and do not report success until its process is actually gone. Escalates only if
# the clean stop does not take: a duplicate live session costs the sprint far more than a hard
# kill does, and the conversation is on disk either way, so it stays resumable.
stop_session() {
  local sid="$1" short pid rc i
  case "$sid" in ""|unresolved) return 0 ;; esac
  short="${sid%%-*}"

  pid="$(session_pid "$sid")"
  claude stop "$short" >/dev/null 2>&1
  rc=$?

  # No live pid means there is nothing to wait for - the usual case when reviving a session that
  # already died. `claude stop` reporting "No job matching" there is correct, not a failure.
  [ -n "$pid" ] || return 0

  for i in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 1
  done

  # Only ever signal a process that is still the claude session we looked up. A pid the OS has
  # recycled onto something else must not be killed because a sprint wanted its slot back.
  case "$(ps -o command= -p "$pid" 2>/dev/null)" in
    *claude*) : ;;
    *) return 0 ;;
  esac

  echo "stop_session: $short (pid $pid) ignored 'claude stop' (rc=$rc) - sending SIGTERM" >&2
  kill -TERM "$pid" 2>/dev/null
  for i in $(seq 1 10); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 1
  done

  echo "stop_session: $short (pid $pid) survived SIGTERM - sending SIGKILL" >&2
  kill -KILL "$pid" 2>/dev/null
  for i in $(seq 1 5); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 1
  done

  echo "stop_session: $short (pid $pid) will not stop" >&2
  return 1
}

# ---------------------------------------------------------------- removing a finished session
#
# A stopped session stays on the agent list as `state:done` until something removes it, so
# stopping alone still leaves one row per tag in the morning. `claude rm` takes it off the list.
#
# `rm` does NOT delete the sprint's worktree. It deletes only a worktree the session created
# itself (`claude --worktree`). A sprint session is launched with `cd "$WT" && claude --bg`, so it
# runs in a worktree it does not own. Checked on 2.1.280: after `claude rm` on a `done idle`
# session in `.claude/worktrees/<slug>`, the worktree, its branch, an unpushed commit and an
# untracked file were all still there. The transcript stays on disk too, so
# `claude --bg --resume <sessionId>` still continues the conversation; only `claude attach <id>`
# stops working, because there is no listed job left to attach to.

# session_listed SID -> 0 if the agent list still has a row for it. An unreadable list counts as
# listed, so a bad read makes a removal retry instead of passing.
session_listed() {
  agents_json | python3 -c 'import json,sys
sid=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
sys.exit(0 if any(r.get("sessionId")==sid or r.get("id")==sid[:8] for r in rows) else 1)' "$1"
}

# remove_session SID -> 0 once it is off the list (or was never on it), 1 if it is still there.
# Stops it first through stop_session, so a live process gets the same wait and escalation.
remove_session() {
  local sid="$1" short i
  case "$sid" in ""|unresolved) return 0 ;; esac
  short="${sid%%-*}"

  session_listed "$sid" || return 0
  stop_session "$sid" || return 1

  for i in 1 2 3; do
    claude rm "$short" >/dev/null 2>&1
    session_listed "$sid" || return 0
    sleep 1
  done

  echo "remove_session: $short is still listed after 'claude rm'" >&2
  return 1
}
