#!/usr/bin/env bash
# night-sprint reviver - bring a dead or stuck session back, cheapest rung first.
#
#   revive.sh <WORKSPACE> <TAG> [CAUSE]
#
# CAUSE is the watcher's second field: api-error | ended-without-signal | idle |
# permission-prompt | unarmed (default: ended-without-signal), plus two the CALLER uses to say
# "I have already dealt with the reason this stopped, try again now": budget-retry and auth-retry.
# `unarmed` is phase chains only: a conductor that closed its turn with nothing left to wake it.
#
# Most night-time deaths are not the session's fault - the API drops the call mid-response,
# stalls mid-stream, or returns 529/500. The process is gone but the whole conversation is
# still on disk: what it read, what it decided, the edit it was halfway through. Resuming that
# conversation costs one prompt. Restarting the ticket from the top throws all of it away.
#
# But not every death wants a retry, and that distinction is the first thing this script
# settles - see WHAT ACTUALLY ENDED IT below. `classify-error.sh` reads the transcript, and a
# quota or auth failure never reaches the ladder at all: retrying those cannot succeed, and a
# ladder spent against a spending cap is how a night loses three and a half hours.
#
# The ladder, cheapest rung first, for the failures a retry CAN fix:
#   resume   `claude --bg --resume` on the same conversation, told to carry on, not start over.
#            Budget: 2 for api-error (transient infrastructure, worth a second go), 1 otherwise.
#   restart  a brand new session on the original ticket prompt, plus a RESUME block telling it
#            which commits already landed so it does not redo them. Budget: 1.
#   abandon  writes `BLOCKED: ABANDONED ...` so the watcher reports it and the sprint moves on.
#
# Prints one line naming the rung it took, so the conductor can log it without parsing anything.
#
# Exit codes, because the watcher acts on them:
#   0  a rung was taken (resume or restart), or there was nothing to revive
#   1  refused - the session is still working, or the old one would not stop
#   5  BUDGET-BLOCKED: out of capacity. state/PAUSED now holds the retry time; nothing new
#      may launch until it clears, and the watcher comes back with CAUSE=budget-retry
#   6  held on auth. A human must re-authenticate, then call this again with CAUSE=auth-retry.
#      No terminal status is written: the work is fine, only the login is not
#   7  out of budget for good - waited the full ladder of waits and capacity never returned
#   8  FORKED - the resume found the old session still running, and its copy would not stop. A DUP.
#
# TWO THINGS THAT MAKE HAND-REVIVING WRONG, both handled here:
#   1. A resumed session gets a NEW session id and does NOT inherit its display name. The
#      watcher tracks the id in state/<TAG>.session, so a stale id there is a live session
#      nobody is watching - the sprint goes quiet until morning.
#   2. The watcher emits each (tag, verdict) at most once. Without clearing the tag's rows from
#      its seen-file, a revived session that dies again is never reported.
#
# IN A PHASE CHAIN (the workspace holds a PHASE_CHAIN file, see phase-chain.sh) every tag is a
# CONDUCTOR, not a ticket, and four things change. A conductor that ended its own turn with no
# error is not dead - it waits on a person, a Monitor or its own relay - so it is left alone,
# whatever the harness calls it (blocked, busy or idle) and whatever CAUSE the caller passed,
# except `unarmed`. The resume and restart messages send it back to its LOG.md, not to a commit
# and a push. The ladder budget counts only the last RUNG_WINDOW_MIN, because a conductor lives
# all night and two deaths hours apart are two incidents, not one. And the abandon rung does not
# stop a conductor that is still running: it only writes the status.

set -uo pipefail

WS="${1:?usage: revive.sh <WORKSPACE> <TAG> [CAUSE]}"
TAG="${2:?usage: revive.sh <WORKSPACE> <TAG> [CAUSE]}"
CAUSE="${3:-ended-without-signal}"

# shellcheck source=agents.sh
. "$WS/agents.sh"

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

