"""Items: reading them, filing them by hand, Undo, the Inbox's suggestions, rules and purge.

Every function takes an open connection; `sdk.api` owns the transactions. Rules kept here:
- An item has exactly one home. A move by hand sets `placed_by = manual`, bumps `revision` and
  records a `moves` row; the auto-attached items of a moved run (placed by title or cwd) follow it.
- A move can carry the revision the caller saw; a newer one refuses it. Undo is refused when the
  item (or project) moved since the move it undoes.
- Nothing is filed into an archived project, by hand or by rule.
- Purge deletes only gone items, and only when asked.
- A dismissed item (`dismissed_at` set) keeps its home, its file, session or PR; it only leaves
  home, the project view's lists, the Inbox, `status` and the counts (`find` shows it when asked).
  A dismissal and a restore are ledger rows like a move, so Undo works, and a run's auto-attached
  items go with it. A refresh never clears it: the reconcile does not touch `dismissed_at`.
- A night run marked done by hand (`done_marked_at` set) is Done, "marked done by you", while its
  files hold still: once its state files change after the mark (`data.changed_at` newer), the
  reader's word wins again and the mark counts for nothing (`marked_done`). Only night runs.

The move ledger: every undoable change records one `moves` row (`_record`) of a `store.MOVE_KINDS`
kind, and `undo` hands the row to `UNDO[kind]`. A new kind is a function that changes the item and
calls `_record(..., kind, data)`, one `UNDO` entry that puts it back, and its name in MOVE_KINDS.
"""

import json
import os
import re
import time
from collections import Counter

from . import cache, model, rules, store
from .errors import InvalidInput, NotFound, Refused
from .reconcile import AUTO_LINK, WORKSPACE_KINDS, item_data, new_item_id
from .results import (InboxEntry, Item, MoveResult, Rule, RuleAdd, RuleFiling, RulePreview, RuleSample, Run,
                      SourceState, SubProject, Suggestion)

ITEM_ID = re.compile(r"^i_[0-9a-f]{12}$")
SESSION_KEY = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PR_KEY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*$")
RUN_RANK = {"needs-you": 0, "blocked": 1, "running": 2, "paused": 3}
RULE_SAMPLE = 5         # how many matching items a rule written by pattern names


def check_item_id(value):
    if not isinstance(value, str) or not ITEM_ID.match(value):
        raise NotFound("No item with id %r." % (value,))
    return value


def row(conn, item_id):
    found = conn.execute("SELECT * FROM items WHERE id = ?", (check_item_id(item_id),)).fetchone()
    if found is None:
        raise NotFound("No item with id %r." % item_id)
    return dict(found)


def to_item(r, tree):
    data = item_data(r)
    path = tree.project(r["project_id"]).path if r["project_id"] in tree.rows else []
    return Item(id=r["id"], kind=r["kind"], key=r["key"], title=r["title"], project_id=r["project_id"],
                project_path=path, placed_by=r["placed_by"], workspace_item_id=r["workspace_item_id"],
                revision=r["revision"], status=str(data.get("status") or ""), gone=bool(r["gone_at"]),
                gone_at=r["gone_at"], seen_at=r["seen_at"], data=data, dismissed=bool(r.get("dismissed_at")),
                dismissed_at=r.get("dismissed_at"), done_marked_at=r.get("done_marked_at"))


def subtree(tree, project_id, include_archived=False):
    """`project_id` and every project under it (archived branches left out unless asked)."""
    out, todo = [], [project_id]
    while todo:
        pid = todo.pop()
        out.append(pid)
        for child in tree.children.get(pid, []):
            if include_archived or not tree.rows[child]["archived_at"]:
                todo.append(child)
    return out


def sources(conn):
    """Every reader's last state, for banners ("gh pr list failed ... PR states are from 11:42")."""
    return [SourceState(source=e.source, key=e.key, ok=e.ok, error=e.error, fetched_at=e.fetched_at,
                        good_at=e.good_at or None, partial=e.partial)
            for e in sorted(cache.entries(conn).values(), key=lambda e: (e.source, e.key))]


# ---------------------------------------------------------------- reading

def _matches(r, query):
    if not query:
        return True
    data = item_data(r)
    hay = " ".join([r["title"], r["key"]] + [str(data.get(k) or "") for k in ("name", "cwd", "branch", "git_branch", "slug")])
    return query.lower() in hay.lower()


INBOX_DAYS, recent = model.INBOX_DAYS, model.recent   # the Inbox window lives with the tree's counts


