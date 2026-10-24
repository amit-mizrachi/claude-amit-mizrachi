"""Throw away a night run: the ONE action in the studio that removes things, and only when confirmed.

Rules kept here:
- `plan` changes nothing. It names what would go (the run's folder, each worktree, how many
  attached items) and refuses (`Refused`) before anything happens when:
  - the item is not a night run;
  - the folder is not strictly under a known run root (`commands.roots()`): symlinks resolved, a
    `..` part refused, the root itself refused, the folder itself a symlink refused, and a folder
    with no `state/` (or `phases/PHASE_CHAIN`) is no workspace;
  - a worktree holds the folder (removing it would delete the folder outright);
  - git cannot say which ignored files a worktree holds. `git worktree remove` does not count
    gitignored files as changes and deletes them for good (never to the Trash), so the plan names
    them (`ThrowWorktree.ignored`) and the message says so;
  - the run's runner (`watch.sh`) is alive in any of its state folders;
  - a session of the run is live: `claude agents` lists it (by id, or by a cwd inside the folder or
    a worktree) in a state that is not finished, or an attached interactive session's transcript
    changed in the last 5 minutes. When `claude agents` cannot answer, that is refused too: unknown
    is never "not live".
- `execute` runs the steps in this order and stops at the first that fails, with a message that
  says what was done and what was not:
  1. each worktree: `git -C <repo> worktree remove <path>`, never `--force`, so git refuses a
     worktree with changes and keeps the branch (its commits survive). A worktree `git worktree
     list` no longer lists is skipped.
  2. the folder: to the macOS Trash through Finder (`osascript`, the path is the script's argument,
     never part of it); never a plain delete. It must be gone from its place afterwards.
  3. the store, in one transaction: the run and its attached items are marked gone and purged, and
     the cache rows that listed the folder and the worktrees are dropped, so the next refresh reads
     them again instead of bringing the run back from the cache. Nothing else is touched.
- It never stops, kills or removes a session.
"""

import glob
import os
import sqlite3

from . import store
from .errors import Refused, StudioError
from .inventory import ACTIVE_SECONDS
from .items import purge, row as item_row
from .projectview import FINISHED
from .readers import commands, git, sessions as session_reader
from .readers.workspace import World, read1
from .reconcile import WORKSPACE_KINDS, item_data
from .results import ThrowAway, ThrowWorktree

SESSION_KINDS = ("session-bg", "session-interactive")
TRASH_SCRIPT = ('on run argv', 'tell application "Finder" to delete (POSIX file (item 1 of argv) as alias)',
                'end run')
STEP_TIMEOUT = 60


# ---------------------------------------------------------------- what would go

def _inside(path, folder):
    return bool(path and folder) and (path == folder or path.startswith(folder.rstrip("/") + "/"))


def check_folder(key):
    """The run's folder, symlinks resolved, once it passes every check; "" when it is no longer on this Mac."""
    if not isinstance(key, str) or not os.path.isabs(key) or any(ord(c) < 32 for c in key):
        raise Refused("%r is not a folder path, so the studio will not throw it away." % (key,))
    if ".." in key.split("/"):
        raise Refused("%s has a '..' in it; the studio throws away only plain folders under the run roots." % key)
    real = os.path.realpath(key)
    roots = [os.path.realpath(r) for r in commands.roots()]
    if not any(_inside(real, root) and real != root for root in roots):
        raise Refused("%s is not inside a run root (%s), so the studio will not throw it away."
                      % (key, ", ".join(commands.roots())))
    if not os.path.lexists(key):
        return ""
    if os.path.islink(key) or not os.path.isdir(real):
        raise Refused("%s is not a plain folder, so the studio will not throw it away." % key)
    if not (os.path.isdir(os.path.join(real, "state")) or os.path.exists(os.path.join(real, "phases", "PHASE_CHAIN"))):
        raise Refused("%s holds no night-run state, so the studio will not throw it away." % key)
    return real


def _attached(conn, run_id, kinds=None):
    rows = [dict(r) for r in conn.execute("SELECT * FROM items WHERE workspace_item_id = ? ORDER BY kind, key",
                                          (run_id,))]
    return [r for r in rows if kinds is None or r["kind"] in kinds]


