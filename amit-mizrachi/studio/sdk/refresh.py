"""Refresh: run the readers whose cache rows are due, store what they said, then reconcile.

TTLs live in `sdk.cache.TTL`. Due sources are read OUTSIDE any transaction (a `gh` call takes a
second; the store must not be locked for it), then one BEGIN IMMEDIATE stores every read and
runs the reconcile over the whole cache, so all processes see one consistent result.

Fast sources land first. The slow ones (`SLOW`: a `gh pr list` can take a minute) are read after,
each stored and reconciled as it lands, so the home page never waits for them. While a slow
source, or a source with nothing stored yet, is being read, `reading()` names it.

Repos come from the runs: each workspace's `REPO_PATH` gets a `git worktree list`, each
`REPO_SLUG` one `gh pr list` (open and closed) per TTL.
"""

import os
import threading
import time

from . import cache, store
from .inventory import Inventory
from .readers import git, runs, sessions
from .reconcile import WORKSPACE_KINDS, item_data, reconcile

NO_CHANGES = {"added": 0, "filed": 0, "gone": 0, "back": 0}
SLOW = ("prs",)

_lock = threading.Lock()
_in_flight = {}


def _mark(keys):
    with _lock:
        for key in keys:
            _in_flight[key] = _in_flight.get(key, 0) + 1


def _unmark(keys):
    with _lock:
        for key in keys:
            _in_flight[key] -= 1
            if not _in_flight[key]:
                del _in_flight[key]


def reading():
    """The sources this process is reading now that the page should name: a slow one, or one with
    nothing stored yet. Sorted source names, [] when idle."""
    with _lock:
        return sorted({source for source, _ in _in_flight})


def _read(entries, source, key, fn):
    """Run one read, named by `reading()` while it runs when it is slow or the first of its row."""
    flag = [(source, key)] if source in SLOW or (source, key) not in entries else []
    _mark(flag)
    try:
        return fn()
    finally:
        _unmark(flag)


class Plan(object):
    """The reads one refresh makes, as (source, key, callable) in order."""

    def __init__(self, entries, now, force):
        self.entries, self.now, self.force = entries, now, force
        self.reads = []

    def due(self, source, key):
        entry = self.entries.get((source, key))
        return self.force or entry is None or entry.due(self.now)

    def add(self, source, key, fn):
        if self.due(source, key):
            self.reads.append((source, key, fn))


def _known(conn):
    """Workspace folders and repo paths the store already holds (hand-added ones included)."""
    folders, repos = [], set()
    for row in conn.execute("SELECT kind, key, data_json FROM items WHERE kind IN ('night-sprint', "
                            "'night-marathon', 'worktree') AND gone_at IS NULL"):
        if row["kind"] in WORKSPACE_KINDS:
            folders.append(row["key"])
        elif item_data(row).get("repo_path"):
            repos.add(item_data(row)["repo_path"])
    return folders, repos


def _repos(workspaces, repo_paths):
    paths, slugs = set(repo_paths), set()
    for ws in workspaces:
        if ws.get("repo_path"):
            paths.add(ws["repo_path"])
        slugs.update(s for s in ws.get("repo_slugs", []) + [ws.get("repo_slug", "")] if s)
    return sorted(p for p in paths if os.path.isdir(p)), sorted(slugs)


def _one_workspace(path):
    rec = runs.read_workspace(path, runs.World())
    return git.Read(True, [rec] if rec else [])


def run_reads(entries, folders, repo_paths, now, force, slow=True):
    """Read every due fast source. Returns ([(source, key, Read)] made, [(source, key, callable)] of
    the due slow sources, still to read; [] when `slow` is False)."""
    plan = Plan(entries, now, force)
    done = []
    if plan.due("workspaces", "discover"):
        read = _read(entries, "workspaces", "discover", lambda: runs.discover(extra=folders))
        done.append(("workspaces", "discover", read))
        workspaces = read.records if read.ok else Inventory(entries, now).workspaces
    else:
        workspaces = Inventory(entries, now).workspaces
        for ws in workspaces:
            if ws.get("status") != "done":                       # live runs only, every 2 s
                plan.add("workspace", ws["path"], lambda p=ws["path"]: _one_workspace(p))
    previous = entries.get(("transcripts", "all"))
    plan.add("agents", "all", sessions.agents)
    plan.add("jobs", "all", sessions.jobs)
    plan.add("transcripts", "all", lambda: sessions.transcripts(previous.data if previous else None, now))
    paths, slugs = _repos(workspaces, repo_paths)
    for path in paths:
        plan.add("worktrees", path, lambda p=path: git.worktrees(p))
    for slug in slugs:
        plan.add("prs", slug, lambda s=slug: git.prs(s))
    for source, key, fn in plan.reads:
        if source not in SLOW:
            done.append((source, key, _read(entries, source, key, fn)))
    return done, [r for r in plan.reads if r[0] in SLOW] if slow else []


def _store(reads):
    """Store reads in one transaction and reconcile. Returns (every cache entry after, counts)."""
    with store.write() as conn:
        before = cache.entries(conn)
        for source, key, read in reads:
            cache.put(conn, source, key, read, before.get((source, key)))
        after = cache.entries(conn)
        return after, reconcile(conn, Inventory(after, time.time()))


def _slow(entries, pending):
    """Read and store each slow source as it lands; each is named by `reading()` until stored."""
    keys = [(source, key) for source, key, _ in pending]
    _mark(keys)
    made, counts, after = [], dict(NO_CHANGES), entries
    try:
        for source, key, fn in pending:
            read = fn()
            after, more = _store([(source, key, read)])
            _unmark([(source, key)])
            keys.remove((source, key))
            made.append((source, key, read))
            counts = {name: counts[name] + more.get(name, 0) for name in counts}
    finally:
        _unmark(keys)
    return made, counts, after


def refresh(force=False, strict=True, slow=True):
    """Read what is due (everything when `force`), store it, reconcile. Returns
    (reads made as [(source, key, ok)], reconcile counts, every cache entry after).

    The fast sources are stored and reconciled first, then each slow one as it lands. With `slow`
    False the slow sources are not read at all (a caller that must not wait for `gh`).

    A store written by a newer SDK is read-only: `strict` raises `ReadOnlyStore` before any read,
    otherwise nothing is read and the current entries come back, so a read that refreshes first
    still returns the stored data."""
    now = time.time()
    with store.read() as conn:
        version = store.version_of(conn)
        entries = cache.entries(conn)
        folders, repo_paths = _known(conn)
    if version > store.SCHEMA_VERSION:
        if strict:
            raise store.read_only_error(version)
        return [], dict(NO_CHANGES), entries
    done, pending = run_reads(entries, folders, repo_paths, now, force, slow)
    counts, after = dict(NO_CHANGES), entries
    if done:
        after, counts = _store(done)
    if pending:
        late, more, after = _slow(after, pending)
        done += late
        counts = {name: counts[name] + more.get(name, 0) for name in counts}
    return [(s, k, r.ok) for s, k, r in done], counts, after