# A tag may run somewhere other than the sprint worktree (a phase conductor runs in its own repo).
# A resume MUST run there too: the harness files a transcript under its cwd, and
# `claude --resume <id>` from any other directory does not find the conversation.
WT="$( { tr -d '[:space:]' < "$STATE/$TAG.cwd"; } 2>/dev/null || true)"
[ -n "$WT" ] || WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"
PHASE=0
[ -f "$WS/PHASE_CHAIN" ] && PHASE=1
MODE="$(tr -d '[:space:]' < "$WS/PERMISSION_MODE" 2>/dev/null || echo auto)"
SLUG="$(tr -d '[:space:]' < "$WS/SLUG" 2>/dev/null || echo sprint)"
OLD_SID="$(tr -d '[:space:]' < "$SESSION_FILE" 2>/dev/null || echo)"

# A CONDUCTOR'S BUDGET IS PER INCIDENT, NOT PER NIGHT - phase chains only.
#
# A ticket session lives for minutes, so one resume and one restart per tag is a fair bound on a
# ticket that keeps dying. A phase conductor lives for hours and relays to new session ids along
# the way, and every rung it ever used counted against the same budget. On 2026-10-02 the BUILD
# conductor was revived at 14:01 and restarted at 14:27, and the third revive at 14:53 abandoned
# the whole build. All three were false alarms. But the same arithmetic abandons a build after two
# real dropped connections hours apart, which a resume fixes every time.
#
# So in a phase chain only the rungs of the last RUNG_WINDOW_MIN count. A conductor that dies three
# times inside an hour is broken, and the ladder still ends it. A revive that bought an hour of work
# succeeded, and the next death starts a new ladder. Every rung row carries `at=<epoch>` for this.
# Rows written before that field existed have no time, so they always count.
RUNG_WINDOW_MIN=60
since=0
[ "$PHASE" -eq 1 ] && since=$(( $(date +%s) - RUNG_WINDOW_MIN * 60 ))
count_rungs() {
  [ -f "$LEDGER" ] || { echo 0; return 0; }
  awk -v k="$1" -v since="$since" '
    $1 == k {
      at = 0
      for (i = 5; i <= NF; i++) if ($i ~ /^at=/) at = substr($i, 4) + 0
      if (at == 0 || at >= since) n++
    }
    END { print n + 0 }' "$LEDGER" 2>/dev/null || echo 0
}
resumes="$(count_rungs resume)"
restarts="$(count_rungs restart)"
events=0
[ -f "$LEDGER" ] && events="$(wc -l < "$LEDGER" 2>/dev/null || true)"
events="${events:-0}"
NOW_AT="at=$(date +%s)"

# THE LAUNCH GENERATION IS NOT THE LADDER BUDGET, and conflating them broke session tracking.
#
# `attempt` only exists to make the display name unique, and it used to be
# `resumes + restarts + 1`. Budget retries deliberately do not increment those counters - being
# out of capacity is not a failed attempt at the conversation - so every quota resume in a night
# was named `ns-<slug>-<tag>-r1`. `resolve_sid` matches on that name, so the second retry
# happily resolved the FIRST retry's finished session and recorded its id as the new one. The
# real process ran untracked for the rest of the night.
#
# So the generation counts EVERY line in the ledger, which only ever grows, while the ladder
# budgets keep counting their own kinds. `tr -d` because `wc -l` pads on macOS.
events="$(printf '%s' "$events" | tr -d '[:space:]')"
attempt=$(( events + 1 ))

RESUME_BUDGET=1
[ "$CAUSE" = "api-error" ] && RESUME_BUDGET=2

# A resume after a quota wait is not an attempt at a broken conversation - the conversation
# was never broken, the account was out of capacity. So it gets its own ledger key and does
# not eat the ladder: the number of WAITS is what bounds this failure, and that cap lives in
# the quota branch below.
RESUME_KEY="resume"
case "$CAUSE" in
  budget-retry) RESUME_KEY="resume-budget"; RESUME_BUDGET=99 ;;
  auth-retry)   RESUME_KEY="resume-auth";   RESUME_BUDGET=99 ;;
