#!/usr/bin/env bash
# night-sprint reviver - bring a dead or stuck session back, cheapest rung first.
#
#   revive.sh <WORKSPACE> <TAG> [CAUSE]
#
# CAUSE is the watcher's second field: api-error | ended-without-signal | idle | permission-prompt
# (default: ended-without-signal). It changes only the resume budget and the wording of the
# continue prompt.
#
# Most night-time deaths are not the session's fault - the API drops the call mid-response,
# stalls mid-stream, or returns 529/500. The process is gone but the whole conversation is
# still on disk: what it read, what it decided, the edit it was halfway through. Resuming that
# conversation costs one prompt. Restarting the ticket from the top throws all of it away.
#
# The ladder, cheapest rung first:
#   resume   `claude --bg --resume` on the same conversation, told to carry on, not start over.
#            Budget: 2 for api-error (transient infrastructure, worth a second go), 1 otherwise.
#   restart  a brand new session on the original ticket prompt, plus a RESUME block telling it
#            which commits already landed so it does not redo them. Budget: 1.
#   abandon  writes `BLOCKED: ABANDONED ...` so the watcher reports it and the sprint moves on.
#
# Prints one line naming the rung it took, so the conductor can log it without parsing anything.
#
# TWO THINGS THAT MAKE HAND-REVIVING WRONG, both handled here:
#   1. A resumed session gets a NEW session id and does NOT inherit its display name. The
#      watcher tracks the id in state/<TAG>.session, so a stale id there is a live session
#      nobody is watching - the sprint goes quiet until morning.
#   2. The watcher emits each (tag, verdict) at most once. Without clearing the tag's rows from
#      its seen-file, a revived session that dies again is never reported.

set -uo pipefail

WS="${1:?usage: revive.sh <WORKSPACE> <TAG> [CAUSE]}"
TAG="${2:?usage: revive.sh <WORKSPACE> <TAG> [CAUSE]}"
CAUSE="${3:-ended-without-signal}"

STATE="$WS/state"
SEEN="$STATE/.watch-seen"
SESSION_FILE="$STATE/$TAG.session"
LEDGER="$STATE/$TAG.revivals"
PROMPT="$WS/prompt-$TAG.txt"

# A session that wrote its own status reached a terminal state it chose. DONE needs nothing;
# BLOCKED hit something real and relaunching just burns tokens into the same wall.
if [ -f "$STATE/$TAG.status" ]; then
  echo "revive: $TAG already reported '$(head -1 "$STATE/$TAG.status")' - nothing to revive"
  exit 0
fi

WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"
MODE="$(tr -d '[:space:]' < "$WS/PERMISSION_MODE" 2>/dev/null || echo auto)"
SLUG="$(tr -d '[:space:]' < "$WS/SLUG" 2>/dev/null || echo sprint)"
OLD_SID="$(tr -d '[:space:]' < "$SESSION_FILE" 2>/dev/null || echo)"

resumes=0
restarts=0
if [ -f "$LEDGER" ]; then
  # `grep -c` prints 0 and exits 1 when nothing matches - `|| true` swallows the status
  # without printing a second count on top of it.
  resumes="$(grep -c '^resume ' "$LEDGER" 2>/dev/null || true)"
  restarts="$(grep -c '^restart ' "$LEDGER" 2>/dev/null || true)"
  resumes="${resumes:-0}"
  restarts="${restarts:-0}"
fi
attempt=$(( resumes + restarts + 1 ))

RESUME_BUDGET=1
[ "$CAUSE" = "api-error" ] && RESUME_BUDGET=2

# The watcher must be able to report this tag's next failure too.
clear_seen() {
  [ -f "$SEEN" ] || return 0
  # grep -v exits 1 when it filters the file down to nothing, which is a perfectly good
  # result here - do not let it skip the mv.
  grep -v "^$TAG:" "$SEEN" > "$SEEN.tmp" 2>/dev/null || true
  [ -f "$SEEN.tmp" ] && mv "$SEEN.tmp" "$SEEN"
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
  claude agents --json --all 2>/dev/null | python3 -c 'import json,sys
sid=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
for r in rows:
    if r.get("sessionId")==sid or r.get("id")==sid[:8]:
        if r.get("pid") and r.get("state")!="done": print(r["pid"])
        break' "$1"
}

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

