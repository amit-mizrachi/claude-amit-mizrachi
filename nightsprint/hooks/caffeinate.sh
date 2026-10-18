#!/usr/bin/env bash
#
# Keep macOS awake for 8 hours after the last Claude Code interaction.
#
# Fires on SessionStart and on every UserPromptSubmit. Each invocation starts a
# fresh 8-hour `caffeinate` and kills the previous one, giving a sliding window:
# the Mac stays awake until 8 hours pass with no Claude activity, then sleeps
# normally. The timer is global across sessions and keeps counting even if you
# quit Claude Code (it releases at the 8h mark regardless).

# macOS only; silently no-op everywhere else.
[ "$(uname)" = "Darwin" ] || exit 0
command -v caffeinate >/dev/null 2>&1 || exit 0

TIMEOUT_SECONDS=28800   # 8 hours
PIDFILE="${HOME}/.claude/.caffeinate-8h.pid"
PATTERN="caffeinate -i -s -t $TIMEOUT_SECONDS"

# Stop the previous managed caffeinate so 8h timers don't stack. Verify the PID
# is actually our caffeinate before killing — guards against PID reuse killing
# an unrelated process.
if [ -f "$PIDFILE" ]; then
  OLD=$(cat "$PIDFILE" 2>/dev/null)
  if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null \
     && ps -p "$OLD" -o command= 2>/dev/null | grep -qF "$PATTERN"; then
    kill "$OLD" 2>/dev/null
  fi
fi

# -i: no idle system sleep  -s: no sleep on AC  -t: auto-exit after the timeout.
# Nothing is written to stdout (UserPromptSubmit stdout would be injected into
# the prompt) — the PID goes to the pidfile, all caffeinate output is discarded.
nohup caffeinate -i -s -t "$TIMEOUT_SECONDS" >/dev/null 2>&1 &
echo "$!" > "$PIDFILE"
disown 2>/dev/null || true

exit 0