esac

# The watcher must be able to report this tag's next failure too.
clear_seen() {
  [ -f "$SEEN" ] || return 0
  # grep -v exits 1 when it filters the file down to nothing, which is a perfectly good
  # result here - do not let it skip the mv.
  grep -v "^$TAG:" "$SEEN" > "$SEEN.tmp" 2>/dev/null || true
  [ -f "$SEEN.tmp" ] && mv "$SEEN.tmp" "$SEEN"
}

# Stopping a session for real - `stop_session` - lives in agents.sh, shared with close.sh.

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
# Prints "<status> <live|gone>" for the session, or returns 1 when the list cannot be read.
harness_status() {
  local rows
  rows="$(agents_json "$WT")" || return 1
  printf '%s' "$rows" | python3 -c 'import json,sys
sid=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
for r in rows:
    if r.get("sessionId")==sid or r.get("id")==sid[:8]:
        live="live" if r.get("pid") and r.get("state")!="done" else "gone"
        print((r.get("status") or "-")+" "+live); break' "$1"
}
GROWING_MIN=2         # a transcript written this recently belongs to a live process
session_is_active() {
  local sid="$1" f last now hs
  case "$sid" in ""|unresolved) return 1 ;; esac

  f="$(ls -t "$HOME"/.claude/projects/*/"$sid".jsonl 2>/dev/null | head -1)"
  last=""
  [ -n "$f" ] && last="$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null)"
  now="$(date +%s)"

  # NO ANSWER FROM THE HARNESS IS NO LICENCE TO ACT. This guard used to read a failed `claude
  # agents` as status "", which is "not busy", so it passed without ever looking at the transcript.
  # On 2026-10-04 c5081c1b wrote a record every few seconds right through the revive that forked
  # it. Hands off; the next sweep asks again.
  hs="$(harness_status "$sid")" || return 0

  # A LIVE PROCESS WITH A GROWING TRANSCRIPT IS WORKING, whatever `status` says - it reads `idle`
  # between model calls. Only a live pid counts: a session that just died also has a fresh file.
  if [ "${hs#* }" = "live" ] && [ -n "$last" ] && [ $(( (now - last) / 60 )) -lt "$GROWING_MIN" ]; then
    return 0
  fi
  [ "${hs%% *}" = "busy" ] || return 1

  [ -n "$last" ] || return 0         # busy with no transcript to check - assume working, hands off
  [ $(( (now - last) / 60 )) -lt "$ACTIVE_STALL_MIN" ]
}

# A CONDUCTOR THAT ENDED ITS OWN TURN IS WAITING, NOT DEAD - phase chains only.
#
# The harness labels cannot tell a conductor that ended its turn on purpose from the corpse this
# script exists to revive. A review-mode conductor waiting for the user's picks shows as
# `state:blocked` - the label of a permission prompt. One waiting on its Monitor shows as
# `status:busy` - the label of a hung call. One that died on an API error shows as `working/idle`.
# Only the transcript tells them apart: a wait CLOSED its turn (turn_ended in agents.sh) with no
# error; a death ends on an error; a permission prompt, a hung call and a kill stop mid-turn.
# Reviving a waiting conductor stops it - and its Monitor with it - and starts a copy that knows
# nothing of the conversation the user is having with it. On 2026-10-02 that is what happened at
# the review gate: the runner read the waiting conductor as a permission prompt, this guard let
# `permission-prompt` straight through, and the conductor the user was answering was stopped.
# So decide before the stop below, not after it. Only the two retry causes skip the check: the
# caller has already dealt with what ended the session and is asking for it back.
#
# `unarmed` is the one closed turn that IS revived: no Monitor and no background command is left
# to wake it (see conductor_waiting in watch.sh). Check that again here, because a conductor can
# re-arm between the watcher's look and this one. One that has a tool running again is waiting.
if [ "$PHASE" -eq 1 ] && [ -n "$OLD_SID" ] && [ "$OLD_SID" != "unresolved" ]; then
  case "$CAUSE" in
    budget-retry|auth-retry) : ;;
    unarmed)
      if [ -n "$(session_pid "$OLD_SID")" ] && ! nothing_armed "$OLD_SID"; then
        echo "revive: $TAG ($OLD_SID) has a Monitor or background command running again - waiting, not reviving it"
        exit 0
      fi
      ;;
    *)
      if [ "$(bash "$WS/classify-error.sh" "$OLD_SID" 2>/dev/null || echo none)" = "none" ] \
         && turn_ended "$OLD_SID"; then
        echo "revive: $TAG ($OLD_SID) ended its own turn with no error - a conductor that is waiting, not dead; not reviving it"
        exit 0
      fi
      ;;
  esac
