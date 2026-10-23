"""Refresh: run the readers whose cache rows are due, store what they said, then reconcile.

TTLs live in `sdk.cache.TTL`. Due sources are read OUTSIDE any transaction (a `gh` call takes a
second; the store must not be locked for it), then one BEGIN IMMEDIATE stores every read and
runs the reconcile over the whole cache, so all processes see one consistent result.

Repos come from the runs: each workspace's `REPO_PATH` gets a `git worktree list`, each
`REPO_SLUG` one `gh pr list` (open and closed) per TTL.
"""

import os
import time

from . import cache, store
from .inventory import Inventory
from .readers import git, runs, sessions
from .reconcile import WORKSPACE_KINDS, item_data, reconcile


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


def run_reads(entries, folders, repo_paths, now, force):
    """Read every due source. Returns [(source, key, Read)]."""
    plan = Plan(entries, now, force)
    done = []
    if plan.due("workspaces", "discover"):
        read = runs.discover(extra=folders)
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
        done.append((source, key, fn()))
    return done


def refresh(force=False):
    """Read what is due (everything when `force`), store it, reconcile. Returns
    (reads made as [(source, key, ok)], reconcile counts, every cache entry after)."""
    now = time.time()
    with store.read() as conn:
        entries = cache.entries(conn)
        folders, repo_paths = _known(conn)
    done = run_reads(entries, folders, repo_paths, now, force)
    if not done:
        return [], {"added": 0, "filed": 0, "gone": 0, "back": 0}, entries
    with store.write() as conn:
        before = cache.entries(conn)
        for source, key, read in done:
            cache.put(conn, source, key, read, before.get((source, key)))
        after = cache.entries(conn)
        counts = reconcile(conn, Inventory(after, now))
    return [(s, k, r.ok) for s, k, r in done], counts, after
