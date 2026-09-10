#!/usr/bin/env bash
# night-sprint context relay - tell a session that is running out of window to consolidate
# and hand its ticket to a fresh session.
#
#   relay.sh <WORKSPACE> <TAG> [USED_PCT]
#
# USED_PCT is the watcher's reading (the N in `FAT <tag> used-Npct <id>`); it is only used to
# tell the session how full it is.
#
# WHY. A ticket is not the same size as a context window. A session that keeps going until it
# is full does not stop cleanly - it thrashes, auto-compacts away the reasoning that mattered,
# and in the worst case dies mid-edit having written none of it down. Everything it worked out
# (why that approach failed, which file is next, what the failing check actually says) is worth
# more than the tokens it would take to finish. So the sprint hands off instead: the session
# consolidates, writes a filled continuation prompt, and a fresh session picks the SAME ticket up
# with a full window. One ticket, several sessions, still strictly one at a time.
#
# THE HANDOFF LINE IS EARLY ON PURPOSE - 30% used by default, not 90%. A session with 70% of its
# window still free writes a handoff its successor can actually act on, and the successor gets a
# nearly full window to spend on the ticket rather than on recovery. The sprint would rather run
# three fresh sessions per ticket than one exhausted one. The watcher holds this back until the
# session has actually produced work, so an early relay never costs the sprint a pure re-read;
# see tag_has_produced_work in watch.sh.
#
# HOW A SESSION IS TOLD. There is no way to push a message into a running background session,
# so this does what revive.sh does: `claude stop` (the conversation survives on disk), then
# `claude --bg --resume` with the consolidate instruction as the next turn. The session keeps
# everything it knows and simply gets a new, smaller job.
#
# The relayed tag ends as `RELAYED: <cont-tag>` - NOT `DONE`. The ticket is still in flight;
# the continuation owns finishing it and owns launching whatever comes next.

set -uo pipefail

WS="${1:?usage: relay.sh <WORKSPACE> <TAG> [USED_PCT]}"
TAG="${2:?usage: relay.sh <WORKSPACE> <TAG> [USED_PCT]}"
USED="${3:-unknown}"

STATE="$WS/state"
SEEN="$STATE/.watch-seen"
SESSION_FILE="$STATE/$TAG.session"

# A session that already reported a terminal status has nothing left to relay.
if [ -f "$STATE/$TAG.status" ]; then
  echo "relay: $TAG already reported '$(head -1 "$STATE/$TAG.status")' - nothing to relay"
  exit 0
fi

# One relay per tag. The continuation is a new tag with its own window, so a sprint that needs
# three handoffs gets T03 -> T03c2 -> T03c3, each relayed exactly once.
if [ -f "$STATE/$TAG.relayed" ]; then
  echo "relay: $TAG already relayed to $(head -1 "$STATE/$TAG.relayed") - nothing to do"
  exit 0
fi

WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"
MODE="$(tr -d '[:space:]' < "$WS/PERMISSION_MODE" 2>/dev/null || echo auto)"
SLUG="$(tr -d '[:space:]' < "$WS/SLUG" 2>/dev/null || echo sprint)"
OLD_SID=""
[ -f "$SESSION_FILE" ] && OLD_SID="$(tr -d '[:space:]' < "$SESSION_FILE")"

if [ -z "$OLD_SID" ] || [ "$OLD_SID" = "unresolved" ]; then
  echo "relay: $TAG has no resolvable session id - cannot relay it" >&2
  exit 1
fi

# Continuation tag: T03 -> T03c2 -> T03c3. Strip a trailing `c<N>` so the chain stays flat
# instead of growing T03c2c3.
BASE="$TAG"
N=1
case "$TAG" in
  *c[0-9]|*c[0-9][0-9])
    suffix="${TAG##*c}"
    candidate="${TAG%c$suffix}"
    if [ -n "$candidate" ]; then BASE="$candidate"; N="$suffix"; fi
    ;;
esac
CONT="${BASE}c$(( N + 1 ))"

# What the ticket was supposed to hand off to when it finished. The continuation inherits that
# duty; without it the sprint stops dead at the end of this ticket.
NEXT_TAG=""
[ -f "$STATE/$BASE.next" ] && NEXT_TAG="$(tr -d '[:space:]' < "$STATE/$BASE.next")"
if [ -n "$NEXT_TAG" ]; then
  NEXT_LINE="that when the ticket is finally green it must launch $NEXT_TAG - state that duty explicitly"
else
  NEXT_LINE="whatever NEXT_TAG your own prompt told you to launch when done - the continuation inherits that duty, so name it explicitly, or say plainly that there is none"
fi

CONSOLIDATE_PROMPT="CONTEXT RELAY - you have reached the handoff line. Consolidate and hand off.

You have used about ${USED}% of your context window. THIS IS NOT AN EMERGENCY and you have not
run out of anything - the sprint hands a ticket on early, while the session doing it still has
most of a window left to explain itself clearly. That is the whole point: your successor should
inherit a good handoff and a nearly full window, not a rushed note from a session that was
thrashing. Several sessions per ticket is the expected shape of this sprint, not a failure, and
your ticket is not being taken away from you.