def _recency(item):
    data = item.data
    return data.get("last_active") or data.get("updated_at") or item.seen_at or ""


def find(conn, query, kind, project_id, include_gone, include_dismissed=False):
    """Matching items, newest activity first, gone ones last; dismissed ones only when asked (after the rest)."""
    tree = model.Tree(conn)
    homes = set(subtree(tree, tree.row(project_id)["id"])) if project_id else None
    out = []
    for r in conn.execute("SELECT * FROM items"):
        r = dict(r)
        if (kind and r["kind"] != kind) or (homes is not None and r["project_id"] not in homes):
            continue
        if (r["gone_at"] and not include_gone) or (r["dismissed_at"] and not include_dismissed):
            continue
        if _matches(r, query):
            out.append(to_item(r, tree))
    out.sort(key=_recency, reverse=True)
    out.sort(key=lambda i: (i.dismissed, i.gone))
    return out


def _pr_of(run_id, prs):
    mine = [p for p in prs if p.workspace_item_id == run_id]
    if not mine:
        return None
    mine.sort(key=lambda p: p.data.get("updated_at") or "", reverse=True)
    mine.sort(key=lambda p: p.data.get("state") != "open")
    p = mine[0].data
    return {"key": mine[0].key, "number": p.get("number"), "state": p.get("state"), "draft": bool(p.get("draft")),
            "url": p.get("url"), "good_at": p.get("good_at"), "checks": p.get("checks")}


MARKED_DONE = "marked done by you"     # the reason a run marked done by hand shows


def marked_done(item):
    """True while a night run's mark-done holds: it is marked and its state files have not changed
    since (a newer `changed_at` means the run moved on, so the reader's word wins again)."""
    stamp = item.done_marked_at
    return bool(stamp) and item.kind in WORKSPACE_KINDS and str(item.data.get("changed_at") or "") <= stamp


def session_ids(conn):
    """{session id: item id} of every session item not gone: what a run's conductor id points at."""
    return {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM items WHERE gone_at IS NULL AND kind IN "
                                                    "('session-bg', 'session-interactive')")}


def conductor_row(conn, run_row):
    """The session item that conducts run row `run_row` (its newest `conductor_session_id`), or None."""
    sid = item_data(run_row).get("conductor_session_id")
    if not sid:
        return None
    found = conn.execute("SELECT * FROM items WHERE gone_at IS NULL AND key = ? AND kind IN "
                         "('session-bg', 'session-interactive')", (sid,)).fetchone()
    return dict(found) if found else None


def to_run(item, prs, artifacts, sessions=None):
    """A run item as a `Run`, with its newest PR, its plan artifact and (from `sessions`, the
    `session_ids` map) its conductor's item id."""
    from .home import _progress_text, pr_text   # home imports this module
    d = item.data
    arts = sorted((a for a in artifacts if a.workspace_item_id == item.id), key=lambda a: not a.data.get("plan"))
    pr = _pr_of(item.id, prs)
    if pr is None and d.get("pr_url"):
        pr = {"key": "", "number": None, "state": "", "draft": False, "url": d["pr_url"], "good_at": None,
              "checks": None}
    status, reason = item.status or "unknown", str(d.get("reason") or "")
    if status in ("blocked", "needs-you") and pr and pr.get("state") == "merged":
        status, reason = "done", "PR merged"     # its state files froze before the merge; the merge ended it
    marked = marked_done(item) and status != "done"
    if marked:
        status, reason = "done", MARKED_DONE
    run = Run(item_id=item.id, kind=item.kind, title=item.title, project_id=item.project_id,
              status=status, reason=reason, progress=d.get("progress"),
              stage=str(d.get("stage") or ""), stages=d.get("stages") or [], pr=pr,
              artifact_url=arts[0].data.get("url", "") if arts else "", started_at=str(d.get("started_at") or ""),
              updated_at=str(d.get("updated_at") or ""), gone=item.gone, marked_done=marked,
              conductor_item_id=(sessions or {}).get(d.get("conductor_session_id") or "") or None)
    run.progress_text, run.pr_text = _progress_text(run), pr_text(pr)
    return run


def rank_runs(runs):
    """needs-you > blocked > running > paused > the rest by latest change; gone runs last."""
    runs = sorted(runs, key=lambda r: r.updated_at, reverse=True)
    return sorted(runs, key=lambda r: (r.gone, RUN_RANK.get(r.status, len(RUN_RANK))))


