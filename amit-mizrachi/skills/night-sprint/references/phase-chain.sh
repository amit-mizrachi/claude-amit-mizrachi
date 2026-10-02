#!/usr/bin/env bash
# night-sprint phase chain - one runner over a whole multi-conductor run.
#
#   phase-chain.sh init   <PWS> <SKILL_REFERENCES_DIR> <SLUG>
#   phase-chain.sh add    <PWS> <PHASE> <CWD> [NEXT_PHASE]
#   phase-chain.sh start  <PWS> <PHASE>      launch the first phase, then start the runner
#   phase-chain.sh runner <PWS>              start the detached runner unless one is running
#
# A night-marathon run is several conductors in a row: the research conductor, then one build
# conductor per PR. Inside each sprint, watch.sh revives a ticket session that dies. Nothing
# used to watch the conductors themselves, or the hop between them: a conductor launched its
# successor with a bare `claude --bg`, saw it `busy` six seconds later, and ended. On 2026-10-02
# that successor died 2.5 minutes in on "API Error: Connection lost mid-response" - a transient
# error a resume fixes - and the run sat dead for six hours until a person noticed.
#
# So a phase chain is an ordinary night-sprint workspace whose tags are PHASES:
#   state/<PHASE>.cwd      where the phase conductor runs (its repo, or the run workspace)
#   state/<PHASE>.next     the phase after it
#   state/<PHASE>.session  its live session id - written by launch.sh, by revive.sh after a
#                          resume, and by the conductor itself on start and after every relay
#   state/<PHASE>.status   DONE | BLOCKED: <reason>, written by the conductor as its LAST action
#   prompt-<PHASE>.txt     its rendered prompt, which must exist before its predecessor is DONE
#   PHASE_CHAIN            the marker that puts watch.sh and revive.sh into phase mode
#
# and ONE runner, watch.sh, runs over it for the whole run, detached from every session, so no
# conductor's death can take it down. It launches the next phase through advance.sh when a
# conductor writes DONE, and revives a dead conductor through revive.sh - classify, resume on
# the same conversation in the same cwd, then restart, then abandon - repointing the session file
# each time. A conductor that ended its own turn with no error is waiting, not dead, and is left
# alone. Every launch, death and revive lands in state/EVENTS.log; the reports read it from there.

set -uo pipefail

CMD="${1:?usage: phase-chain.sh init|add|start|runner <PWS> ...}"
PWS="${2:?usage: phase-chain.sh $CMD <PWS> ...}"

# A conductor is quiet for long stretches (a Monitor wait, a review-mode gate), and its quiet
# costs nothing to check because the classifier, not the clock, decides whether it is dead. So
# the phase runner looks sooner than a sprint runner: a dead conductor is found in minutes.
POLL=60
STALL=5

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

runner_alive() {
  local pid
  pid="$( { tr -d '[:space:]' < "$PWS/state/runner.pid"; } 2>/dev/null)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  case "$(ps -o command= -p "$pid" 2>/dev/null)" in
    *watch.sh*) return 0 ;;
  esac
  return 1
}

start_runner() {
  if runner_alive; then
    echo "phase-chain: runner already running (pid $(cat "$PWS/state/runner.pid"))"
    return 0
  fi
  # setsid puts the runner in its own session, so it outlives the tool call that started it and
  # the session that ran that call. macOS has no setsid binary; python3's os.setsid is the same
  # system call. The pid survives the exec, so runner.pid names the runner itself.
  nohup python3 -c 'import os, sys; os.setsid(); os.execvp("bash", ["bash"] + sys.argv[1:])' \
    "$PWS/watch.sh" "$PWS" "$POLL" "$STALL" >> "$PWS/state/runner.log" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "$PWS/state/runner.pid"
  printf '%s runner started pid=%s\n' "$(ts)" "$!" >> "$PWS/state/EVENTS.log"
  sleep 1
  if runner_alive; then
    echo "phase-chain: runner running (pid $!), log $PWS/state/runner.log"
  else
    echo "phase-chain: runner did not stay up - see $PWS/state/runner.log" >&2
    return 1
  fi
}

case "$CMD" in
  init)
    REF="${3:?usage: phase-chain.sh init <PWS> <SKILL_REFERENCES_DIR> <SLUG>}"
    SLUG="${4:?usage: phase-chain.sh init <PWS> <SKILL_REFERENCES_DIR> <SLUG>}"
    mkdir -p "$PWS/state"
    missing=""
    for f in agents.sh launch.sh advance.sh watch.sh revive.sh close.sh classify-error.sh context-used.sh phase-chain.sh; do
      if [ -f "$REF/$f" ]; then cp "$REF/$f" "$PWS/$f"; else missing="$missing $f"; fi
    done
    [ -z "$missing" ] || { echo "phase-chain: FAILED - missing from $REF:$missing" >&2; exit 1; }
    chmod +x "$PWS"/*.sh
    printf '%s\n' "$SLUG" > "$PWS/SLUG"
    [ -f "$PWS/PERMISSION_MODE" ] || printf 'auto\n' > "$PWS/PERMISSION_MODE"
    : > "$PWS/PHASE_CHAIN"
    printf '%s phase chain ready\n' "$(ts)" >> "$PWS/state/EVENTS.log"
    echo "phase-chain: $PWS ready"
    ;;
  add)
    PHASE="${3:?usage: phase-chain.sh add <PWS> <PHASE> <CWD> [NEXT_PHASE]}"
    DIR="${4:?usage: phase-chain.sh add <PWS> <PHASE> <CWD> [NEXT_PHASE]}"
    NEXT="${5:-}"
    [ -f "$PWS/PHASE_CHAIN" ] || { echo "phase-chain: $PWS is not initialised - run init first" >&2; exit 1; }
    [ -d "$DIR" ] || { echo "phase-chain: $PHASE cwd $DIR does not exist" >&2; exit 1; }
    printf '%s\n' "$DIR" > "$PWS/state/$PHASE.cwd"
    if [ -n "$NEXT" ]; then printf '%s\n' "$NEXT" > "$PWS/state/$PHASE.next"; else rm -f "$PWS/state/$PHASE.next"; fi
    echo "phase-chain: $PHASE runs in $DIR${NEXT:+, then $NEXT}"
    ;;
  start)
    PHASE="${3:?usage: phase-chain.sh start <PWS> <PHASE>}"
    bash "$PWS/launch.sh" "$PWS" "$PHASE" || exit $?
    start_runner
    ;;
  runner)
    start_runner
    ;;
  *)
    echo "phase-chain: unknown command '$CMD' (init | add | start | runner)" >&2
    exit 1
    ;;
esac