FIRST, THE EXCEPTION. If this ticket is essentially finished - the code is written and all that
is left is running the verify command, committing and pushing - then FINISH IT the normal way,
exactly as your original prompt's \"WHEN YOU ARE DONE\" steps say, and ignore everything below.
Splitting a ticket that was one command from green costs the sprint a whole session of
re-reading for nothing.

OTHERWISE, do exactly this, in order, and nothing else:

1. GET WHAT YOU HAVE ONTO THE BRANCH. cd $WT. Leave nothing uncommitted and never stash or
   revert. If the tree is green, commit and push as usual. If it is not green, commit anyway as
   a WIP commit whose body carries:
     SIGNAL: $TAG-RELAYED
   and names exactly which checks are failing. Your successor needs the work far more than the
   branch needs a tidy history.

2. WRITE THE CONTINUATION PROMPT at $WS/prompt-$CONT.txt, filling in every placeholder of the
   template at $WS/continuation-prompt.md. This file is the ONLY thing your successor inherits -
   it starts with an empty window and cannot read this conversation. Assume it knows nothing.
   Write down, concretely:
     - the ticket, and which acceptance criteria are already met and which are not
     - the commits you landed (sha + subject) and what in them is still WIP
     - the real verify status: which checks pass, which fail, and the actual failure text
     - the files you changed, and the ones you had already decided to change next
     - every decision you made and every approach you ruled out, with the reason, so your
       successor does not spend its window rediscovering what you already know
     - $NEXT_LINE
   \"Continue where I left off\" is not a handoff. Be specific enough that a stranger could
   take over.

3. echo \"<one line: what you landed, and what is left for $CONT>\" > $WS/state/$TAG.summary

4. Release yourself - this is the last thing you write about yourself, and it says RELAYED, not
   DONE. Your ticket is still in flight; DONE would let the sprint move on to the next ticket
   with your work unfinished:
     echo \"RELAYED: $CONT\" > $WS/state/$TAG.status

5. bash $WS/launch.sh $WS $CONT
   The claim is atomic - if the conductor already started $CONT this is a harmless no-op. Run
   it once and do not second-guess the result. Do NOT launch the next ticket; $CONT owns that.

Then stop. Post three lines as your last message: what landed, what is left, and the
continuation tag. Still an autonomous night run - nobody is awake to answer a question."

echo "relay: $TAG used=${USED}pct -> handing off to $CONT (from $OLD_SID)"

# Stop the running session first. The conversation stays resumable; this is the only way to get
# a new instruction in front of a background session.
claude stop "$OLD_SID" >/dev/null 2>&1

NAME="ns-$SLUG-$TAG-relay"
( cd "$WT" && claude --bg --resume "$OLD_SID" -n "$NAME" --permission-mode "$MODE" "$CONSOLIDATE_PROMPT" ) \
  > "$STATE/$TAG.relay.log" 2>&1
rc=$?

# A resumed session gets a NEW session id and does not inherit its display name. Repoint the
# watcher at it, or the sprint spends the rest of the night watching a corpse.
new_sid=""
if [ $rc -eq 0 ]; then
  for _ in $(seq 1 15); do
    new_sid="$(claude agents --json --all --cwd "$WT" 2>/dev/null \
      | python3 -c 'import json,sys
want=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
best=None
for r in rows:
    if r.get("name")==want and (best is None or r.get("startedAt",0)>best.get("startedAt",0)):
        best=r
if best: print(best.get("sessionId",""))' "$NAME")"
    [ -n "$new_sid" ] && break
    sleep 2
  done
fi

if [ $rc -ne 0 ] || [ -z "$new_sid" ]; then
  # Not fatal. The session is fat, not broken, and the harness will auto-compact it. Say so
  # loudly, leave the tag unmarked, and let the sprint carry on rather than abandoning work.
  echo "relay: $TAG relay FAILED (rc=$rc, see $STATE/$TAG.relay.log) - session left to run on and auto-compact" >&2
  echo "relay-failed $USED $OLD_SID -" >> "$STATE/$TAG.relays"
  exit 1
fi

printf '%s\n' "$new_sid" > "$SESSION_FILE"
printf '%s\n' "$CONT" > "$STATE/$TAG.relayed"
echo "relay $USED $OLD_SID $new_sid $CONT" >> "$STATE/$TAG.relays"

# The watcher emits each (tag, verdict) once. Clear this tag's rows so its RELAYED status, and
# any later death, are still reported. The `.relayed` marker above is what stops FAT refiring.
if [ -f "$SEEN" ]; then
  grep -v "^$TAG:" "$SEEN" > "$SEEN.tmp" 2>/dev/null || true
  [ -f "$SEEN.tmp" ] && mv "$SEEN.tmp" "$SEEN"
fi

echo "relay: $TAG consolidating as $new_sid ($NAME); continuation tag is $CONT"