def status(conn, project_id):
    from .projectview import tile_state   # projectview imports this module
    tree = model.Tree(conn)
    project = tree.project(project_id)
    homes = subtree(tree, project_id)
    marks = ",".join("?" * len(homes))
    rows = [dict(r) for r in conn.execute("SELECT * FROM items WHERE project_id IN (%s) AND dismissed_at IS NULL"
                                          % marks, homes)]
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(to_item(r, tree))
    for found in by_kind.values():
        found.sort(key=_recency, reverse=True)
        found.sort(key=lambda i: i.gone)
    prs, arts = by_kind.get("pr", []), by_kind.get("artifact", [])
    every_pr = [to_item(dict(r), tree) for r in conn.execute("SELECT * FROM items WHERE kind = 'pr' AND "
                                                             "dismissed_at IS NULL")]
    known = session_ids(conn)
    runs = rank_runs([to_run(i, every_pr, arts, known) for k in WORKSPACE_KINDS for i in by_kind.get(k, [])])
    subs = []
    for child in sorted(tree.children.get(project_id, []), key=lambda c: tree.rows[c]["name"].lower()):
        if tree.rows[child]["archived_at"]:
            continue
        mine = [r for r in runs if r.project_id in set(subtree(tree, child))]
        active, top = sum(1 for r in mine if r.status in RUN_RANK), mine[0].status if mine else None
        subs.append(SubProject(project=tree.project(child), runs=len(mine), runs_active=active, top_status=top,
                               text=tile_state(len(mine), active, top)[1]))
    sessions = by_kind.get("session-bg", []) + by_kind.get("session-interactive", [])
    sessions.sort(key=_recency, reverse=True)
    sessions.sort(key=lambda i: i.gone)
    return project, runs, sessions, prs, by_kind.get("worktree", []), arts, subs, sources(conn)


def dismissed(conn, project_id):
    """The dismissed items of a project and everything under it, most recently dismissed first."""
    tree = model.Tree(conn)
    homes = subtree(tree, tree.row(project_id)["id"])
    marks = ",".join("?" * len(homes))
    found = [to_item(dict(r), tree) for r in conn.execute(
        "SELECT * FROM items WHERE project_id IN (%s) AND dismissed_at IS NOT NULL" % marks, homes)]
    return sorted(found, key=lambda i: (i.dismissed_at, i.id), reverse=True)


# ---------------------------------------------------------------- moving

def _target(tree, project_id):
    target = tree.row(project_id)
    if tree.hidden(project_id):
        raise Refused("Can't file anything into %s: it is archived." % target["name"])
    return target


def _move_row(conn, r, to_project, placed_by):
    """Re-home one row (bumping its revision) and its auto-attached children. Returns
    (new revision, ids of the children that followed)."""
    revision = r["revision"] + 1
    conn.execute("UPDATE items SET project_id = ?, placed_by = ?, revision = ? WHERE id = ?",
                 (to_project, placed_by, revision, r["id"]))
    followed = []
    if r["kind"] in WORKSPACE_KINDS:
        for child in conn.execute("SELECT id, revision FROM items WHERE workspace_item_id = ? AND placed_by IN "
                                  "(?, ?) AND project_id != ?", (r["id"],) + AUTO_LINK + (to_project,)).fetchall():
            conn.execute("UPDATE items SET project_id = ?, revision = ? WHERE id = ?",
                         (to_project, child["revision"] + 1, child["id"]))
            followed.append(child["id"])
    return revision, followed


def _record(conn, r, to_project, revision, kind="move", data=None):
    """Record a change of item row `r` (as it was before it) in the move ledger, for Undo: a `kind`
    from store.MOVE_KINDS, the revision it produced, and `data`, what its Undo needs. Returns the move id."""
    cur = conn.execute("INSERT INTO moves (item_id, from_project, from_placed_by, to_project, revision, at, kind, "
                       "data_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (r["id"], r["project_id"], r["placed_by"], to_project, revision, store.now_iso(), kind,
                        json.dumps(data or {}, sort_keys=True)))
    return cur.lastrowid


def preview(r, to_project):
    found = rules.for_signals(item_data(r).get("signals")) if to_project != store.INBOX_ID else None
    return RulePreview(signal=found[0], pattern=found[1], description=rules.describe(*found),
                       parts=rules.parts(*found)) if found else None


def moved_to(tree, project_id, back=False):
    """The toast after a move: "Moved to Project Studio", "Moved back to the top level"."""
    where = tree.rows[project_id]["name"] if project_id in tree.rows else "the top level"
    return "Moved %sto %s" % ("back " if back else "", where)


