#!/usr/bin/env bash
#
# File every new Claude session into its Project Studio project as it starts.
#
# Fires on SessionStart with the hook payload on stdin. studio/session_hook.py calls one SDK
# function (api.attach_session), which files the session by the studio's own rules: night-sprint
# title ns-<slug>-<TAG>, then cwd/worktree, then a learned rule, else the Inbox. Sessions it
# misses, the studio's next scan files.
#
# It must never block or slow a session: it prints nothing (SessionStart stdout goes into the
# session's context), the Python side kills itself after 3 seconds, hooks.json gives it 5, and it
# exits 0 whatever happened - no python3, a locked or broken store, a bad payload.

HOOK="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%/*}/..}/studio/session_hook.py"
[ -f "$HOOK" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
# The shell's own stderr goes too: when the 3 s alarm ends python3, bash itself reports
# "Alarm clock" on stderr, and a redirect on the command alone does not hide that.
exec >/dev/null 2>&1
python3 "$HOOK"
exit 0
