"""The project tree: projects, their one parent, links, and the rules that keep the tree sound.

Every function takes an open connection from `store.read()` / `store.write()`; `sdk.api` owns
the transactions. Rules kept here:
- A project has at most one parent, and the tree has no cycles.
- Sibling names are unique among active projects, ignoring case.
- The Inbox (`store.INBOX_ID`) is top-level for ever: it can't be moved, archived, deleted,
  linked, or hold sub-projects.
- Only an empty project (no sub-projects, no items) can be deleted; otherwise archive it.
- An archived project, and everything under it, is hidden from lists unless asked for.
"""

import json
import re
import uuid

from . import store
from .errors import InvalidInput, NotFound, Refused
from .results import Project

PROJECT_ID = re.compile(r"^(inbox|p_[0-9a-f]{12})$")
MAX_NAME = 120


def new_project_id():
    return "p_" + uuid.uuid4().hex[:12]


def clean_name(name):
    """The name with outer spaces removed, or InvalidInput when it is empty, too long or has control characters."""
    if not isinstance(name, str):
        raise InvalidInput("A project name must be text.")
    name = name.strip()
    if not name:
        raise InvalidInput("A project name can't be empty.")
    if len(name) > MAX_NAME:
        raise InvalidInput("A project name can be at most %d characters." % MAX_NAME)
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise InvalidInput("A project name can't hold control characters.")
    return name


def check_id(value):
    """The id when it has a project id's shape; NotFound otherwise (no lookup by a malformed id)."""
    if not isinstance(value, str) or not PROJECT_ID.match(value):
        raise NotFound("No project with id %r." % (value,))
    return value


# ---------------------------------------------------------------- reading the tree