fi

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
  echo "revive: $TAG is still WORKING ($OLD_SID: transcript still growing, harness busy, or harness unreadable) - NOT interrupting it." >&2
  echo "        A live session manages its own window and hands its own ticket on. There is nothing" >&2
  echo "        to do from out here. If it is genuinely stuck it will stop growing; revive it then." >&2
  # No ledger row: nothing was spent. The watcher logs this refusal in EVENTS.log. As ledger rows,
  # these refusals made the rung numbers unreadable: 13 of them turned the second real rung of
  # 2026-10-02 into "revive attempt 15".
  exit 1
fi

# Is any rung left? The abandon rung below must know BEFORE the stop, not after it.
rung_left=0
if [ -n "$OLD_SID" ] && [ "$OLD_SID" != "unresolved" ] && [ "$resumes" -lt "$RESUME_BUDGET" ]; then
  rung_left=1
fi
if [ "$restarts" -lt 1 ] && [ -f "$PROMPT" ]; then
  rung_left=1
fi

# Stop whatever is left of the old session before starting anything. Harmless if it is already
# gone, and the conversation survives - `claude stop` keeps it resumable.
#
# EXCEPT a phase conductor that is out of rungs. Nothing is launched after that stop, so stopping
# it gains nothing. And it can be a conductor that was working. On 2026-10-02 the abandon rung
# stopped a healthy BUILD conductor, and the sprint runner under its Monitor died with it. A
# conductor that is really stuck costs a stuck process until a person looks. A healthy one that is
# stopped costs the build.
LEFT_RUNNING=0
if [ "$PHASE" -eq 1 ] && [ "$rung_left" -eq 0 ] && [ -n "$(session_pid "$OLD_SID")" ]; then
  LEFT_RUNNING=1
  echo "revive: $TAG - out of rungs; leaving $OLD_SID running, not stopping a conductor nothing replaces" >&2
elif ! stop_session "$OLD_SID"; then
  # Never put a second agent into a worktree that still has one. BOTH rungs below would do
  # exactly that - resume forks the conversation, restart launches a fresh session - and the old
  # process would go on committing to the same branch with nobody watching it. A tag that stalls
  # where a human can see it beats two agents fighting over one worktree until morning.
  echo "revive: $TAG - $OLD_SID will not stop; refusing to start a second session in $WT" >&2
  echo "stop-failed $CAUSE $OLD_SID -" >> "$LEDGER"
  exit 1
fi

# ------------------------------------------------- WHAT ACTUALLY ENDED IT, before any rung
#
# The CAUSE the caller passed is the watcher's read of the symptom. The transcript is the
# evidence, and for two whole classes of failure the difference decides whether ANY rung is
# worth spending. A dropped socket wants a resume. A spending cap and a logged-out CLI want
# the exact opposite: resuming is guaranteed to fail, and every attempt is one more refused
# request. A night was lost to this - two reviews stopped on organisation spend-limit errors
# and the recovery treated them as ordinary stalls, so the ladder burned out against a wall
# and the incident log recorded the outage as a permission problem.
#
# So classify first, and let the class pick the response.
CLASS="none"
if [ -n "$OLD_SID" ] && [ "$OLD_SID" != "unresolved" ] && [ -x "$WS/classify-error.sh" ]; then
  CLASS="$(bash "$WS/classify-error.sh" "$OLD_SID" 2>/dev/null || echo none)"
