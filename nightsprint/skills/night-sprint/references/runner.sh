#!/usr/bin/env bash
# night-sprint runner control - keep watch.sh alive on its own, and let a conductor listen to it.
#
#   runner.sh start  <WS> [POLL] [STALL]   start watch.sh detached, unless one is already running
#   runner.sh follow <WS>                   the conductor's Monitor command: print what the runner says
#   runner.sh status <WS>                   prints `running <pid>` or `stopped`; exit 0 only if running
#
# WHY THE RUNNER IS NOT THE MONITOR'S CHILD ANY MORE. It used to be: the conductor armed
# `Monitor: bash <WS>/watch.sh <WS>`, so watch.sh lived exactly as long as that Monitor. On
# 2026-10-02 that cost a build four hours. The harness caps every Monitor at 30 minutes and kills
# its command at expiry, so the runner died twice an hour by design. And when the phase runner
# stopped the BUILD conductor, the runner died with it. FIX-C2 then dropped its connection 3 minutes
# later. A resume would have fixed that, but no runner was left to do it, and nothing moved until a
# person came back.
#
# So the runner is detached, exactly as phase-chain.sh detaches the phase runner: its own process
# session, stdout appended to state/runner.log, its pid in state/runner.pid. Nothing a conductor does,
# and nothing done to a conductor, stops it. It stops by itself after `SWEEP 0`, when the chain has
# nothing left to run.
#
# The conductor still hears the runner the same way, as Monitor events, through `follow`. It prints
# every complete line the runner wrote since the last follower stopped reading. The read position
# is kept in state/.follow-offset, so a Monitor that expires, or a conductor that relays, loses no
# line and repeats no line. The follower is cheap to kill and to start again; the runner is not
# touched by either.
#
# `follow` also keeps the runner up. A runner that died WITHOUT saying `SWEEP 0` (killed, crashed,
# the machine restarted) is started again, and the conductor gets one `RUNNER-RESTARTED` line. If it
# keeps dying, the follower says `RUNNER-DOWN` and exits, because a crash loop needs a person.

set -uo pipefail

CMD="${1:?usage: runner.sh start|follow|status <WS> ...}"
WS="${2:?usage: runner.sh $CMD <WS> ...}"
STATE="$WS/state"
LOG="$STATE/runner.log"
PIDF="$STATE/runner.pid"
OFFSET="$STATE/.follow-offset"
RESTARTS="$STATE/.runner-restarts"
FOLLOW_POLL="${FOLLOW_POLL:-5}"   # seconds between reads; the tests shorten it
mkdir -p "$STATE"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

runner_pid() {
  local pid
  pid="$( { tr -d '[:space:]' < "$PIDF"; } 2>/dev/null)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  # A recycled pid must not pass for the runner.
  case "$(ps -o command= -p "$pid" 2>/dev/null)" in
    *watch.sh*) printf '%s' "$pid"; return 0 ;;
  esac
  return 1
}

start_runner() {
  local poll="${1:-}" stall="${2:-}" pid
  if pid="$(runner_pid)"; then
    echo "runner: already running (pid $pid)"
    return 0
  fi
  # A restart from `follow` passes nothing, and must come back with the timings it was started
  # with - the phase runner polls every minute, a sprint runner every two.
  if [ -n "$poll" ]; then
    printf '%s %s\n' "$poll" "$stall" > "$STATE/runner.args"
  elif [ -f "$STATE/runner.args" ]; then
    read -r poll stall < "$STATE/runner.args"
  fi
  # The runner inherits this shell's cwd, and it outlives that shell by hours. Give it one nobody
  # deletes (2026-10-04: started from inputs/stage-c-spec/issues, which a peer re-copied at 07:26).
  cd "$WS" || return 1
  # setsid puts the runner in its own session, so it outlives the tool call that started it and
  # the session that ran that call. macOS has no setsid binary; python3's os.setsid is the same
  # system call. The pid survives the exec, so runner.pid names the runner itself.
  # shellcheck disable=SC2086
  nohup python3 -c 'import os, sys; os.setsid(); os.execvp("bash", ["bash"] + sys.argv[1:])' \
    "$WS/watch.sh" "$WS" $poll $stall >> "$LOG" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "$PIDF"
  printf '%s runner started pid=%s\n' "$(ts)" "$!" >> "$STATE/EVENTS.log"
  sleep 1
  if runner_pid >/dev/null; then
    echo "runner: running (pid $!), log $LOG"
  else
    echo "runner: did not stay up - see $LOG" >&2
    return 1
  fi
}

