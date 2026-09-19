#!/usr/bin/env bash
# night-sprint error classifier - what actually ended this session, in one word.
#
#   classify-error.sh <SESSION_ID>
#
# Prints ONE line: `<class> [detail]`. Exit 0 always - "none" is a real answer.
#
#   transient <kind>       dropped connection, stalled stream, 529/500, DNS, timeout.
#                          Infrastructure. Resume it, that is what the ladder is for.
#   quota-session <epoch>  the rolling session limit, WITH the reset time it names.
#                          Nothing to fix and nothing to retry until <epoch>. Wait.
#   quota-spend            the org monthly spend cap. No reset time exists: a human
#                          has to raise it. Poll for capacity, never hammer.
#   auth <why>             logged out, expired token, subscription disabled.
#                          A human must act. NEVER retry - retrying cannot succeed.
#   none                   no terminal API error, or the session carried on after one.
#
# WHY THIS IS ITS OWN FILE. `watch.sh` decides what to emit and `revive.sh` decides what
# to do, and for months they each sniffed the transcript their own way - `grep -q
# isApiErrorMessage` in both, which answers "was there an error" and not "which kind".
# So a spending cap and a dropped socket produced the same `api-error` verdict, the
# reviver spent its whole resume ladder against a wall it could not climb, and the night's
# operational log recorded a two-hour spend-limit outage as a one-hour permission stall.
# One classifier, two callers, and the class is named rather than guessed.
#
# The strings are the harness's own, taken verbatim from real transcripts:
#   "You've hit your org's monthly spend limit - run /usage-credits to raise it, ..."
#   "You've hit your session limit - resets 4:20pm (Asia/Jerusalem)"
#   "Not logged in - Please run /login"
#   "API Error: Connection closed mid-response. ..."
# Matched on their ASCII substrings only: the live text separates clauses with a
# non-ASCII middle dot, and a pattern that depends on that byte breaks the day it changes.

set -uo pipefail

SID="${1:?usage: classify-error.sh <SESSION_ID|TRANSCRIPT_PATH>}"

# A path is accepted as well as an id, purely so the tests can drive this with fixtures
# instead of a live transcript. Every one of the classes below was a real night once, and
# a class nobody can test offline is a class that rots.
if [ -f "$SID" ]; then
  f="$SID"
else
  f="$(ls -t "$HOME"/.claude/projects/*/"$SID".jsonl 2>/dev/null | head -1)"
fi
[ -n "$f" ] || { echo none; exit 0; }

tail -n 400 "$f" 2>/dev/null | python3 -c '
import json, re, sys
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# The LAST api-error, and whether the session spoke again afterwards. A session that hit a
# 529, got resumed by its own retry and carried on is not a session that died of a 529.
err = None
recovered = False
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
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    else:
        text = str(content or "")
    if row.get("isApiErrorMessage"):
        err = (" ".join(text.split()), row.get("timestamp"))
        recovered = False
    elif err is not None and text.strip():
        recovered = True

if err is None or recovered:
    print("none")
    raise SystemExit(0)

text, stamp = err
low = text.lower()

# --- a human must act. Retrying cannot succeed, so the ladder must not spend a rung on it.
if "not logged in" in low or "please run /login" in low:
    print("auth logged-out"); raise SystemExit(0)
if "oauth access token has expired" in low or "401" in low and "token" in low:
    print("auth token-expired"); raise SystemExit(0)
if "disabled claude subscription access" in low:
    print("auth subscription-disabled"); raise SystemExit(0)

# --- the org spend cap. There is no reset time: somebody has to raise the limit.
if "spend limit" in low or "spending limit" in low or "usage-credits" in low:
    print("quota-spend"); raise SystemExit(0)

# --- the rolling session limit. It names its own reset, which is the whole point:
#     the sprint can wait exactly that long instead of guessing or giving up.
if "session limit" in low or "usage limit" in low or "rate limit" in low:
    reset = None
    m = re.search(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*(?:\(([^)]+)\))?", text, re.I)
    if m:
        hour = int(m.group(1)) % 12
        minute = int(m.group(2) or 0)
        if (m.group(3) or "").lower() == "pm":
            hour += 12
        tz = None
        if ZoneInfo and m.group(4):
            try:
                tz = ZoneInfo(m.group(4).strip())
            except Exception:
                tz = None
        # Anchor to the error itself, not to now: a sprint may read this file hours later
        # and must still resolve the same wall-clock reset the harness named.
        base = None
        if stamp:
            try:
                base = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            except Exception:
                base = None
        if base is None:
            base = datetime.now(tz) if tz else datetime.now()
        if tz:
            base = base.astimezone(tz)
        elif base.tzinfo:
            base = base.astimezone()
        target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= base:
            target += timedelta(days=1)
        reset = int(target.timestamp())
    # 0 means "a session limit with no reset time we could parse" - the caller falls back
    # to a fixed wait rather than treating an unparsed clock as no limit at all.
    print("quota-session %d" % (reset or 0))
    raise SystemExit(0)

# --- everything else the API does to a session is infrastructure. Resume it.
for needle, kind in (
    ("connection closed", "connection-closed"),
    ("stalled mid-stream", "stalled"),
    ("529", "overloaded"),
    ("overloaded", "overloaded"),
    ("500", "server-error"),
    ("server error", "server-error"),
    ("enotfound", "dns"),
    ("econnreset", "reset"),
    ("unable to connect", "unreachable"),
    ("timed out", "timeout"),
    ("could not be parsed", "bad-tool-call"),
):
    if needle in low:
        print("transient %s" % kind); raise SystemExit(0)

print("transient unknown")
'