fi
KIND="${CLASS%% *}"
DETAIL=""
case "$CLASS" in *" "*) DETAIL="${CLASS#* }" ;; esac

# A human must act, and no amount of retrying substitutes for it. Report it as the blocker
# it is - NOT as an abandoned ticket, because nothing about the ticket is wrong.
# NOTE THE ABSENCE OF A TERMINAL STATUS HERE, and it is deliberate.
#
# This used to write `BLOCKED: auth ...` to state/<TAG>.status while telling the user to log in
# and then revive the tag. Those two instructions contradict each other: the status guard at the
# top of this script exits 0 the moment a status file exists, so the documented recovery was a
# no-op and the tag could never come back. A tag held up by a logged-out CLI is not a blocked
# ticket - nothing about the work is wrong - so it stays OPEN, parked behind state/PAUSED, and
# the marker file below is what the recovery clears.
#
# Recovery, and it is the one path that works:
#     claude /login                      (a human, in a real terminal)
#     bash <WS>/revive.sh <WS> <TAG> auth-retry
# `auth-retry` skips this classification - the transcript still ENDS on the auth error, so
# classifying again would park it again forever - and clears both markers itself.
if [ "$CAUSE" != "auth-retry" ] && [ "$KIND" = "auth" ]; then
  echo "revive: $TAG stopped on an AUTH failure ($DETAIL) - a human must fix this, not a retry" >&2
  echo "        After 'claude /login', run: bash $WS/revive.sh $WS $TAG auth-retry" >&2
  echo "auth-blocked $CAUSE $OLD_SID $DETAIL" >> "$LEDGER"
  echo "waiting on re-authentication ($DETAIL) - not started, not blocked on the work" \
    > "$STATE/$TAG.summary"
  printf '%s\n' "$DETAIL" > "$STATE/$TAG.auth-blocked"
  clear_seen
  printf 'auth %s tag=%s\n' "$DETAIL" "$TAG" > "$STATE/PAUSED"
  exit 6
fi

# The human has logged in and is asking for the tag back. Clear the hold, then fall through to
# the ordinary ladder as if this were any other recoverable death.
if [ "$CAUSE" = "auth-retry" ]; then
  rm -f "$STATE/$TAG.auth-blocked"
  case "$(head -1 "$STATE/PAUSED" 2>/dev/null)" in
    auth*) rm -f "$STATE/PAUSED"; echo "revive: cleared the auth hold on the sprint" ;;
  esac
  echo "auth-cleared auth-retry $OLD_SID -" >> "$LEDGER"
fi