def worktrees_of(conn, run_id, folder):
    """The run's worktrees still listed (attached worktree items not gone), each checked."""
    out = []
    for r in _attached(conn, run_id, ("worktree",)):
        data = item_data(r)
        tree = ThrowWorktree(path=r["key"], repo_path=str(data.get("repo_path") or ""), branch=str(data.get("branch") or ""))
        if r["gone_at"]:
            continue
        if not os.path.isabs(tree.path) or not os.path.isabs(tree.repo_path):
            raise Refused("The worktree %s has no repo the studio knows, so nothing was thrown away." % tree.path)
        if folder and _inside(folder, os.path.realpath(tree.path)):
            raise Refused("The worktree %s holds the run's folder, so nothing was thrown away." % tree.path)
        tree.ignored = ignored_in(tree)
        out.append(tree)
    return out


def _listed(tree):
    """False only when git answers and no longer lists the worktree (the throw then skips it)."""
    read = git.worktrees(tree.repo_path)
    return not read.ok or os.path.realpath(tree.path) in {os.path.realpath(w["path"]) for w in read.records}


def ignored_in(tree):
    """The gitignored entries in the worktree `tree` (a folder that holds only ignored files is one
    entry, `name/`); git deletes them with the worktree. [] when it is gone or git no longer lists it."""
    path = tree.path
    if not os.path.isdir(path) or not _listed(tree):
        return []
    ok, out, error = commands.run(["git", "-C", path, "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
                                   "--directory"], timeout=STEP_TIMEOUT)
    if not ok:
        raise Refused("Can't tell which ignored files git would delete with the worktree %s (%s), so nothing was "
                      "thrown away." % (path, error))
    return [p for p in out.split("\0") if p]


def _state_dirs(folder):
    found = [os.path.join(folder, "state"), os.path.join(folder, "phases", "state")]
    found += sorted(glob.glob(os.path.join(folder, "build*", "state")))
    return [d for d in found if os.path.isdir(d)]


def _session_ids(conn, run_id, folder):
    """The run's session ids: its attached session items and every `state/<TAG>.session` file."""
    ids = {r["key"] for r in _attached(conn, run_id, SESSION_KINDS)}
    for state in _state_dirs(folder) if folder else []:
        for path in glob.glob(os.path.join(state, "*.session")):
            sid = read1(path).split(" ")[0]
            if sid:
                ids.add(sid)
    return ids


def check_not_live(conn, r, folder, trees):
    """Refuse a run whose runner is alive or that has a live session (or when `claude agents` can't say)."""
    world = World()
    if folder and any(world.runner_alive(state) for state in _state_dirs(folder)):
        raise Refused("%s is still running: its runner is alive. Stop the run first; the studio never stops one."
                      % r["title"])
    read = session_reader.agents()
    if not read.ok:
        raise Refused("Can't tell whether %s has a live session (%s), so nothing was thrown away."
                      % (r["title"], read.error))
    sids = _session_ids(conn, r["id"], folder)
    places = [p for p in [folder or r["key"]] + [os.path.realpath(t.path) for t in trees] if p]
    for rec in read.records:
        mine = rec["session_id"] in sids or rec["short"] in sids or any(_inside(rec["cwd"], p) for p in places)
        if mine and rec["state"].lower() not in FINISHED:
            raise Refused("%s has a live session (%s, %s). The studio never stops a session; end it first."
                          % (r["title"], rec["name"] or rec["short"], rec["state"] or "listed"))
    now = world.now
    for s in _attached(conn, r["id"], ("session-interactive",)):
        transcript = item_data(s).get("transcript")
        try:
            changed = os.stat(transcript).st_mtime if transcript else 0
        except OSError:
            changed = 0
        if changed and now - changed < ACTIVE_SECONDS:
            raise Refused("%s has a live session (%s, active in the last 5 min). End it first." % (r["title"], s["title"]))


def _what_goes(title, folder, trees, count):
    parts = ["its folder %s goes to the Trash" % folder if folder else "its folder is no longer on this Mac"]
    if trees:
        parts.append("%d worktree%s %s removed with git worktree remove (%s; the branches stay)"
                     % (len(trees), "" if len(trees) == 1 else "s", "is" if len(trees) == 1 else "are",
                        ", ".join(t.path for t in trees)))
    for t in trees:
        if t.ignored:
            parts.append("git deletes the %d ignored file%s in %s for good, not to the Trash (%s)"
                         % (len(t.ignored), "" if len(t.ignored) == 1 else "s", t.path, _first(t.ignored)))
    parts.append("the run and its %d attached item%s leave the studio for good" % (count, "" if count == 1 else "s"))
    return "This throws away %s: %s." % (title, "; ".join(parts))