def move(conn, item_id, to_project, expected_revision, placed_by="manual"):
    """Move an item by hand. Returns a MoveResult (move_id None when it was already there)."""
    r = row(conn, item_id)
    tree = model.Tree(conn)
    _target(tree, to_project)
    if expected_revision is not None and expected_revision != r["revision"]:
        raise Refused("%s changed since you looked (revision %d, now %d). Reload and try again."
                      % (r["title"], expected_revision, r["revision"]))
    if r["project_id"] == to_project and r["placed_by"] == placed_by:
        return MoveResult(item=to_item(r, tree), project=None, move_id=None, from_project_id=r["project_id"],
                          to_project_id=to_project, rule_preview=preview(r, to_project),
                          message="Already in %s" % tree.rows[to_project]["name"])
    revision, followed = _move_row(conn, r, to_project, placed_by)
    move_id = _record(conn, r, to_project, revision)
    return MoveResult(item=to_item(row(conn, item_id), tree), project=None, move_id=move_id,
                      from_project_id=r["project_id"], to_project_id=to_project, followed=followed,
                      rule_preview=preview(r, to_project), message=moved_to(tree, to_project))


def move_project(conn, project_id, to_parent):
    """Move a project under `to_parent` (None = top level) as a MoveResult with an undoable move_id."""
    move_id = model.move_project(conn, project_id, to_parent)
    tree = model.Tree(conn)
    message = moved_to(tree, to_parent) if move_id else "Already there"
    return MoveResult(item=None, project=tree.project(project_id), move_id=move_id, from_project_id=None,
                      to_project_id=to_parent, message=message)


def _move_by_id(conn, move_id):
    if isinstance(move_id, bool) or not isinstance(move_id, int):
        raise NotFound("No move with id %r." % (move_id,))
    m = conn.execute("SELECT * FROM moves WHERE id = ?", (move_id,)).fetchone()
    if m is None:
        raise NotFound("No move with id %r." % move_id)
    return dict(m)


def _undo_project(conn, m):
    tree = model.Tree(conn)
    p = tree.row(m["project_id"])
    if p["revision"] != m["revision"]:
        raise Refused("Can't undo: %s was moved again since." % p["name"])
    if m["from_project"] is not None and m["from_project"] not in tree.rows:
        raise Refused("Can't undo: the project %s came from no longer exists." % p["name"])
    new_id = model.move_project(conn, p["id"], m["from_project"])
    tree = model.Tree(conn)
    return MoveResult(item=None, project=tree.project(p["id"]), move_id=new_id, from_project_id=m["to_project"],
                      to_project_id=m["from_project"], message=moved_to(tree, m["from_project"], back=True))


def undo(conn, move_id):
    """Put back what one ledger row did: a project's move, or an item's change by its kind (`UNDO`).
    Refused when the item or project changed since (its revision is not the one the row produced)."""
    m = _move_by_id(conn, move_id)
    if m["project_id"]:
        return _undo_project(conn, m)
    r = row(conn, m["item_id"])
    if r["revision"] != m["revision"]:
        raise Refused("Can't undo: %s was %s again since." % (r["title"], "moved" if m["kind"] == "move" else "changed"))
    if m["kind"] not in UNDO:
        raise Refused("Can't undo move %d: this Project Studio does not know a %r change." % (m["id"], m["kind"]))
    return UNDO[m["kind"]](conn, m, r)


def _undo_move(conn, m, r):
    if not m["from_project"]:
        raise Refused("Can't undo: %s had no project before this move." % r["title"])
    tree = model.Tree(conn)
    if m["from_project"] not in tree.rows:
        raise Refused("Can't undo: the project %s came from no longer exists." % r["title"])
    _target(tree, m["from_project"])
    placed_by = m["from_placed_by"] or ("inbox" if m["from_project"] == store.INBOX_ID else "manual")
    revision, followed = _move_row(conn, r, m["from_project"], placed_by)
    new_id = _record(conn, r, m["from_project"], revision)
    dropped = conn.execute("DELETE FROM rules WHERE move_id = ?", (m["id"],)).rowcount   # its "Always file" rule
    message = moved_to(tree, m["from_project"], back=True) + (". The rule was removed." if dropped else "")
    return MoveResult(item=to_item(row(conn, r["id"]), tree), project=None, move_id=new_id,
                      from_project_id=m["to_project"], to_project_id=m["from_project"], followed=followed,
                      message=message)


# ---------------------------------------------------------------- dismissing

