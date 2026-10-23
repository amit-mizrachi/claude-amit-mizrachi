"""Items: reading them, filing them by hand, Undo, the Inbox's suggestions, rules and purge.

Every function takes an open connection; `sdk.api` owns the transactions. Rules kept here:
- An item has exactly one home. A move by hand sets `placed_by = manual`, bumps `revision` and
  records a `moves` row; the auto-attached items of a moved run (placed by title or cwd) follow it.
- A move can carry the revision the caller saw; a newer one refuses it. Undo is refused when the
  item moved since the move it undoes.
- Nothing is filed into an archived project, by hand or by rule.
- Purge deletes only gone items, and only when asked.
"""

import json
import os
import re
from collections import Counter

from . import cache, model, rules, store
from .errors import InvalidInput, NotFound, Refused
from .reconcile import AUTO_LINK, WORKSPACE_KINDS, item_data, new_item_id
from .results import (InboxEntry, Item, MoveResult, Rule, RulePreview, Run, SourceState,
                      SubProject, Suggestion)

ITEM_ID = re.compile(r"^i_[0-9a-f]{12}$")
SESSION_KEY = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PR_KEY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*$")
RUN_RANK = {"needs-you": 0, "blocked": 1, "running": 2, "paused": 3}


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
                gone_at=r["gone_at"], seen_at=r["seen_at"], data=data)


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


def _recency(item):
    data = item.data
    return data.get("last_active") or data.get("updated_at") or item.seen_at or ""


def find(conn, query, kind, project_id, include_gone):
    tree = model.Tree(conn)
    homes = set(subtree(tree, tree.row(project_id)["id"])) if project_id else None
    out = []
    for r in conn.execute("SELECT * FROM items"):
        r = dict(r)
        if (kind and r["kind"] != kind) or (homes is not None and r["project_id"] not in homes):
            continue
        if (r["gone_at"] and not include_gone) or not _matches(r, query):
            continue
        out.append(to_item(r, tree))
    out.sort(key=_recency, reverse=True)
    out.sort(key=lambda i: i.gone)
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


def to_run(item, prs, artifacts):
    """A run item as a `Run`, with its newest PR and its plan artifact."""
    d = item.data
    arts = sorted((a for a in artifacts if a.workspace_item_id == item.id), key=lambda a: not a.data.get("plan"))
    pr = _pr_of(item.id, prs)
    if pr is None and d.get("pr_url"):
        pr = {"key": "", "number": None, "state": "", "draft": False, "url": d["pr_url"], "good_at": None,
              "checks": None}
    return Run(item_id=item.id, kind=item.kind, title=item.title, project_id=item.project_id,
               status=item.status or "unknown", reason=str(d.get("reason") or ""), progress=d.get("progress"),
               stage=str(d.get("stage") or ""), stages=d.get("stages") or [], pr=pr,
               artifact_url=arts[0].data.get("url", "") if arts else "", started_at=str(d.get("started_at") or ""),
               updated_at=str(d.get("updated_at") or ""), gone=item.gone)


def rank_runs(runs):
    """needs-you > blocked > running > paused > the rest by latest change; gone runs last."""
    runs = sorted(runs, key=lambda r: r.updated_at, reverse=True)
    return sorted(runs, key=lambda r: (r.gone, RUN_RANK.get(r.status, len(RUN_RANK))))


def status(conn, project_id):
    tree = model.Tree(conn)
    project = tree.project(project_id)
    homes = subtree(tree, project_id)
    marks = ",".join("?" * len(homes))
    rows = [dict(r) for r in conn.execute("SELECT * FROM items WHERE project_id IN (%s)" % marks, homes)]
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(to_item(r, tree))
    for found in by_kind.values():
        found.sort(key=_recency, reverse=True)
        found.sort(key=lambda i: i.gone)
    prs, arts = by_kind.get("pr", []), by_kind.get("artifact", [])
    every_pr = [to_item(dict(r), tree) for r in conn.execute("SELECT * FROM items WHERE kind = 'pr'")]
    runs = rank_runs([to_run(i, every_pr, arts) for k in WORKSPACE_KINDS for i in by_kind.get(k, [])])
    subs = []
    for child in sorted(tree.children.get(project_id, []), key=lambda c: tree.rows[c]["name"].lower()):
        if tree.rows[child]["archived_at"]:
            continue
        mine = [r for r in runs if r.project_id in set(subtree(tree, child))]
        subs.append(SubProject(project=tree.project(child), runs=len(mine),
                               runs_active=sum(1 for r in mine if r.status in RUN_RANK),
                               top_status=mine[0].status if mine else None))
    sessions = by_kind.get("session-bg", []) + by_kind.get("session-interactive", [])
    sessions.sort(key=_recency, reverse=True)
    sessions.sort(key=lambda i: i.gone)
    return project, runs, sessions, prs, by_kind.get("worktree", []), arts, subs, sources(conn)


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