# Out of capacity, not out of road. The work in that conversation is fine and the ticket is
# fine; there is simply no budget to run it this minute. So: park the tag, stop the sprint
# from launching anything else into a cap that is already refusing requests, and record WHEN
# it is worth trying again. The watcher un-pauses. Nothing here sleeps - a reviver that
# blocked for two hours would take the monitor loop down with it.
#
# `budget-retry` is the watcher coming back after the wait it was told to make. The
# transcript still ENDS on that quota error - it is the last thing the session ever said -
# so classifying again would pause again, forever. The cause is how the caller says "I have
# already waited; this time, try."
if [ "$CAUSE" != "budget-retry" ] && { [ "$KIND" = "quota-session" ] || [ "$KIND" = "quota-spend" ]; }; then
  blocks="$(grep -c '^budget-blocked ' "$LEDGER" 2>/dev/null || true)"
  blocks="${blocks:-0}"
  now="$(date +%s)"

  if [ "$KIND" = "quota-session" ] && [ "${DETAIL:-0}" -gt "$now" ] 2>/dev/null; then
    # The harness told us the wall-clock reset. Believe it, plus two minutes of slack.
    retry_at=$(( DETAIL + 120 ))
    why="session limit, resets $(date -r "$retry_at" '+%H:%M' 2>/dev/null || date -d "@$retry_at" '+%H:%M' 2>/dev/null)"
  else
    # No reset time exists for an org spend cap - somebody has to raise it. There is no
    # probe cheaper than the work itself, so back off and let the next resume BE the probe:
    # 20 minutes, then 40, then 80, capped at an hour.
    mins=$(( 20 * (1 << blocks) ))
    [ "$mins" -gt 60 ] && mins=60
    retry_at=$(( now + mins * 60 ))
    why="$KIND, retrying in ${mins}m"
  fi

  # Eight waits is most of a night. Past that, say so plainly rather than idling until noon.
  if [ "$blocks" -ge 8 ]; then
    echo "revive: $TAG - out of capacity for $blocks waits running; giving up on it" >&2
    echo "budget-exhausted $CAUSE $OLD_SID $KIND" >> "$LEDGER"
    [ -f "$STATE/$TAG.summary" ] || \
      echo "never ran: $KIND held it for $blocks waits and capacity never came back" > "$STATE/$TAG.summary"
    echo "BLOCKED: out of budget ($KIND) after $blocks waits" > "$STATE/$TAG.status"
    clear_seen
    rm -f "$STATE/PAUSED"
    exit 7
  fi

  echo "budget-blocked $CAUSE $OLD_SID $KIND retry-at=$retry_at" >> "$LEDGER"
  printf '%s retry-at=%s tag=%s\n' "$KIND" "$retry_at" "$TAG" > "$STATE/PAUSED"
  printf '%s\n' "$retry_at" > "$STATE/$TAG.budget-blocked"
  clear_seen
  echo "revive: $TAG BUDGET-BLOCKED ($why). Sprint paused; the watcher resumes it after $retry_at."
  exit 5
fi

# Resolve a background session id by display name, newest first. Same contract launch.sh uses:
# the launch output format is not stable, `claude agents --json` reporting `name` is.
#
# The second argument is a space-separated list of session ids that already existed BEFORE the
# launch, and it is the belt to the unique-name braces. A name collision resolved to a finished
# session once left the real process untracked all night, and a name is not something this
# script fully controls - the harness may truncate or reuse it. An id that was already there
# cannot be the session we just started, whatever it is called.
resolve_sid() {
  local want="$1" exclude="${2:-}" sid="" rows
  for _ in $(seq 1 15); do
    rows="$(agents_json "$WT")" || return 1   # the list cannot be read: 30s of retries will not help
    sid="$(printf '%s' "$rows" \
      | python3 -c 'import json,sys
want=sys.argv[1]
exclude=set(sys.argv[2].split())
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
best=None
for r in rows:
    if r.get("name")!=want: continue
    if r.get("sessionId") in exclude: continue
    if best is None or r.get("startedAt",0)>best.get("startedAt",0):
        best=r
if best: print(best.get("sessionId",""))' "$want" "$exclude")"
    [ -n "$sid" ] && { printf '%s' "$sid"; return 0; }
    sleep 2
  done
  return 1
}

# Every session id the harness knows about right now. Snapshot this before launching anything.
known_sids() {
  agents_json "$WT" | python3 -c 'import json,sys
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
print(" ".join(str(r.get("sessionId") or "") for r in rows if r.get("sessionId")))'
}

# ---------------------------------------------------------------- rung 1: resume
if [ -n "$OLD_SID" ] && [ "$OLD_SID" != "unresolved" ] && [ "$resumes" -lt "$RESUME_BUDGET" ]; then
  NAME="ns-$SLUG-$TAG-r$attempt"

  case "$CAUSE" in
    api-error) WHY="an API error - the connection dropped or the model call failed. That is infrastructure, not something you did wrong." ;;
    permission-prompt) WHY="a permission prompt. Nobody is awake to answer it, so do not wait for approval: decide it yourself, and if an action stays refused, route around it and say so in your summary." ;;
    idle) WHY="a stall - you went quiet for a long time and the sprint could not tell whether you were still working." ;;
    unarmed) WHY="you ended your turn with nothing armed to wake you - no Monitor and no background command - so you would have waited until morning. Re-arm your Monitor before anything else, and re-arm it every time it expires." ;;
    auth-retry) WHY="the CLI was logged out or its token had expired - nothing to do with your work. A human has re-authenticated and the sprint has brought you back. Your conversation is intact." ;;
    budget-retry) WHY="the account ran out of capacity mid-turn - a spend or session limit, nothing to do with your work. The sprint waited for capacity and has now brought you back. Your conversation is intact." ;;
    *) WHY="something that ended your process before you wrote your status file." ;;
  esac

  if [ "$PHASE" -eq 1 ]; then
  CONTINUE_PROMPT="CONTINUE - you were interrupted, you did not finish, and nobody has taken over.

