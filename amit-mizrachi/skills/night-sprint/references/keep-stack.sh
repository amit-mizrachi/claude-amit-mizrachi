#!/usr/bin/env bash
# night-sprint kept stack - start a long-running dev stack that outlives the session that booted it.
#
#   keep-stack.sh <WORKSPACE> start <NAME> <DIR> -- <command...>
#   keep-stack.sh <WORKSPACE> stop  <NAME>
#   keep-stack.sh <WORKSPACE> list
#
# WHY THIS EXISTS. A stack booted from a ticket session's Bash tool died twice over, every night:
#   1. It was a child of that session. The runner closes every finished session (close.sh:
#      `claude stop`, then SIGTERM and SIGKILL), revive.sh stops a stalled one, and the stack went
#      with it - a successor that was told "the stack is UP" found ERR_CONNECTION_REFUSED.
#   2. Reclaim (the launchd reaper) reads CLAUDE_CODE_SESSION_ID out of each process's environment.
#      Once that session ended, an idle stack with no browser attached was an "orphan", and under
#      memory pressure - which a sprint machine is at most of the night - reclaim stopped it.
# So the stack is started here, detached from both:
#   - its own process session and group (setsid), reparented to launchd at once, so no session's
#     process tree holds it and stopping a session cannot reach it;
#   - without CLAUDE_CODE_SESSION_ID / CLAUDE_PID, so no session owns it;
#   - with RECLAIM_KEEP=1, which reclaim honours: it never stops the group automatically.
# It stays up after the sprint ends, until the user stops it: `keep-stack.sh <WS> stop <NAME>`, the
# Reclaim page's Stop button, or the stack's own stop target. No session ever stops a kept stack.
#
# SIGINT. A background child of a non-interactive shell starts with SIGINT ignored, and an ignored
# signal survives exec - so a stack started with plain `cmd &` cannot be stopped with SIGINT, the
# signal Shapes' dev.sh cleans up on. The launcher restores SIGINT and SIGQUIT to their defaults
# before it execs the command.
#
# Writes:
#   <WS>/stacks/<NAME>.log  - the stack's output (appended across restarts)
#   <WS>/stacks/<NAME>.pid  - the process group id (the leader's pid, since it leads a new session)
#   <WS>/state/STACKS.md    - one line per start and stop, for the morning report
#   <WS>/state/EVENTS.log   - one line per start and stop

set -uo pipefail

WS="${1:?usage: keep-stack.sh <WORKSPACE> start|stop|list ...}"
VERB="${2:?usage: keep-stack.sh <WORKSPACE> start|stop|list ...}"
DIR_STACKS="$WS/stacks"
STATE="$WS/state"
mkdir -p "$DIR_STACKS" "$STATE"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
note() { printf '%s keep-stack %s\n' "$(now)" "$*" >> "$STATE/EVENTS.log"; }
alive() { kill -0 -- "-$1" 2>/dev/null; }

valid_name() {
  case "$1" in
    ""|*[!A-Za-z0-9._-]*) echo "keep-stack: name must be letters, digits, '.', '_' or '-'" >&2; return 1 ;;
  esac
}

case "$VERB" in
  start)
    NAME="${3:-}"; DIR="${4:-}"
    valid_name "$NAME" || exit 2
    [ "${5:-}" = "--" ] && [ $# -ge 6 ] || { echo "usage: keep-stack.sh <WS> start <NAME> <DIR> -- <command...>" >&2; exit 2; }
    shift 5
    [ -d "$DIR" ] || { echo "keep-stack: no such directory: $DIR" >&2; exit 2; }
    PIDF="$DIR_STACKS/$NAME.pid"
    if [ -s "$PIDF" ] && alive "$(cat "$PIDF")"; then
      echo "keep-stack: $NAME is already up (group $(cat "$PIDF")) - stop it first or use another name"
      exit 0
    fi
    LOG="$DIR_STACKS/$NAME.log"
    : > "$PIDF"
    printf '\n=== %s keep-stack start: %s ===\n' "$(now)" "$*" >> "$LOG"
    # The outer subshell exits at once, so the launcher is reparented to launchd. perl writes its own
    # pid (which setsid makes the group id too), resets SIGINT/SIGQUIT, and execs the command.
    ( cd "$DIR" && exec env -u CLAUDE_CODE_SESSION_ID -u CLAUDE_PID RECLAIM_KEEP=1 \
        perl -MPOSIX -e '
          POSIX::setsid() or die "setsid: $!\n";
          $SIG{INT} = "DEFAULT"; $SIG{QUIT} = "DEFAULT";
          open(my $f, ">", shift @ARGV) or die "pid file: $!\n"; print $f "$$\n"; close $f;
          exec { $ARGV[0] } @ARGV or die "exec $ARGV[0]: $!\n";
        ' "$PIDF" "$@" </dev/null >>"$LOG" 2>&1 & )
    for _ in $(seq 1 50); do [ -s "$PIDF" ] && break; sleep 0.1; done
    PGID="$(cat "$PIDF" 2>/dev/null)"
    if [ -z "$PGID" ] || ! alive "$PGID"; then
      echo "keep-stack: $NAME did not start - see $LOG" >&2
      tail -5 "$LOG" >&2
      note "$NAME start FAILED in $DIR"
      exit 1
    fi
    STOP="bash $WS/keep-stack.sh $WS stop $NAME"
    printf -- '- %s UP %s group=%s dir=%s log=%s stop: `%s` cmd: `%s`\n' \
      "$(now)" "$NAME" "$PGID" "$DIR" "$LOG" "$STOP" "$*" >> "$STATE/STACKS.md"
    note "$NAME up group=$PGID dir=$DIR"
    echo "keep-stack: $NAME up, group $PGID, log $LOG"
    echo "keep-stack: it stays up after this session and after the sprint; stop it with: $STOP"
    ;;

  stop)
    NAME="${3:-}"
    valid_name "$NAME" || exit 2
    PIDF="$DIR_STACKS/$NAME.pid"
    PGID="$(cat "$PIDF" 2>/dev/null)"
    if [ -z "$PGID" ] || ! alive "$PGID"; then
      echo "keep-stack: $NAME is not running"
      exit 0
    fi
    # INT first: what Ctrl-C sends, and what dev.sh cleans up on (ports, locks, the registry row).
    for sig in INT TERM KILL; do
      kill "-$sig" -- "-$PGID" 2>/dev/null
      for _ in $(seq 1 30); do alive "$PGID" || break; sleep 1; done
      alive "$PGID" || break
    done
    if alive "$PGID"; then echo "keep-stack: $NAME (group $PGID) will not stop" >&2; exit 1; fi
    : > "$PIDF"
    printf -- '- %s DOWN %s group=%s\n' "$(now)" "$NAME" "$PGID" >> "$STATE/STACKS.md"
    note "$NAME down group=$PGID"
    echo "keep-stack: $NAME stopped"
    ;;

  list)
    found=0
    for f in "$DIR_STACKS"/*.pid; do
      [ -e "$f" ] || continue
      n="$(basename "$f" .pid)"; g="$(cat "$f" 2>/dev/null)"
      [ -n "$g" ] && alive "$g" || continue
      found=1
      echo "$n UP group=$g log=$DIR_STACKS/$n.log stop: bash $WS/keep-stack.sh $WS stop $n"
    done
    [ "$found" -eq 1 ] || echo "keep-stack: no kept stack is up"
    ;;

  *) echo "usage: keep-stack.sh <WORKSPACE> start|stop|list ..." >&2; exit 2 ;;
esac
