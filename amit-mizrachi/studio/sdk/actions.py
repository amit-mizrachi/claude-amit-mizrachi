"""Open actions and Open in Terminal (D4 A: open and copy only).

Rules kept here:
- What opens comes from the store, never from the request: a caller names an item id (and for a
  run, `plan` or `pr`); the URL or path is that item's own.
- `open` gets only an http(s) URL, or an absolute path under a known root (the workspace roots,
  the repos `git worktree list` was read in, and the folders of stored runs and worktrees). A
  folder opens in Finder; a file a browser or viewer shows opens; any other file is only revealed
  (`open -R`), so a stored path never runs a program.
- A session opens again with `claude attach <short>` when `claude agents` lists it, else with
  `cd <recorded cwd> && claude --resume <session id>`. Every value is pattern-checked and
  shlex-quoted, then written to `<data dir>/open/<item id>.command` (mode 0700) and opened in the
  `terminal` setting's app (sdk/settings.py): by default `open <file>`, which hands it to whatever
  app opens .command files (Terminal); `open -a Terminal <file>`; or for iTerm, `osascript` with a
  fixed script that opens a new window with the default profile and writes the file's quoted path
  into it (the path is the script's argument, never part of the script).
- When the open fails, the command goes to the clipboard (`pbcopy`) and the message says so.
- A resume of a session whose transcript changed in the last 5 minutes is confirmed once first.
- Nothing here stops, kills or removes anything.
"""

import os
import re
import shlex
import subprocess
import time
from urllib.parse import urlparse

from . import settings, store
from .errors import InvalidInput, Refused
from .items import SESSION_KEY, row as item_row
from .readers import commands, sessions as session_reader
from .reconcile import WORKSPACE_KINDS, item_data
from .results import OpenResult, TerminalCommand, TerminalOpen

SHORT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SESSION_KINDS = ("session-bg", "session-interactive")
RECENT_SECONDS = 300
OPEN_TIMEOUT = 10
TARGETS = ("default", "plan", "pr")
BUNDLE_EXTENSIONS = (".app", ".bundle", ".framework", ".prefpane", ".saver", ".workflow", ".action")   # `open` runs these
VIEW_EXTENSIONS = (".html", ".htm", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".txt", ".json", ".log")
ITERM_SCRIPT = ('on run argv', 'tell application "iTerm"', 'activate',
                'set w to (create window with default profile)',
                'tell current session of w to write text (item 1 of argv)', 'end tell', 'end run')


# ---------------------------------------------------------------- Open in Terminal

def run_session(conn, run_id):
    """The run's newest session `claude agents` still lists (bg first), or None."""
    found = [dict(r) for r in conn.execute("SELECT * FROM items WHERE workspace_item_id = ? AND gone_at IS NULL "
                                           "AND kind IN ('session-bg', 'session-interactive')", (run_id,))]
    found = [r for r in found if item_data(r).get("listed")]
    found.sort(key=lambda r: item_data(r).get("last_active") or item_data(r).get("started_at") or "", reverse=True)
    found.sort(key=lambda r: r["kind"] != "session-bg")
    return found[0] if found else None


def session_of(conn, item_id):
    """The session item behind `item_id`: a session itself, or a run's live session."""
    r = item_row(conn, item_id)
    if r["kind"] in SESSION_KINDS:
        return r
    if r["kind"] in WORKSPACE_KINDS:
        found = run_session(conn, item_id)
        if found is None:
            raise Refused("%s has no live session to open." % r["title"])
        return found
    raise InvalidInput("Only a session or a night run opens in Terminal.")


def command_for(session_id, short, cwd, listed):
    """(mode, command): `claude attach <short>` when listed, else `cd <cwd> && claude --resume <id>`.

    Refuses an id that does not match its pattern and a resume with no absolute recorded folder.
    """
    if listed:
        if not isinstance(short, str) or not SHORT_ID.match(short):
            raise Refused("This session's short id %r is not one Claude Code prints." % (short,))
        return "attach", "claude attach %s" % shlex.quote(short)
    if not isinstance(session_id, str) or not SESSION_KEY.match(session_id):
        raise Refused("This session's id %r is not a session UUID." % (session_id,))
    if not isinstance(cwd, str) or not os.path.isabs(cwd) or any(ord(c) < 32 for c in cwd):
        raise Refused("This session has no recorded folder to resume it in.")
    return "resume", "cd %s && claude --resume %s" % (shlex.quote(cwd), shlex.quote(session_id))