class Tree(object):
    """Every project row, the counts and links, read once per call."""

    def __init__(self, conn):
        self.rows = {r["id"]: r for r in conn.execute(
            "SELECT id, name, parent_id, archived_at, revision, created_at, updated_at FROM projects")}
        self.children = {}
        for row in self.rows.values():
            self.children.setdefault(row["parent_id"], []).append(row["id"])
        self.items = {r[0]: r[1] for r in conn.execute("SELECT project_id, COUNT(*) FROM items GROUP BY project_id")}
        self.links = {}
        for a, b in conn.execute("SELECT a_id, b_id FROM links"):
            self.links.setdefault(a, []).append(b)
            self.links.setdefault(b, []).append(a)

    def row(self, project_id):
        check_id(project_id)
        row = self.rows.get(project_id)
        if row is None:
            raise NotFound("No project with id %r." % project_id)
        return row

    def ancestors(self, project_id):
        """Ids from the parent of `project_id` up to the top level."""
        out, cur = [], self.rows[project_id]["parent_id"]
        while cur is not None and cur not in out:
            out.append(cur)
            cur = self.rows[cur]["parent_id"]
        return out

    def hidden(self, project_id):
        """Archived itself, or under an archived project."""
        return any(self.rows[p]["archived_at"] for p in [project_id] + self.ancestors(project_id))

    def project(self, project_id):
        row = self.row(project_id)
        names = [self.rows[p]["name"] for p in reversed(self.ancestors(project_id))] + [row["name"]]
        return Project(
            id=row["id"], name=row["name"], parent_id=row["parent_id"], path=names,
            is_inbox=row["id"] == store.INBOX_ID, archived_at=row["archived_at"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            child_count=len(self.children.get(row["id"], [])), item_count=self.items.get(row["id"], 0),
            linked_ids=sorted(self.links.get(row["id"], [])))

    def sibling_named(self, parent_id, name, skip=None):
        for pid in self.children.get(parent_id, []):
            row = self.rows[pid]
            if pid != skip and not row["archived_at"] and row["name"].lower() == name.lower():
                return row
        return None


def order_key(project):
    return (not project.is_inbox, [n.lower() for n in project.path], project.id)


def list_projects(conn, parent_id, top_level, include_archived):
    tree = Tree(conn)
    if parent_id is not None:
        tree.row(parent_id)
    out = []
    for pid, row in tree.rows.items():
        if parent_id is not None and row["parent_id"] != parent_id:
            continue
        if top_level and row["parent_id"] is not None:
            continue
        if not include_archived and tree.hidden(pid):
            continue
        out.append(tree.project(pid))
    return sorted(out, key=order_key)


# ---------------------------------------------------------------- changing the tree

def _parent_ok(tree, parent_id, name):
    """Refuse a parent that is the Inbox or archived, or that already has an active child `name`."""
    if parent_id is None:
        return
    parent = tree.row(parent_id)
    if parent_id == store.INBOX_ID:
        raise Refused("The Inbox can't hold sub-projects.")
    if tree.hidden(parent_id):
        raise Refused("Can't put %s inside %s: %s is archived." % (name, parent["name"], parent["name"]))


def create_project(conn, name, parent_id):
    name = clean_name(name)
    tree = Tree(conn)
    _parent_ok(tree, parent_id, name)
    if tree.sibling_named(parent_id, name):
        raise Refused("A project named %s already exists there." % name)
    pid, stamp = new_project_id(), store.now_iso()
    conn.execute("INSERT INTO projects (id, name, parent_id, archived_at, created_at, updated_at) "
                 "VALUES (?, ?, ?, NULL, ?, ?)", (pid, name, parent_id, stamp, stamp))
    return pid


def move_project(conn, project_id, new_parent_id):
    """Re-parent a project, bump its revision and record the move. Returns the move id, or None
    when it already had that parent."""
    tree = Tree(conn)
    row = tree.row(project_id)
    if project_id == store.INBOX_ID:
        raise Refused("The Inbox can't be moved.")
    if new_parent_id is not None:
        target = tree.row(new_parent_id)
        if new_parent_id == project_id or project_id in tree.ancestors(new_parent_id):
            raise Refused("Can't move %s into %s: it is inside %s." % (row["name"], target["name"], row["name"]))
    if row["parent_id"] == new_parent_id:
        return None
    _parent_ok(tree, new_parent_id, row["name"])
    if tree.sibling_named(new_parent_id, row["name"], skip=project_id):
        raise Refused("A project named %s already exists there." % row["name"])
    stamp, revision = store.now_iso(), row["revision"] + 1
    conn.execute("UPDATE projects SET parent_id = ?, revision = ?, updated_at = ? WHERE id = ?",
                 (new_parent_id, revision, stamp, project_id))
    cur = conn.execute("INSERT INTO moves (project_id, from_project, to_project, revision, at) VALUES (?, ?, ?, ?, ?)",
                       (project_id, row["parent_id"], new_parent_id, revision, stamp))
    return cur.lastrowid


def rename_project(conn, project_id, name):
    name = clean_name(name)
    tree = Tree(conn)
    row = tree.row(project_id)
    if project_id == store.INBOX_ID:
        raise Refused("The Inbox can't be renamed.")
    if row["name"] == name:
        return
    if tree.sibling_named(row["parent_id"], name, skip=project_id):
        raise Refused("A project named %s already exists there." % name)
    conn.execute("UPDATE projects SET name = ?, updated_at = ? WHERE id = ?", (name, store.now_iso(), project_id))


def link_projects(conn, a_id, b_id):
    """Link two projects. Returns True when the link is new."""
    tree = Tree(conn)
    a, b = tree.row(a_id), tree.row(b_id)
    if a_id == b_id:
        raise Refused("Can't link %s to itself." % a["name"])
    if store.INBOX_ID in (a_id, b_id):
        raise Refused("The Inbox can't be linked.")
    lo, hi = sorted((a_id, b_id))
    cur = conn.execute("INSERT OR IGNORE INTO links (a_id, b_id, created_at) VALUES (?, ?, ?)", (lo, hi, store.now_iso()))
    return cur.rowcount == 1


def archive_project(conn, project_id):
    row = Tree(conn).row(project_id)
    if project_id == store.INBOX_ID:
        raise Refused("The Inbox can't be archived.")
    if row["archived_at"]:
        return
    stamp = store.now_iso()
    conn.execute("UPDATE projects SET archived_at = ?, updated_at = ? WHERE id = ?", (stamp, stamp, project_id))


def delete_project(conn, project_id):
    """Delete an empty project with its links and rules. Returns its name."""
    tree = Tree(conn)
    row = tree.row(project_id)
    if project_id == store.INBOX_ID:
        raise Refused("The Inbox can't be deleted.")
    children, items = len(tree.children.get(project_id, [])), tree.items.get(project_id, 0)
    if children or items:
        held = []
        if children:
            held.append("%d sub-project%s" % (children, "" if children == 1 else "s"))
        if items:
            held.append("%d item%s" % (items, "" if items == 1 else "s"))
        raise Refused("Can't delete %s: it still holds %s. Move them out first, or archive it instead."
                      % (row["name"], " and ".join(held)))
    conn.execute("DELETE FROM links WHERE a_id = ? OR b_id = ?", (project_id, project_id))
    conn.execute("DELETE FROM rules WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM moves WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return row["name"]


# ---------------------------------------------------------------- export

def _rows(conn, sql):
    return [dict(r) for r in conn.execute(sql)]


def export_document(conn, version):
    """The whole store (minus the cache, which is rebuilt by any refresh) as one JSON-ready dict."""
    items = _rows(conn, "SELECT * FROM items ORDER BY id")
    for item in items:
        try:
            item["data"] = json.loads(item.pop("data_json") or "{}")
        except ValueError:
            item["data"] = {}
    return {
        "format": "project-studio-export",
        "schema_version": version,
        "exported_at": store.now_iso(),
        "projects": _rows(conn, "SELECT id, name, parent_id, archived_at, revision, created_at, updated_at FROM projects "
                                       "ORDER BY created_at, id"),
        "links": _rows(conn, "SELECT a_id, b_id, created_at FROM links ORDER BY a_id, b_id"),
        "items": items,
        "rules": _rows(conn, "SELECT id, project_id, signal, pattern, created_at FROM rules ORDER BY created_at, id"),
        "moves": _rows(conn, "SELECT id, item_id, project_id, from_project, to_project, revision, at FROM moves ORDER BY id"),
    }