What stopped you: $WHY

You are a phase CONDUCTOR, and your role is $PROMPT. Everything you had is still in this
conversation. DO NOT START OVER and do not redo a finished step. Re-establish ground truth first:
re-read the LOG.md your role names and the state files it points at. Any Monitor you had armed
died with your process - re-arm it before anything else. A sprint runner you started with
runner.sh did NOT die: it is detached. Check it with \`runner.sh status\`, and arm your Monitor on
\`runner.sh follow\`, which starts again where the last follower stopped. Then carry on from the
step LOG.md names. When your phase is finished, write DONE (or BLOCKED: <reason>) to $WS/state/$TAG.status as
your LAST action - that file is what starts the next phase.

Still an autonomous night run. Nobody is awake to answer a question - decide, note the decision
in your LOG.md, and keep going."
  else
  CONTINUE_PROMPT="CONTINUE - you were interrupted, you did not finish, and nobody has taken over.

What stopped you: $WHY

Everything you had is still in this conversation. DO NOT START OVER and do not re-plan the
ticket. Re-establish ground truth first:
  cd $WT && git status --short && git log --oneline -10
Then carry on from exactly where you stopped.

You still owe the full handoff, in this order: the checks your contract names green (tests run
once, at the end, in FIX-FINAL - before that, static checks only), commit with your SIGNAL line and
push, write $WS/state/$TAG.summary (one line), write $WS/state/$TAG.status LAST, then launch the
next tag if and only if you wrote DONE. Your original contract is $PROMPT - re-read it if you
are unsure what you owe.

Still an autonomous night run. Nobody is awake to answer a question - decide, note the decision
in your summary, and keep going."
  fi

  # The rung's place in its budget, which is what a person reading the log wants. `launch` is the
  # name generation (see above), which only counts up and says nothing about the budget.
  case "$RESUME_KEY" in
    resume) RUNG_OF="resume $(( resumes + 1 )) of $RESUME_BUDGET" ;;
    *)      RUNG_OF="$RESUME_KEY, not counted against the ladder" ;;
  esac
  echo "revive: $TAG rung=resume ($RUNG_OF) launch=r$attempt cause=$CAUSE from=$OLD_SID"
  PRE_SIDS="$(known_sids)"
  ( cd "$WT" && claude --bg --resume "$OLD_SID" -n "$NAME" --permission-mode "$MODE" "$CONTINUE_PROMPT" ) \
    > "$STATE/$TAG.revive-$attempt.log" 2>&1
  rc=$?

  RLOG="$STATE/$TAG.revive-$attempt.log"
  if [ $rc -eq 0 ]; then
    new_sid="$(resolve_sid "$NAME" "$PRE_SIDS")" || new_sid="$(sid_from_launch_log "$RLOG")" || new_sid=""

    # THE HARNESS SAYS SO IN WORDS when the conversation is still live: "session <id> is already
    # running in the background, so this started a copy as <id>". Then the old session was never
    # dead - whatever told the watcher so was wrong - and the copy is seconds old and has done
    # nothing. Stop the copy, keep the original and its session file, and spend no rung. Only a
    # copy that will not stop is a real DUP, and that goes to the conductor.
    if grep -q 'already running in the background' "$RLOG" 2>/dev/null; then
      if [ -n "$new_sid" ] && stop_session "$new_sid"; then
        echo "forked-stopped $CAUSE $OLD_SID $new_sid $NOW_AT" >> "$LEDGER"
        clear_seen
        echo "revive: $TAG - $OLD_SID is ALIVE (the resume found it running); stopped the copy $new_sid, nothing revived" >&2
        exit 1
      fi
      [ -n "$new_sid" ] && printf '%s\n' "$new_sid" > "$SESSION_FILE"
      echo "forked $CAUSE $OLD_SID ${new_sid:-unresolved} $NOW_AT" >> "$LEDGER"
      echo "revive: $TAG - $OLD_SID is ALIVE and its copy ${new_sid:-unresolved} did not stop. DUP - no further rung." >&2
      exit 8
    fi

    if [ -n "$new_sid" ]; then
      printf '%s\n' "$new_sid" > "$SESSION_FILE"
      echo "$RESUME_KEY $CAUSE $OLD_SID $new_sid $NOW_AT" >> "$LEDGER"
      clear_seen
      echo "revive: $TAG resumed as $new_sid ($NAME) - conversation kept, watcher repointed"
      exit 0
    fi

    # rc=0 means a session STARTED. Its id is unknown, but it exists, so the restart rung below
    # would put a second one on the tag. Stop here and let the conductor look.
    echo "unresolved" > "$SESSION_FILE"
    echo "$RESUME_KEY $CAUSE $OLD_SID unresolved $NOW_AT" >> "$LEDGER"
    echo "revive: $TAG resumed (rc=0) but its id did not resolve - NOT restarting on top of it; see $RLOG" >&2
    exit 1
  fi

  # Resume failed. Record the spent attempt so the next call falls through to restart rather
  # than trying the same broken rung again.
  echo "$RESUME_KEY $CAUSE $OLD_SID FAILED(rc=$rc) $NOW_AT" >> "$LEDGER"
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
    if [ "$PHASE" -eq 1 ]; then
      if ! grep -q '^## RESUME - the earlier' "$PROMPT" 2>/dev/null; then
        cat >> "$PROMPT" <<EOF

## RESUME - the earlier conductor session died

An earlier session in this role ended before it wrote its status ($CAUSE), and its conversation
could not be resumed. It may have finished several steps. Before anything else, read the LOG.md
this prompt names and resume at the step it names. Never redo a finished step. A sprint runner
started with runner.sh is detached and is still running: check it with \`runner.sh status\`, then
arm your Monitor on \`runner.sh follow\`.
EOF
      fi
    elif ! grep -q '^## RESUME - the earlier session died' "$PROMPT" 2>/dev/null; then
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
    echo "restart $CAUSE $OLD_SID - $NOW_AT" >> "$LEDGER"
    echo "revive: $TAG rung=restart (restart 1 of 1) launch=$attempt cause=$CAUSE - fresh session on the ticket prompt"
    exec bash "$WS/launch.sh" "$WS" "$TAG"
  fi
fi

# ---------------------------------------------------------------- rung 3: abandon
echo "abandon $CAUSE $OLD_SID - $NOW_AT" >> "$LEDGER"
# Count the rungs actually spent, not this call - the abandon itself is not a revive attempt.
spent=$(( resumes + restarts ))
WITHIN=""
[ "$PHASE" -eq 1 ] && WITHIN=" in ${RUNG_WINDOW_MIN}m"
KEPT=""
[ "$LEFT_RUNNING" -eq 1 ] && KEPT="; $OLD_SID left running, not stopped"
[ -f "$STATE/$TAG.summary" ] || \
  echo "ABANDONED - died again after $spent revive attempts$WITHIN ($CAUSE), never reported a status$KEPT" > "$STATE/$TAG.summary"
echo "BLOCKED: ABANDONED after $spent revive attempts$WITHIN ($CAUSE)$KEPT" > "$STATE/$TAG.status"
echo "revive: $TAG rung=abandon - out of attempts$KEPT. Skip its dependents and report the gap."