# Is this session ACTUALLY working this second?
#
# Two signals, and both are needed. `status` is the harness's own word for it: `busy` means a model
# call is running right now. Do not use `state` for this - `state:working` also covers a session
# that finished its turn and is waiting, which is exactly the kind this script exists to revive.
#
# And do not use the transcript alone either. A busy session can write nothing for minutes while a
# long turn streams or a long command runs, so "the file has not grown" does NOT mean "not
# working". The transcript's only job here is to catch the opposite case: a session still reporting
# `busy` that has been silent longer than the watcher's stall window is not working, it is hung
# mid-call, and that is precisely what the conductor was called here to fix.
ACTIVE_STALL_MIN=25   # matches watch.sh's default STALL_MINUTES
session_is_active() {
  local sid="$1" status f last now
  case "$sid" in ""|unresolved) return 1 ;; esac

  status="$(claude agents --json --all 2>/dev/null | python3 -c 'import json,sys
sid=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
for r in rows:
    if r.get("sessionId")==sid or r.get("id")==sid[:8]:
        print(r.get("status") or ""); break' "$sid")"
  [ "$status" = "busy" ] || return 1

  f="$(ls -t "$HOME"/.claude/projects/*/"$sid".jsonl 2>/dev/null | head -1)"
  [ -n "$f" ] || return 0            # busy with no transcript to check - assume working, hands off
  last="$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null)"
  [ -n "$last" ] || return 0
  now="$(date +%s)"
  [ $(( (now - last) / 60 )) -lt "$ACTIVE_STALL_MIN" ]
}

# NEVER REVIVE A SESSION THAT IS STILL WORKING.
#
# The sprint has one rule about live sessions: it does not interrupt them. A working session owns
# its ticket AND its own window - it measures itself and hands its tag to a fresh session by
# itself, from its own prompt. Reviving it would stop a session mid-edit and resume a COPY of its
# conversation, which is exactly how two agents end up in one worktree.
#
# The watcher can misread a long build, a big install or a quiet stretch as a stall. A transcript
# that is still growing cannot be misread. So the process, not the verdict, has the last word here.
#
# Everything else IS revivable. A dead session has nothing to interrupt. A session blocked on a
# permission prompt nobody can answer is not working either - it will sit there until morning, and
# it is not mid-edit, so stopping it costs only the prompt it was stuck on.
if session_is_active "$OLD_SID"; then
  echo "revive: $TAG is still WORKING ($OLD_SID, transcript grew < ${ACTIVE_WITHIN_MIN}m ago) - NOT interrupting it." >&2
  echo "        A live session manages its own window and hands its own ticket on. There is nothing" >&2
  echo "        to do from out here. If it is genuinely stuck it will stop growing; revive it then." >&2
  echo "declined-still-working $CAUSE $OLD_SID -" >> "$LEDGER"
  exit 1
fi

# Stop whatever is left of the old session before starting anything. Harmless if it is already
# gone, and the conversation survives - `claude stop` keeps it resumable.
if ! stop_session "$OLD_SID"; then
  # Never put a second agent into a worktree that still has one. BOTH rungs below would do
  # exactly that - resume forks the conversation, restart launches a fresh session - and the old
  # process would go on committing to the same branch with nobody watching it. A tag that stalls
  # where a human can see it beats two agents fighting over one worktree until morning.
  echo "revive: $TAG - $OLD_SID will not stop; refusing to start a second session in $WT" >&2
  echo "stop-failed $CAUSE $OLD_SID -" >> "$LEDGER"
  exit 1
fi

# Resolve a background session id by display name, newest first. Same contract launch.sh uses:
# the launch output format is not stable, `claude agents --json` reporting `name` is.
resolve_sid() {
  local want="$1" sid=""
  for _ in $(seq 1 15); do
    sid="$(claude agents --json --all --cwd "$WT" 2>/dev/null \
      | python3 -c 'import json,sys
want=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
best=None
for r in rows:
    if r.get("name")==want and (best is None or r.get("startedAt",0)>best.get("startedAt",0)):
        best=r
if best: print(best.get("sessionId",""))' "$want")"
    [ -n "$sid" ] && { printf '%s' "$sid"; return 0; }
    sleep 2
  done
  return 1
}

