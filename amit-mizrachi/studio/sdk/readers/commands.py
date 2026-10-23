"""Running the outside commands the readers need (`claude`, `gh`, `git`), and where they look.

A reader never trusts a command that failed: `run` returns `(ok, stdout, error)`, and a caller
that gets `ok=False` must treat what it knows as UNKNOWN, never as an empty answer.

Paths every reader shares, each overridable by an env var (tests point them at fixtures):
- `PROJECT_STUDIO_ROOTS` (colon-separated), else `NIGHT_WATCH_ROOTS`, else night-watch's
  defaults: where night-sprint and night-marathon workspaces live.
- `PROJECT_STUDIO_CLAUDE_HOME`, else `~/.claude`: where `jobs/` and `projects/` live.
"""

import os
import subprocess

from .workspace import DEFAULT_ROOTS

TIMEOUT = 20


def roots():
    """The workspace roots, in order."""
    for name in ("PROJECT_STUDIO_ROOTS", "NIGHT_WATCH_ROOTS"):
        found = [r for r in os.environ.get(name, "").split(":") if r]
        if found:
            return [os.path.abspath(os.path.expanduser(r)) for r in found]
    return list(DEFAULT_ROOTS)


def claude_home():
    """The Claude Code data dir that holds `jobs/` and `projects/`."""
    return os.path.abspath(os.path.expanduser(os.environ.get("PROJECT_STUDIO_CLAUDE_HOME") or "~/.claude"))


def run(argv, cwd=None, timeout=TIMEOUT):
    """Run one command. Returns (ok, stdout, error): ok only for exit 0 within the timeout."""
    try:
        done = subprocess.run(argv, cwd=cwd or os.path.expanduser("~"), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                              universal_newlines=True, timeout=timeout)
    except FileNotFoundError:
        return False, "", "%s is not installed or not on PATH" % argv[0]
    except subprocess.TimeoutExpired:
        return False, "", "%s timed out after %d s" % (" ".join(argv[:3]), timeout)
    except OSError as exc:
        return False, "", "%s could not run: %s" % (argv[0], exc)
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        return False, done.stdout, "%s exited %d%s" % (" ".join(argv[:3]), done.returncode,
                                                        ": " + detail[-1][:200] if detail else "")
    return True, done.stdout, ""