def _listed(session_id):
    """(listed, short) from a fresh `claude agents`, or None when it cannot answer."""
    read = session_reader.agents()
    if not read.ok:
        return None
    for rec in read.records:
        if rec["session_id"] == session_id:
            return True, rec["short"]
    return False, ""


def _recent(transcript, now):
    """Seconds (at least 1) since the transcript changed, when under 5 minutes; else 0."""
    try:
        changed = os.stat(transcript).st_mtime if transcript else 0
    except OSError:
        return 0
    return max(1, int(now - changed)) if changed and now - changed < RECENT_SECONDS else 0


def terminal_command(r, now=None):
    """The TerminalCommand for session row `r`, asking `claude agents` (the stored `listed` when it fails)."""
    data = item_data(r)
    sid, short = data.get("session_id") or r["key"], data.get("short") or ""
    fresh = _listed(sid)
    listed, short = fresh if fresh is not None else (bool(data.get("listed")), short)
    mode, command = command_for(sid, short or sid[:8], data.get("cwd"), listed)
    confirm = ""
    if mode == "resume":
        secs = _recent(data.get("transcript"), time.time() if now is None else now)
        if secs:
            confirm = ("%s changed %s ago and may still be open in another window. Resume it here too?"
                       % (r["title"], "%d min" % (secs // 60) if secs >= 60 else "%d s" % secs))
    return TerminalCommand(item_id=r["id"], mode=mode, command=command, session_id=sid, short=short,
                           cwd=str(data.get("cwd") or ""), confirm=confirm)


def write_command_file(item_id, command):
    """Write `<data dir>/open/<item id>.command` (mode 0700, folder 0700) and return its path."""
    folder = os.path.join(store.home(), "open")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    path = os.path.join(folder, "%s.command" % item_id)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o700)
    with os.fdopen(fd, "w") as fh:
        fh.write("#!/bin/bash\n# Written by Project Studio: Open in Terminal.\n%s\n" % command)
    os.chmod(tmp, 0o700)
    os.replace(tmp, path)
    return path


def copy(text):
    """Put `text` on the clipboard with `pbcopy`. True when it worked."""
    try:
        done = subprocess.run(["pbcopy"], input=text, universal_newlines=True, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=OPEN_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def launch_argv(app, path):
    """The argv that opens the .command file at `path` in `app` ("" = the default app)."""
    if app == "iTerm":
        return ["osascript"] + [arg for line in ITERM_SCRIPT for arg in ("-e", line)] + [shlex.quote(path)]
    if app == "Terminal":
        return ["open", "-a", "Terminal", path]
    return ["open", path]


def open_in_terminal(cmd, confirmed):
    """Open the .command file of a built command in the `terminal` setting's app; on failure copy
    the command. Asks first when `confirm`."""
    if cmd.confirm and not confirmed:
        return TerminalOpen(command=cmd, opened=False, copied=False, needs_confirm=True, path=None,
                            message=cmd.confirm)
    app, note = settings.terminal()
    name = app or "Terminal"
    note = note + " " if note else ""
    path, opened = None, False
    try:
        path = write_command_file(cmd.item_id, cmd.command)
        opened = commands.run(launch_argv(app, path), timeout=OPEN_TIMEOUT)[0]
    except OSError:
        opened = False
    if opened:
        return TerminalOpen(command=cmd, opened=True, copied=False, needs_confirm=False, path=path,
                            message="%sOpened in %s:" % (note, name), app=app)
    copied = copy(cmd.command)
    message = "%sCould not open %s. %s:" % (note, name, "Command copied" if copied else "Copy this command")
    return TerminalOpen(command=cmd, opened=False, copied=copied, needs_confirm=False, path=path, message=message,
                        app=app)


# ---------------------------------------------------------------- open a URL or a path

def known_roots(conn):
    """The folders a stored path may be under: workspace roots, read repos, stored runs and worktrees."""
    found = list(commands.roots())
    found += [r["key"] for r in conn.execute("SELECT key FROM cache WHERE source = 'worktrees'")]
    marks = ",".join("?" * (len(WORKSPACE_KINDS) + 1))
    found += [r["key"] for r in conn.execute("SELECT key FROM items WHERE kind IN (%s)" % marks,
                                             WORKSPACE_KINDS + ("worktree",))]
    return [os.path.realpath(p) for p in found if p and os.path.isabs(p)]


def _under(path, roots):
    return any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots)


def _plan_value(conn, run):
    arts = [dict(a) for a in conn.execute("SELECT * FROM items WHERE kind = 'artifact' AND workspace_item_id = ?",
                                          (run["id"],))]
    arts.sort(key=lambda a: not item_data(a).get("plan"))
    if not arts:
        raise Refused("%s has no plan page." % run["title"])
    data = item_data(arts[0])
    return data.get("url") or data.get("file") or arts[0]["key"]


def _pr_value(conn, r):
    if r["kind"] == "pr":
        return item_data(r).get("url") or ""
    prs = [dict(p) for p in conn.execute("SELECT * FROM items WHERE kind = 'pr' AND workspace_item_id = ?", (r["id"],))]
    prs.sort(key=lambda p: item_data(p).get("updated_at") or "", reverse=True)
    prs.sort(key=lambda p: item_data(p).get("state") != "open")
    url = item_data(prs[0]).get("url") if prs else item_data(r).get("pr_url")
    if not url:
        raise Refused("%s has no pull request." % r["title"])
    return url


def target_value(conn, r, target):
    """The URL or path an item opens, from the store: a run's folder, plan page or PR; a PR's URL;
    an artifact's URL or file; a worktree's folder; a session's recorded folder."""
    kind, data = r["kind"], item_data(r)
    if target == "plan":
        if kind not in WORKSPACE_KINDS:
            raise InvalidInput("Only a night run has a plan page.")
        return _plan_value(conn, r)
    if target == "pr" or kind == "pr":
        if kind not in WORKSPACE_KINDS + ("pr",):
            raise InvalidInput("Only a night run or a PR has a pull request.")
        return _pr_value(conn, r)
    if kind == "artifact":
        return data.get("url") or data.get("file") or r["key"]
    if kind in SESSION_KINDS:
        return data.get("cwd") or ""
    return r["key"]


def open_argv(value, roots):
    """(how, argv) for `open`: an http(s) URL, a folder, a file to show, or a file to reveal only.

    Refuses anything else, and any path that is not under one of `roots` (symlinks resolved).
    """
    if value.startswith(("https://", "http://")):
        parts = urlparse(value)
        if not parts.netloc or any(ord(c) <= 32 or ord(c) == 127 for c in value):
            raise Refused("%r is not a URL the studio opens." % value)
        return "url", ["open", value]
    if not os.path.isabs(value):
        raise Refused("The studio opens only http(s) URLs and folders it knows; %r is neither." % value)
    path = os.path.realpath(value)
    if not os.path.exists(path):
        raise Refused("%s is not on this Mac any more." % value)
    if not _under(path, roots):
        raise Refused("%s is not under a folder the studio knows." % value)
    if os.path.isdir(path):
        if path.lower().endswith(BUNDLE_EXTENSIONS):
            return "reveal", ["open", "-R", path]
        return "folder", ["open", path]
    if path.lower().endswith(VIEW_EXTENSIONS):
        return "file", ["open", path]
    return "reveal", ["open", "-R", path]


def resolve_target(conn, item_id, target):
    """(item id, value, how, argv) for opening item `item_id` (its `target`: default, plan or pr)."""
    if target not in TARGETS:
        raise InvalidInput("target must be one of: %s." % ", ".join(TARGETS))
    r = item_row(conn, item_id)
    value = target_value(conn, r, target)
    if not value:
        raise Refused("%s has nothing to open." % r["title"])
    how, argv = open_argv(value, known_roots(conn))
    return r["id"], value, how, argv


def run_open(item_id, target, value, how, argv):
    """Run the `open` argv `resolve_target` built. Returns an OpenResult."""
    ok, _, error = commands.run(argv, timeout=OPEN_TIMEOUT)
    message = ("Opened %s" % value) if ok else ("Could not open %s: %s" % (value, error))
    return OpenResult(item_id=item_id, target=target, value=value, how=how, opened=ok, message=message)
