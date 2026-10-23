"""The reconcile scan: file every found item into a project, and retire nothing on a bad read.

Placement, strongest first: manual > title > cwd/worktree > rule > Inbox.
- manual: an item a person (or an agent) placed never moves on its own again.
- title / cwd: an item linked to a run (a session named `ns-<slug>-<TAG>` or listed in its
  `state/<TAG>.session`, a cwd, worktree, branch or artifact inside it) lives where the run
  lives, and follows the run when it moves. Its link is kept in `workspace_item_id`.
- rule: the first matching attach rule (`sdk.rules`).
- Inbox: everything else.
An archived project gets nothing new: a link or rule that points into one is skipped.

An item already placed by title or cwd follows its run; an Inbox item is filed again when a
rule or a filed run now claims it; rule-placed items move only when a run claims them.

Gone: only an item whose scope was read completely (`Inventory.ok_scopes`) and that the read
did not hold gets `gone_at`. It keeps its project. Found again, it comes back. When
`claude agents` failed, every bg session is UNKNOWN (`data.status = "unknown"`), never gone.
A session the SessionStart hook attached (`sdk.attach`) has no scope until a read finds it; it
counts as "sessions" only once ATTACH_GRACE_SECONDS have passed.
"""

import json
import time
import uuid

from . import model, rules, store

WORKSPACE_KINDS = ("night-sprint", "night-marathon")
AUTO_LINK = ("title", "cwd")
ATTACH_GRACE_SECONDS = 600     # how long a hook-attached session may go unseen by every read


def new_item_id():
    return "i_" + uuid.uuid4().hex[:12]


def item_data(row):
    try:
        data = json.loads(row["data_json"] or "{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


class Placer(object):
    """Decides where a found item belongs, from the tree, the rules and the runs' homes."""

    def __init__(self, conn):
        self.tree = model.Tree(conn)
        self.rules = rules.load(conn)
        self.runs = {}            # workspace key -> its item row (dict)

    def place(self, link, signals):
        """(project_id, placed_by, workspace_item_id) for an item that is not placed by hand."""
        run = self.runs.get(link[0]) if link else None
        if run is not None and not self.tree.hidden(run["project_id"]):
            return run["project_id"], link[1], run["id"]
        rule = rules.match(self.rules, signals, self.tree)
        wsid = run["id"] if run is not None else None
        if rule is not None:
            return rule["project_id"], "rule", wsid
        return store.INBOX_ID, "inbox", wsid


def _changes_home(row, target, rung):
    if row["placed_by"] == "manual":
        return False
    if rung in AUTO_LINK:
        return (target, rung) != (row["project_id"], row["placed_by"])
    return row["placed_by"] == "inbox" and rung != "inbox"


def identity(kind, key):
    """What makes two items the same: (kind, key), except that a session's kind is derived and can
    change, so a session is one item per session id across both session kinds."""
    return ("session", key) if kind in store.SESSION_KINDS else (kind, key)


def reconcile(conn, inventory):
    """Upsert every found item, file what is unplaced, mark gone what a complete read lost.

    Runs inside the caller's write transaction. Returns counts: added, filed, gone, back.
    """
    placer, stamp = Placer(conn), store.now_iso()
    rows = {identity(r["kind"], r["key"]): dict(r) for r in conn.execute("SELECT * FROM items")}
    for row in rows.values():
        if row["kind"] in WORKSPACE_KINDS:
            placer.runs[row["key"]] = row
    counts = {"added": 0, "filed": 0, "gone": 0, "back": 0}
    seen = set()
    for found in inventory.found():
        ident = identity(found.kind, found.key)
        if ident in seen:                          # one item found twice in a scan: the first one wins
            continue
        seen.add(ident)
        data = json.dumps(dict(found.data, scope=found.scope, signals=found.signals), sort_keys=True)
        row = rows.get(ident)
        target, rung, wsid = placer.place(found.link, found.signals)
        if row is None:
            row = {"id": new_item_id(), "kind": found.kind, "key": found.key, "project_id": target,
                   "placed_by": rung, "workspace_item_id": wsid, "revision": 1}
            conn.execute("INSERT INTO items (id, kind, key, title, project_id, placed_by, workspace_item_id, "
                         "revision, data_json, seen_at, gone_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)",
                         (row["id"], found.kind, found.key, found.title[:300], target, rung, wsid, data, stamp))
            counts["added"] += 1
        else:
            if row["gone_at"]:
                counts["back"] += 1
            wsid = wsid or row["workspace_item_id"]
            if _changes_home(row, target, rung):
                row.update(project_id=target, placed_by=rung, revision=row["revision"] + 1)
                counts["filed"] += 1
            row.update(workspace_item_id=wsid, kind=found.kind)
            conn.execute("UPDATE items SET kind = ?, title = ?, data_json = ?, seen_at = ?, gone_at = NULL, "
                         "project_id = ?, placed_by = ?, workspace_item_id = ?, revision = ? WHERE id = ?",
                         (found.kind, found.title[:300], data, stamp, row["project_id"], row["placed_by"], wsid,
                          row["revision"], row["id"]))
        if found.kind in WORKSPACE_KINDS:
            placer.runs[found.key] = row
    for key, row in rows.items():
        if key not in seen:
            counts["gone"] += _not_found(conn, row, inventory, stamp)
    return counts


def _attached_scope(row, data, now):
    """A session the SessionStart hook attached that no read has found yet joins the "sessions"
    scope only after ATTACH_GRACE_SECONDS, so a read made before its transcript existed can't
    mark it gone, and one that never wrote a transcript does not stay "starting" for ever."""
    if data.get("attached_by") != "session-start":
        return None
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - ATTACH_GRACE_SECONDS))
    return "sessions" if (row["seen_at"] or "") < cutoff else None


def _not_found(conn, row, inventory, stamp):
    """An item this scan did not find: gone only on a complete read; UNKNOWN when agents failed."""
    data = item_data(row)
    scope = data.get("scope") or _attached_scope(row, data, inventory.now)
    if not scope:
        return 0                                   # added by hand, outside every reader: never gone
    if scope in inventory.ok_scopes and row["key"] not in inventory.present.get(scope, ()):
        if not row["gone_at"]:
            conn.execute("UPDATE items SET gone_at = ? WHERE id = ?", (stamp, row["id"]))
            return 1
        return 0
    if row["kind"] == "session-bg" and not inventory.agents_ok and data.get("status") != "unknown":
        data["status"] = "unknown"
        conn.execute("UPDATE items SET data_json = ? WHERE id = ?", (json.dumps(data, sort_keys=True), row["id"]))
    return 0