def _attached(conn, run):
    """A run's auto-attached items (placed by title or cwd: the ones that follow its move) still shown."""
    if run["kind"] not in WORKSPACE_KINDS:
        return []
    return [dict(c) for c in conn.execute("SELECT * FROM items WHERE workspace_item_id = ? AND placed_by IN (?, ?) "
                                          "AND dismissed_at IS NULL", (run["id"],) + AUTO_LINK)]


def _rows(conn, ids):
    found = [conn.execute("SELECT * FROM items WHERE id = ?", (i,)).fetchone() for i in ids]
    return [dict(r) for r in found if r is not None]


def _ledger_data(m):
    try:
        data = json.loads(m.get("data_json") or "{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _set_dismissed(conn, r, stamp, kind, followers, message):
    """Dismiss (`stamp`) or restore (None) row `r` and `followers`, bumping each revision, and record
    it as one `kind` ledger row that names the followers, so its Undo takes them along too."""
    revision = r["revision"] + 1
    conn.execute("UPDATE items SET dismissed_at = ?, revision = ? WHERE id = ?", (stamp, revision, r["id"]))
    for child in followers:
        conn.execute("UPDATE items SET dismissed_at = ?, revision = ? WHERE id = ?",
                     (stamp, child["revision"] + 1, child["id"]))
    ids = [c["id"] for c in followers]
    move_id = _record(conn, r, r["project_id"], revision, kind, {"followed": ids})
    return MoveResult(item=to_item(row(conn, r["id"]), model.Tree(conn)), project=None, move_id=move_id,
                      from_project_id=r["project_id"], to_project_id=r["project_id"], followed=ids, message=message,
                      kind=kind)


def _unchanged(conn, r, kind, message):
    return MoveResult(item=to_item(r, model.Tree(conn)), project=None, move_id=None, from_project_id=r["project_id"],
                      to_project_id=r["project_id"], message=message, kind=kind)


def dismiss(conn, item_id):
    """Hide an item, and a run's auto-attached items with it, from every list. Deletes nothing."""
    r = row(conn, item_id)
    if r["dismissed_at"]:
        return _unchanged(conn, r, "dismiss", "%s is already dismissed" % r["title"])
    return _set_dismissed(conn, r, store.now_iso(), "dismiss", _attached(conn, r), "Dismissed %s" % r["title"])


def restore(conn, item_id):
    """Show a dismissed item again, with the attached items its newest dismissal took along."""
    r = row(conn, item_id)
    if not r["dismissed_at"]:
        return _unchanged(conn, r, "restore", "%s is not dismissed" % r["title"])
    last = conn.execute("SELECT * FROM moves WHERE item_id = ? AND kind = 'dismiss' ORDER BY id DESC LIMIT 1",
                        (r["id"],)).fetchone()
    ids = (_ledger_data(dict(last)).get("followed") or []) if last else []
    followers = [c for c in _rows(conn, ids) if c["dismissed_at"]]
    return _set_dismissed(conn, r, None, "restore", followers, "Restored %s" % r["title"])


def _undo_dismissal(conn, m, r):
    """Undo a dismiss (restore it) or a restore (dismiss it again), with the items the row names."""
    back = m["kind"] == "dismiss"
    ids = _ledger_data(m).get("followed") or []
    followers = [c for c in _rows(conn, ids) if bool(c["dismissed_at"]) == back]
    if back:
        return _set_dismissed(conn, r, None, "restore", followers, "Restored %s" % r["title"])
    return _set_dismissed(conn, r, store.now_iso(), "dismiss", followers, "Dismissed %s again" % r["title"])


# ---------------------------------------------------------------- marking a run done by hand

NOT_A_RUN = {"session-bg": "a session", "session-interactive": "a session", "pr": "a PR", "worktree": "a worktree",
             "artifact": "an artifact"}


def _set_mark(conn, r, stamp, kind, message):
    """Set (`stamp`) or clear (None) row `r`'s mark-done, bump its revision, and record it as one
    `kind` ledger row that keeps the mark it replaced, so its Undo puts that back."""
    revision = r["revision"] + 1
    conn.execute("UPDATE items SET done_marked_at = ?, revision = ? WHERE id = ?", (stamp, revision, r["id"]))
    move_id = _record(conn, r, r["project_id"], revision, kind, {"before": r["done_marked_at"]})
    return MoveResult(item=to_item(row(conn, r["id"]), model.Tree(conn)), project=None, move_id=move_id,
                      from_project_id=r["project_id"], to_project_id=r["project_id"], message=message, kind=kind)


def mark_done(conn, item_id):
    """Mark a night run done by hand, now; it holds until the run's files change after it."""
    r = row(conn, item_id)
    if r["kind"] not in WORKSPACE_KINDS:
        raise Refused("Only a night run can be marked done; %s is %s." % (r["title"], NOT_A_RUN.get(r["kind"],
                                                                                                    r["kind"])))
    item = to_item(r, model.Tree(conn))
    if marked_done(item):
        return _unchanged(conn, r, "mark-done", "%s is already marked done" % r["title"])
    if item.status == "done":
        return _unchanged(conn, r, "mark-done", "%s is already done" % r["title"])
    return _set_mark(conn, r, store.now_iso(), "mark-done", "Marked %s done" % r["title"])


def _undo_mark(conn, m, r):
    """Undo a mark-done (the reader's word again) or an unmark-done (the mark it took back)."""
    before = _ledger_data(m).get("before")
    if m["kind"] == "mark-done":
        return _set_mark(conn, r, before, "unmark-done", "%s is no longer marked done" % r["title"])
    return _set_mark(conn, r, before, "mark-done", "Marked %s done again" % r["title"])


# A ledger row's kind -> the function that puts back what it did: (conn, move row, item row) -> MoveResult.
UNDO = {"move": _undo_move, "dismiss": _undo_dismissal, "restore": _undo_dismissal, "mark-done": _undo_mark,
        "unmark-done": _undo_mark}


# ---------------------------------------------------------------- adding by hand

def _clean_key(kind, key):
    if not isinstance(key, str) or not key.strip():
        raise InvalidInput("key must be non-empty text.")
    key = key.strip()
    if kind in ("session-bg", "session-interactive"):
        if not SESSION_KEY.match(key):
            raise InvalidInput("A session key is its full session id (a UUID).")
    elif kind == "pr":
        if not PR_KEY.match(key):
            raise InvalidInput("A PR key looks like owner/repo#123.")
    elif kind == "artifact":
        if not (key.startswith("https://") or (os.path.isabs(key) and os.path.isfile(key))):
            raise InvalidInput("An artifact key is an https:// URL or the absolute path of a file.")
    else:
        path = os.path.abspath(os.path.expanduser(key)).rstrip("/") or "/"
        if not os.path.isdir(path):
            raise InvalidInput("%s is not a folder on this Mac." % key)
        key = path
    return key


def add(conn, kind, key, project_id, title):
    if kind not in store.ITEM_KINDS:
        raise InvalidInput("kind must be one of: %s." % ", ".join(store.ITEM_KINDS))
    key = _clean_key(kind, key)
    if title is not None and (not isinstance(title, str) or len(title) > 300):
        raise InvalidInput("title must be text of at most 300 characters.")
    kinds = store.SESSION_KINDS if kind in store.SESSION_KINDS else (kind,)   # one session, either kind
    existing = conn.execute("SELECT id FROM items WHERE kind IN (%s) AND key = ?" % ", ".join("?" * len(kinds)),
                            kinds + (key,)).fetchone()
    if existing:
        return move(conn, existing["id"], project_id, None)
    tree = model.Tree(conn)
    _target(tree, project_id)
    item_id = new_item_id()
    title = (title or "").strip() or os.path.basename(key.rstrip("/")) or key
    signals = {"workspace": os.path.basename(key) if kind in WORKSPACE_KINDS else "", "repo": "", "branch": "",
               "cwd": key if kind in WORKSPACE_KINDS + ("worktree",) else ""}
    conn.execute("INSERT INTO items (id, kind, key, title, project_id, placed_by, workspace_item_id, revision, "
                 "data_json, seen_at, gone_at) VALUES (?, ?, ?, ?, ?, 'manual', NULL, 1, ?, ?, NULL)",
                 (item_id, kind, key, title, project_id,
                  json.dumps({"added_by_hand": True, "status": "unknown", "signals": signals}), store.now_iso()))
    return MoveResult(item=to_item(row(conn, item_id), tree), project=None, move_id=None, from_project_id=None,
                      to_project_id=project_id, created=True)


# ---------------------------------------------------------------- the Inbox

def suggest(conn, r, tree, filed):
    """Where an Inbox item probably belongs, and why, or None."""
    data = item_data(r)
    signals = data.get("signals") or {}
    if r["workspace_item_id"]:
        run = conn.execute("SELECT title, project_id FROM items WHERE id = ?", (r["workspace_item_id"],)).fetchone()
        if run and run["project_id"] != store.INBOX_ID and not tree.hidden(run["project_id"]):
            return Suggestion(run["project_id"], tree.rows[run["project_id"]]["name"], "same run as %s" % run["title"])
    rule = rules.match(rules.load(conn), signals, tree)
    if rule is not None:
        return Suggestion(rule["project_id"], tree.rows[rule["project_id"]]["name"],
                          "rule: " + rules.describe(rule["signal"], rule["pattern"]))
    repo = signals.get("repo")
    homes = Counter(pid for pid, other in filed if repo and other == repo)
    if homes:
        pid, count = homes.most_common(1)[0]
        return Suggestion(pid, tree.rows[pid]["name"], "repo %s: %d item%s there" % (repo, count, "" if count == 1 else "s"))
    return None


def inbox(conn, now=None):
    """Every unfiled item active in the last INBOX_DAYS days, newest first, with its suggestion."""
    now = time.time() if now is None else now
    tree = model.Tree(conn)
    filed = []
    for r in conn.execute("SELECT project_id, data_json FROM items WHERE project_id != ? AND gone_at IS NULL "
                          "AND dismissed_at IS NULL", (store.INBOX_ID,)):
        if not tree.hidden(r["project_id"]):
            filed.append((r["project_id"], (item_data(r).get("signals") or {}).get("repo")))
    rows = [dict(r) for r in conn.execute("SELECT * FROM items WHERE project_id = ? AND gone_at IS NULL AND "
                                          "dismissed_at IS NULL", (store.INBOX_ID,)) if recent(r, now)]
    entries = [InboxEntry(item=to_item(r, tree), suggestion=suggest(conn, r, tree, filed)) for r in rows]
    entries.sort(key=lambda e: _recency(e.item), reverse=True)
    return entries


def accept(conn, item_id):
    r = row(conn, item_id)
    if r["project_id"] != store.INBOX_ID:
        raise Refused("%s is not in the Inbox." % r["title"])
    entry = next((e for e in inbox(conn) if e.item.id == item_id), None)
    if entry is None or entry.suggestion is None:
        raise Refused("There is no suggestion for %s. Move it by hand." % r["title"])
    return move(conn, item_id, entry.suggestion.project_id, None)


# ---------------------------------------------------------------- rules

def to_rule(r, tree, created=False):
    return Rule(id=r["id"], project_id=r["project_id"], project_name=tree.rows[r["project_id"]]["name"],
                signal=r["signal"], pattern=r["pattern"], description=rules.describe(r["signal"], r["pattern"]),
                created_at=r["created_at"], created=created, parts=rules.parts(r["signal"], r["pattern"]))


def save_rule(conn, move_id):
    m = _move_by_id(conn, move_id)
    if m["project_id"]:
        raise Refused("A rule learns from an item's move, not a project's.")
    if m["kind"] != "move":
        raise Refused("A rule learns from a move into a project, not a %s." % m["kind"])
    r = row(conn, m["item_id"])
    tree = model.Tree(conn)
    if m["to_project"] == store.INBOX_ID:
        raise Refused("A rule can't file items into the Inbox.")
    _target(tree, m["to_project"])
    found = rules.for_signals(item_data(r).get("signals"))
    if found is None:
        raise Refused("Nothing about %s to learn a rule from." % r["title"])
    same = conn.execute("SELECT * FROM rules WHERE project_id = ? AND signal = ? AND pattern = ?",
                        (m["to_project"],) + found).fetchone()
    if same:
        return to_rule(dict(same), tree)
    rule = {"id": rules.new_rule_id(), "project_id": m["to_project"], "signal": found[0], "pattern": found[1],
            "created_at": store.now_iso()}
    conn.execute("INSERT INTO rules (id, project_id, signal, pattern, created_at, move_id) VALUES (?, ?, ?, ?, ?, ?)",
                 (rule["id"], rule["project_id"], rule["signal"], rule["pattern"], rule["created_at"], m["id"]))
    return to_rule(rule, tree, created=True)


def would_file(conn, tree, rule):
    """The Inbox items `rule` would file now, newest first: ones a refresh may still file (placed_by
    "inbox": not put there by hand, not following a run), not gone or dismissed, whose signals meet
    this rule before any other (`rules.match` over every rule, this one ranked among them)."""
    loaded = rules.load(conn)
    ranked = loaded if any(r["id"] == rule["id"] for r in loaded) else rules.rank(loaded + [rule])
    rows = [dict(r) for r in conn.execute("SELECT * FROM items WHERE project_id = ? AND placed_by = ? AND "
                                          "gone_at IS NULL AND dismissed_at IS NULL", (store.INBOX_ID, "inbox"))]
    found = [to_item(r, tree) for r in rows
             if (rules.match(ranked, item_data(r).get("signals"), tree) or {}).get("id") == rule["id"]]
    found.sort(key=_recency, reverse=True)
    return found


def add_rule(conn, project_id, signal, pattern, apply, dry_run):
    """A rule written by pattern (`rules.check`) into `project_id`, with the Inbox items it files now.
    A dry run saves and files nothing. With `apply`, each of those items is filed through `move`
    (one undoable move id each); items filed elsewhere are never touched."""
    signal, pattern = rules.check(signal, pattern)
    tree = model.Tree(conn)
    target = _target(tree, project_id)
    if project_id == store.INBOX_ID:
        raise Refused("A rule can't file items into the Inbox.")
    same = conn.execute("SELECT * FROM rules WHERE project_id = ? AND signal = ? AND pattern = ?",
                        (project_id, signal, pattern)).fetchone()
    rule = dict(same) if same else {"id": rules.new_rule_id(), "project_id": project_id, "signal": signal,
                                    "pattern": pattern, "created_at": store.now_iso()}
    found = would_file(conn, tree, rule)
    result = RuleAdd(preview=RulePreview(signal=signal, pattern=pattern, description=rules.describe(signal, pattern),
                                         parts=rules.parts(signal, pattern)),
                     project_id=project_id, project_name=target["name"], rule=None, dry_run=dry_run, created=False,
                     matching=len(found), sample=[RuleSample(i.id, i.title, i.kind) for i in found[:RULE_SAMPLE]])
    if not dry_run:
        if same is None:
            conn.execute("INSERT INTO rules (id, project_id, signal, pattern, created_at, move_id) "
                         "VALUES (?, ?, ?, ?, ?, NULL)",
                         (rule["id"], project_id, signal, pattern, rule["created_at"]))
        result.rule, result.created = to_rule(rule, tree, created=same is None), same is None
        if apply:
            for item in found:
                moved = move(conn, item.id, project_id, None)
                result.filed.append(RuleFiling(item.id, item.title, moved.move_id, moved.followed))
    result.message = _rule_words(result)
    return result


def _rule_words(result):
    """add_rule's message: what was saved, and what it files now or would file."""
    rule = "%s -> %s" % (result.preview.description, result.project_name)
    count = "%d Inbox item%s" % (result.matching, "" if result.matching == 1 else "s")
    names = ", ".join(s.title for s in result.sample) + (", ..." if result.matching > len(result.sample) else "")
    if result.dry_run:
        if not result.matching:
            return "Nothing saved. The rule %s matches no Inbox item now; new items would follow it." % rule
        return "Nothing saved. The rule %s would file %s now: %s." % (rule, count, names)
    head = ("Saved rule %s." if result.created else "Already saved: rule %s.") % rule
    if result.filed:
        return "%s Filed %s there, one move each: %s." % (head, count, names)
    if result.matching:
        return "%s It matches %s now: %s. Add it again with apply to file them now, each undoable." % (head, count, names)
    return "%s No Inbox item matches it now; new items will follow it." % head


def list_rules(conn, project_id):
    tree = model.Tree(conn)
    if project_id is not None:
        tree.row(project_id)
    return [to_rule(r, tree) for r in rules.load(conn) if project_id is None or r["project_id"] == project_id]


def delete_rule(conn, rule_id):
    if not isinstance(rule_id, str) or not rules.RULE_ID.match(rule_id):
        raise NotFound("No rule with id %r." % (rule_id,))
    r = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
    if r is None:
        raise NotFound("No rule with id %r." % rule_id)
    rule = to_rule(dict(r), model.Tree(conn))
    conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    return rule


# ---------------------------------------------------------------- purge

def purge(conn, item_id):
    if item_id is not None:
        r = row(conn, item_id)
        if not r["gone_at"]:
            raise Refused("%s is not gone, so it can't be purged." % r["title"])
        ids = [item_id]
    else:
        ids = [r["id"] for r in conn.execute("SELECT id FROM items WHERE gone_at IS NOT NULL ORDER BY id")]
    for iid in ids:
        conn.execute("UPDATE items SET workspace_item_id = NULL WHERE workspace_item_id = ?", (iid,))
        conn.execute("DELETE FROM moves WHERE item_id = ?", (iid,))
        conn.execute("DELETE FROM items WHERE id = ?", (iid,))
    return ids