# The last complete line the runner wrote. `SWEEP 0` there, with no runner alive, means it ended
# the way it is meant to end - not a crash, so nothing to restart.
finished() {
  [ -f "$LOG" ] || return 1
  case "$(tail -n 1 "$LOG" 2>/dev/null)" in
    "SWEEP 0 "*) return 0 ;;
  esac
  return 1
}

# Print every complete line written since the stored offset, then store the new offset. A line
# still being written stays for the next read. A log shorter than the offset was replaced, so
# read it from the top. Prints the lines; exits 3 if one of them was `SWEEP 0`.
drain() {
  python3 - "$LOG" "$OFFSET" <<'PY'
import os, sys
log, off_path = sys.argv[1], sys.argv[2]
try:
    off = int(open(off_path).read().strip() or 0)
except Exception:
    off = 0
try:
    size = os.path.getsize(log)
except OSError:
    sys.exit(0)
if off > size:
    off = 0
with open(log, "rb") as f:
    f.seek(off)
    chunk = f.read(size - off)
end = chunk.rfind(b"\n")
if end < 0:
    sys.exit(0)
done = chunk[:end + 1]
text = done.decode("utf-8", "replace")
sys.stdout.write(text)
sys.stdout.flush()
open(off_path, "w").write(str(off + len(done)))
sys.exit(3 if any(l.startswith("SWEEP 0 ") for l in text.splitlines()) else 0)
PY
}

# How many times this follower restarted the runner in the last 30 minutes. One restart after a
# kill or a reboot is recovery; three inside half an hour is a runner that cannot stay up.
recent_restarts() {
  local now
  now="$(date +%s)"
  awk -v since="$(( now - 1800 ))" '$1 >= since { n++ } END { print n + 0 }' "$RESTARTS" 2>/dev/null || echo 0
}

follow() {
  local rc n
  while true; do
    drain; rc=$?
    # SWEEP 0 is the runner's last word. Stop following once it has also exited - unless a
    # conductor already started a new runner for tags that are left, which is still running.
    if [ "$rc" -eq 3 ] && ! runner_pid >/dev/null; then
      exit 0
    fi
    if ! runner_pid >/dev/null; then
      finished && exit 0
      n="$(recent_restarts)"
      if [ "$n" -ge 3 ]; then
        printf '%s runner down - %s restarts in 30m, giving up\n' "$(ts)" "$n" >> "$STATE/EVENTS.log"
        echo "RUNNER-DOWN - the runner died $n times in 30 minutes; see $LOG. Nothing is advancing or reviving the sprint."
        exit 1
      fi
      date +%s >> "$RESTARTS"
      printf '%s runner died without SWEEP 0 - restarting it\n' "$(ts)" >> "$STATE/EVENTS.log"
      if start_runner >/dev/null 2>&1; then
        echo "RUNNER-RESTARTED - the runner had died mid-run; it is running again (pid $(runner_pid))"
      fi
    fi
    sleep "$FOLLOW_POLL"
  done
}

case "$CMD" in
  start)
    start_runner "${3:-}" "${4:-}"
    ;;
  follow)
    follow
    ;;
  status)
    if pid="$(runner_pid)"; then echo "running $pid"; exit 0; fi
    echo "stopped"; exit 1
    ;;
  *)
    echo "runner: unknown command '$CMD' (start | follow | status)" >&2
    exit 1
    ;;
esac
