#!/usr/bin/env bash
# night-sprint context gauge - how much of a session's context window it has already USED.
#
#   context-used.sh <SESSION_ID> [CONTEXT_WINDOW]
#   context-used.sh --self      [CONTEXT_WINDOW]
#
# Prints one whole number: the percent of the window already used (0-100). 0 is a fresh
# session, 100 is a full one. Prints nothing and exits 1 when it cannot tell - no transcript
# yet, or nothing in it to measure.
#
# THE NUMBER COUNTS UP, AND THAT IS DELIBERATE. This replaced `context-left.sh`, which counted
# the same thing DOWN (percent still free). Every threshold in the sprint reads "used", the way
# `/context` shows it, so the thresholds are small numbers that get bigger as a session fills:
# nudge at 20, hand off at 30. Under the old gauge those same points were 80 and 70, which is
# an easy thing to get backwards and an expensive thing to get backwards - a sprint configured
# with the wrong polarity either relays every session at birth or never relays one at all. The
# rename is the guard: a stale caller asking for `context-left.sh` fails loudly instead of
# silently inverting.
#
# WHY THIS EXISTS. A night sprint is long and a context window is not. A session that runs out
# mid-ticket does not fail loudly; it silently loses everything it worked out and has to be
# rebuilt from the codebase. Measuring the window turns that into a scheduled handoff: the
# sprint relays the ticket into a fresh session while the old one still has most of its window
# left to explain itself. `watch.sh` calls this for every open tag; the conductor calls it on
# itself.
#
# HOW IT MEASURES. Every assistant turn in the transcript records its own `usage`. The size of
# the conversation right now is the last turn's input + cache_creation + cache_read + output -
# cache reads are the bulk of the window, so leaving them out reads as almost-empty when the
# session is nearly full. Sidechain rows are subagents running in their OWN windows; counting
# them reports the parent as full while it is not, so they are skipped.
#
#   CONTEXT_WINDOW defaults to 200000. A 1M-context model needs it passed - the transcript
#   records the model as `claude-opus-5` whether or not it is the 1M variant, so the window
#   cannot be inferred from the file. The sprint pins it in <WS>/CONTEXT_WINDOW at kickoff.

set -uo pipefail

SID="${1:?usage: context-used.sh <SESSION_ID|--self> [CONTEXT_WINDOW]}"
WINDOW="${2:-200000}"

[ "$SID" = "--self" ] && SID="${CLAUDE_CODE_SESSION_ID:-}"
[ -n "$SID" ] || { echo "context-used: no session id (CLAUDE_CODE_SESSION_ID unset?)" >&2; exit 1; }

f="$(ls -t "$HOME"/.claude/projects/*/"$SID".jsonl 2>/dev/null | head -1)"
[ -n "$f" ] || exit 1

# Only the tail is needed - the last main-thread turn is what counts - and a whole night's
# transcript is large. A partial first line from `tail` just fails to parse and is skipped.
tail -n 1500 "$f" 2>/dev/null | python3 -c '
import json, sys

try:
    win = float(sys.argv[1])
except (IndexError, ValueError):
    win = 0.0
if win <= 0:
    win = 200000.0   # a missing or malformed CONTEXT_WINDOW must not silently disable the relay

used = None
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        row = json.loads(line)
    except Exception:
        continue
    if row.get("type") != "assistant" or row.get("isSidechain"):
        continue
    msg = row.get("message")
    usage = msg.get("usage") if isinstance(msg, dict) else None
    if not isinstance(usage, dict):
        continue
    used = ((usage.get("input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0)
            + (usage.get("cache_read_input_tokens") or 0)
            + (usage.get("output_tokens") or 0))

if used is None:
    sys.exit(1)
print(max(0, min(100, int(round(100.0 * used / win)))))
' "$WINDOW"
