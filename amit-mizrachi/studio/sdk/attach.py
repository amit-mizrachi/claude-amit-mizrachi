"""Attach one starting session (the SessionStart hook) by the reconcile's own rules, without a scan.

The hook runs at every session start, so this reads nothing live: no `claude agents`, no git
call, no `gh`. It files the session from what the store already holds - the runs the last scan
found (their slugs, `state/<TAG>.session` ids, worktrees) and the attach rules - through the
reconcile's `Placer`: title (`ns-<slug>-<TAG>`) > cwd/worktree > rule > Inbox. A run the store
has not seen yet leaves the session in the Inbox, and the next scan files it from there.

The row carries no `scope`, so a scan that read before the session wrote its transcript can not
mark it gone. The first scan that finds the session writes its full data, scope included.
A session the store already knows (a resume, a compact) is left where it is.
"""

import json
import os

from . import items, model, store
from .inventory import Joins, session_title
from .readers.git import repo_of_path
from .readers.sessions import job_state
from .reconcile import WORKSPACE_KINDS, Placer, item_data, new_item_id

SESSION_KINDS = ("session-bg", "session-interactive")
HEADLESS_PREFIX = "sdk"           # CLAUDE_CODE_ENTRYPOINT of `claude -p` and SDK runs: never items


def headless(entrypoint):
    """True for a `claude -p` / SDK run, which never becomes an item."""
    return bool(entrypoint) and entrypoint.startswith(HEADLESS_PREFIX)


def _placer(conn):
    """The reconcile's Placer, plus Joins over the runs the store holds (no reader runs)."""
    placer = Placer(conn)
    runs = [dict(r) for r in conn.execute("SELECT * FROM items WHERE kind IN (?, ?) AND gone_at IS NULL",
                                          WORKSPACE_KINDS)]
    for run in runs:
        placer.runs[run["key"]] = run
    return placer, Joins([dict(item_data(run), path=run["key"]) for run in runs])


def _link(joins, session_id, short, name, cwd):
    link = joins.by_session(session_id, short, name)
    if link is None:
        ws = joins.by_path(cwd)
        link = (ws, "cwd") if ws else None
    return link


def attach(conn, session_id, cwd, job_dir):
    """File a starting session. Returns (Item, created)."""
    known = conn.execute("SELECT * FROM items WHERE kind IN (?, ?) AND key = ?",
                         SESSION_KINDS + (session_id,)).fetchone()
    if known is not None:
        return items.to_item(dict(known), model.Tree(conn)), False
    job = (job_state(job_dir) if job_dir else None) or {}
    name, short = job.get("name", ""), job.get("short") or session_id[:8]
    placer, joins = _placer(conn)
    link = _link(joins, session_id, short, name, cwd)
    signals = {"workspace": os.path.basename(link[0]) if link else "", "repo": repo_of_path(cwd).get("repo", ""),
               "branch": "", "cwd": cwd}
    target, rung, wsid = placer.place(link, signals)
    stamp = store.now_iso()
    data = {
        "session_id": session_id, "short": short, "name": name, "cwd": cwd, "git_branch": "",
        "status": "starting", "listed": False, "activity": "", "waiting_for": "", "detail": "",
        "started_at": stamp, "last_active": stamp, "transcript": "", "recently_active": True,
        "attached_by": "session-start", "signals": signals,
    }
    item_id, kind = new_item_id(), "session-bg" if job_dir else "session-interactive"
    conn.execute("INSERT INTO items (id, kind, key, title, project_id, placed_by, workspace_item_id, revision, "
                 "data_json, seen_at, gone_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)",
                 (item_id, kind, session_id, session_title(name, cwd, short)[:300], target, rung, wsid,
                  json.dumps(data, sort_keys=True), stamp))
    return items.to_item(items.row(conn, item_id), placer.tree), True