def _first(names, shown=3):
    return ", ".join(names[:shown]) + (", ..." if len(names) > shown else "")


def plan(conn, item_id):
    """What throwing the run `item_id` away removes, after every check. Changes nothing."""
    r = item_row(conn, item_id)
    if r["kind"] not in WORKSPACE_KINDS:
        raise Refused("Only a night run can be thrown away; %s is not one." % r["title"])
    folder = check_folder(r["key"])
    trees = worktrees_of(conn, r["id"], folder)
    check_not_live(conn, r, folder, trees)
    count = len(_attached(conn, r["id"]))
    return ThrowAway(item_id=r["id"], title=r["title"], folder=folder, worktrees=trees, items=count, thrown=False,
                     needs_confirm=True, message=_what_goes(r["title"], folder, trees, count))


# ---------------------------------------------------------------- doing it

def remove_worktree(tree):
    """`git worktree remove` without --force. (True, "") removed, (False, "") no longer listed, (None, error) refused."""
    read = git.worktrees(tree.repo_path)
    if not read.ok:
        return None, read.error
    if os.path.realpath(tree.path) not in {os.path.realpath(w["path"]) for w in read.records}:
        return False, ""
    ok, _, error = commands.run(["git", "-C", tree.repo_path, "worktree", "remove", tree.path], timeout=STEP_TIMEOUT)
    return (True, "") if ok else (None, error)


def trash(path):
    """Move `path` to the macOS Trash through Finder. (ok, error); ok only when it left its place."""
    argv = ["osascript"] + [arg for line in TRASH_SCRIPT for arg in ("-e", line)] + [path]
    ok, _, error = commands.run(argv, timeout=STEP_TIMEOUT)
    if ok and os.path.lexists(path):
        return False, "Finder said it did, but the folder is still there"
    return ok, error


def forget(conn, item_id, folder_key, repo_paths):
    """Mark the run and its attached items gone and purge them; drop the cache rows that list them."""
    ids = [item_id] + [a["id"] for a in _attached(conn, item_id)]
    stamp = store.now_iso()
    for iid in ids:
        conn.execute("UPDATE items SET gone_at = COALESCE(gone_at, ?) WHERE id = ?", (stamp, iid))
    for iid in ids:
        purge(conn, iid)
    conn.execute("DELETE FROM cache WHERE source = 'workspaces' OR (source = 'workspace' AND key = ?)", (folder_key,))
    for repo in sorted(set(repo_paths)):
        conn.execute("DELETE FROM cache WHERE source = 'worktrees' AND key = ?", (repo,))
    return ids


def _stopped(why, done, left):
    return "Stopped: %s. Done: %s. Not done: %s." % (why, "; ".join(done) or "nothing", "; ".join(left))


def execute(found):
    """Do what `found` (a `plan`) lists: worktrees, then the folder, then the store. Stops at the first failure."""
    done, store_step = [], "the run and its %d attached items are still in the studio" % found.items
    for i, tree in enumerate(found.worktrees):
        removed, error = remove_worktree(tree)
        if removed is None:
            left = ["worktree %s" % t.path for t in found.worktrees[i:]]
            left += ["the folder %s (not moved to the Trash)" % found.folder] if found.folder else []
            raise Refused(_stopped("git did not remove the worktree %s (%s)" % (tree.path, error), done,
                                   left + [store_step]))
        done.append(("removed worktree %s" % tree.path) if removed else ("worktree %s was already gone" % tree.path))
    if found.folder:
        ok, error = trash(found.folder)
        if not ok:
            raise Refused(_stopped("could not move %s to the Trash (%s)" % (found.folder, error), done, [store_step]))
        done.append("moved %s to the Trash" % found.folder)
    try:
        with store.write() as conn:
            key = item_row(conn, found.item_id)["key"]
            ids = forget(conn, found.item_id, key, [t.repo_path for t in found.worktrees])
    except (StudioError, sqlite3.Error) as exc:
        raise Refused(_stopped("the studio could not update its store (%s)" % exc, done,
                               [store_step + " (the next refresh marks them gone)"]))
    done.append("purged the run and %d attached item%s" % (len(ids) - 1, "" if len(ids) == 2 else "s"))
    return ThrowAway(item_id=found.item_id, title=found.title, folder=found.folder, worktrees=found.worktrees,
                     items=len(ids) - 1, thrown=True, needs_confirm=False,
                     message="Threw away %s: %s." % (found.title, "; ".join(done)), done=done)
