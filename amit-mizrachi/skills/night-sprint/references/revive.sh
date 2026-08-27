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

# Stop whatever is left of the old session before starting anything. Harmless if it is already
# gone, and the conversation survives - `claude stop` keeps it resumable.
[ -n "$OLD_SID" ] && claude stop "$OLD_SID" >/dev/null 2>&1

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