def _record(conn, item_id, from_project, to_project, revision):
    cur = conn.execute("INSERT INTO moves (item_id, from_project, to_project, revision, at) VALUES (?, ?, ?, ?, ?)",
                       (item_id, from_project, to_project, revision, store.now_iso()))
    return cur.lastrowid


def preview(r, to_project):
    found = rules.for_signals(item_data(r).get("signals")) if to_project != store.INBOX_ID else None
    return RulePreview(signal=found[0], pattern=found[1], description=rules.describe(*found)) if found else None


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
                          to_project_id=to_project, rule_preview=preview(r, to_project))
    revision, followed = _move_row(conn, r, to_project, placed_by)
    move_id = _record(conn, item_id, r["project_id"], to_project, revision)
    return MoveResult(item=to_item(row(conn, item_id), tree), project=None, move_id=move_id,
                      from_project_id=r["project_id"], to_project_id=to_project, followed=followed,
                      rule_preview=preview(r, to_project))


def _move_by_id(conn, move_id):
    if isinstance(move_id, bool) or not isinstance(move_id, int):
        raise NotFound("No move with id %r." % (move_id,))
    m = conn.execute("SELECT * FROM moves WHERE id = ?", (move_id,)).fetchone()
    if m is None:
        raise NotFound("No move with id %r." % move_id)
    return dict(m)


def undo(conn, move_id):
    m = _move_by_id(conn, move_id)
    r = row(conn, m["item_id"])
    if r["revision"] != m["revision"]:
        raise Refused("Can't undo: %s was moved again since." % r["title"])
    if not m["from_project"]:
        raise Refused("Can't undo: %s had no project before this move." % r["title"])
    tree = model.Tree(conn)
    if m["from_project"] not in tree.rows:
        raise Refused("Can't undo: the project %s came from no longer exists." % r["title"])
    _target(tree, m["from_project"])
    placed_by = "inbox" if m["from_project"] == store.INBOX_ID else "manual"
    revision, followed = _move_row(conn, r, m["from_project"], placed_by)
    new_id = _record(conn, r["id"], m["to_project"], m["from_project"], revision)
    return MoveResult(item=to_item(row(conn, r["id"]), tree), project=None, move_id=new_id,
                      from_project_id=m["to_project"], to_project_id=m["from_project"], followed=followed)


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
    existing = conn.execute("SELECT id FROM items WHERE kind = ? AND key = ?", (kind, key)).fetchone()
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


def inbox(conn):
    tree = model.Tree(conn)
    filed = []
    for r in conn.execute("SELECT project_id, data_json FROM items WHERE project_id != ? AND gone_at IS NULL",
                          (store.INBOX_ID,)):
        if not tree.hidden(r["project_id"]):
            filed.append((r["project_id"], (item_data(r).get("signals") or {}).get("repo")))
    rows = [dict(r) for r in conn.execute("SELECT * FROM items WHERE project_id = ? AND gone_at IS NULL",
                                          (store.INBOX_ID,))]
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
                created_at=r["created_at"], created=created)


def save_rule(conn, move_id):
    m = _move_by_id(conn, move_id)
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
    conn.execute("INSERT INTO rules (id, project_id, signal, pattern, created_at) VALUES (?, ?, ?, ?, ?)",
                 (rule["id"], rule["project_id"], rule["signal"], rule["pattern"], rule["created_at"]))
    return to_rule(rule, tree, created=True)


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
