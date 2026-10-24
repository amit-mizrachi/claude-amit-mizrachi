#!/usr/bin/env python3
"""The SessionStart hook's adapter: file the starting session into its project.

Run by `hooks/attach-session.sh` with the hook payload on stdin ({"session_id", "cwd", ...}).
It parses the payload and the session's env, calls ONE SDK function (`api.attach_session`), and
says nothing: SessionStart stdout would go into the session's context. Every failure (bad
input, a locked or broken store, a newer store) is swallowed with exit 0, and SIGALRM kills the
process after BUDGET_SECONDS whatever it is doing, so a session start is never blocked.
"""

import json
import os
import signal
import sys

BUDGET_SECONDS = 3
MAX_PAYLOAD = 64 * 1024


def main():
    signal.signal(signal.SIGALRM, signal.SIG_DFL)      # the default action ends the process, even inside SQLite
    signal.alarm(BUDGET_SECONDS)
    try:
        payload = json.loads(sys.stdin.read(MAX_PAYLOAD) or "{}")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from sdk import api
        api.attach_session(payload.get("session_id"), payload.get("cwd"),
                           job_dir=os.environ.get("CLAUDE_JOB_DIR"),
                           entrypoint=os.environ.get("CLAUDE_CODE_ENTRYPOINT"))
    except BaseException:                               # noqa: B902 - a hook never fails a session
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