# ---------------------------------------------------------------- rung 1: resume
if [ -n "$OLD_SID" ] && [ "$OLD_SID" != "unresolved" ] && [ "$resumes" -lt "$RESUME_BUDGET" ]; then
  NAME="ns-$SLUG-$TAG-r$attempt"

  case "$CAUSE" in
    api-error) WHY="an API error - the connection dropped or the model call failed. That is infrastructure, not something you did wrong." ;;
    permission-prompt) WHY="a permission prompt. Nobody is awake to answer it, so do not wait for approval: decide it yourself, and if an action stays refused, route around it and say so in your summary." ;;
    idle) WHY="a stall - you went quiet for a long time and the sprint could not tell whether you were still working." ;;
    *) WHY="something that ended your process before you wrote your status file." ;;
  esac

  CONTINUE_PROMPT="CONTINUE - you were interrupted, you did not finish, and nobody has taken over.

What stopped you: $WHY

Everything you had is still in this conversation. DO NOT START OVER and do not re-plan the
ticket. Re-establish ground truth first:
  cd $WT && git status --short && git log --oneline -10
Then carry on from exactly where you stopped.

You still owe the full handoff, in this order: verify green, commit with your SIGNAL line and
push, write $WS/state/$TAG.summary (one line), write $WS/state/$TAG.status LAST, then launch the
next tag if and only if you wrote DONE. Your original contract is $PROMPT - re-read it if you
are unsure what you owe.

Still an autonomous night run. Nobody is awake to answer a question - decide, note the decision
in your summary, and keep going."

  echo "revive: $TAG rung=resume attempt=$attempt cause=$CAUSE from=$OLD_SID"
  ( cd "$WT" && claude --bg --resume "$OLD_SID" -n "$NAME" --permission-mode "$MODE" "$CONTINUE_PROMPT" ) \
    > "$STATE/$TAG.revive-$attempt.log" 2>&1
  rc=$?

  if [ $rc -eq 0 ] && new_sid="$(resolve_sid "$NAME")"; then
    printf '%s\n' "$new_sid" > "$SESSION_FILE"
    echo "resume $CAUSE $OLD_SID $new_sid" >> "$LEDGER"
    clear_seen
    echo "revive: $TAG resumed as $new_sid ($NAME) - conversation kept, watcher repointed"
    exit 0
  fi

  # Resume failed. Record the spent attempt so the next call falls through to restart rather
  # than trying the same broken rung again.
  echo "resume $CAUSE $OLD_SID FAILED(rc=$rc)" >> "$LEDGER"
  echo "revive: $TAG resume FAILED (rc=$rc, see $STATE/$TAG.revive-$attempt.log) - falling through to restart" >&2
  resumes=$(( resumes + 1 ))
  attempt=$(( attempt + 1 ))
fi

# ---------------------------------------------------------------- rung 2: restart
if [ "$restarts" -lt 1 ]; then
  if [ ! -f "$PROMPT" ]; then
    echo "revive: $TAG cannot restart - no prompt file at $PROMPT" >&2
  else
    # Tell the fresh session what the dead one already landed, so it picks up rather than redoes.
    if ! grep -q '^## RESUME - the earlier session died' "$PROMPT" 2>/dev/null; then
      cat >> "$PROMPT" <<EOF

## RESUME - the earlier session died

An earlier session on this ticket ended before writing its status ($CAUSE). It may already have
landed part of the work. Before you write a line of code:
  cd $WT && git log --oneline -10 && git status --short
Anything already committed for this ticket is DONE - keep it, do not redo it, do not revert it.
Pick up from the first acceptance criterion that is not yet satisfied.
EOF
    fi

    rm -rf "$STATE/claim-$TAG" "$SESSION_FILE"
    clear_seen
    echo "restart $CAUSE $OLD_SID -" >> "$LEDGER"
    echo "revive: $TAG rung=restart attempt=$attempt cause=$CAUSE - fresh session on the ticket prompt"
    exec bash "$WS/launch.sh" "$WS" "$TAG"
  fi
fi

# ---------------------------------------------------------------- rung 3: abandon
echo "abandon $CAUSE $OLD_SID -" >> "$LEDGER"
# Count the rungs actually spent, not this call - the abandon itself is not a revive attempt.
spent=$(( resumes + restarts ))
[ -f "$STATE/$TAG.summary" ] || \
  echo "ABANDONED - died again after $spent revive attempts ($CAUSE), never reported a status" > "$STATE/$TAG.summary"
echo "BLOCKED: ABANDONED after $spent revive attempts ($CAUSE)" > "$STATE/$TAG.status"
echo "revive: $TAG rung=abandon - out of attempts. Skip its dependents and report the gap."
