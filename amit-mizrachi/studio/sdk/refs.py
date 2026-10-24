"""References: how a person names a project or an item without copying its whole id.

Every function takes an open connection; `sdk.api` owns the transactions. Rules kept here:
- A project reference is its exact id, then a unique id prefix (at least 4 characters; the `p_`
  may be left out), then a case-insensitive exact name among active projects. A unique name wins
  over a prefix that matches several ids.
- An item reference is its exact id or a unique id prefix (at least 4 characters; the `i_` may
  be left out). Item titles are not unique, so there is no name matching for items.
- No match raises NotFound; more than one raises Ambiguous with the candidates.
"""

from . import items, model
from .errors import Ambiguous, InvalidInput, NotFound

MIN_PREFIX = 4
MAX_CANDIDATES = 20


def _text(ref, shape):
    if not isinstance(ref, str) or not ref.strip():
        raise InvalidInput("A reference must be %s." % shape)
    return ref.strip()


def _many(ref, what, found, describe):
    shown = found[:MAX_CANDIDATES]
    more = " and %d more" % (len(found) - len(shown)) if len(found) > len(shown) else ""
    listed = "; ".join(describe(c) for c in shown)
    raise Ambiguous("%r matches %d %ss: %s%s. Use an id or a longer prefix." % (ref, len(found), what, listed, more),
                    shown)


def _project_candidate(project):
    return {"id": project.id, "name": project.name, "parent_path": project.path[:-1]}


def _say_project(c):
    return "%s %s (%s)" % (c["id"], c["name"], "in " + " / ".join(c["parent_path"]) if c["parent_path"]
                           else "top level")


def project(conn, ref):
    """The `Project` that `ref` names (see the module rules)."""
    ref = _text(ref, "a project id, an id prefix or a name")
    tree = model.Tree(conn)
    if ref in tree.rows:
        return tree.project(ref)
    prefixed = []
    if len(ref) >= MIN_PREFIX:
        prefixed = [pid for pid in tree.rows if pid.startswith(ref) or pid.startswith("p_" + ref)]
        if len(prefixed) == 1:
            return tree.project(prefixed[0])
    named = [pid for pid, row in tree.rows.items() if row["name"].lower() == ref.lower() and not tree.hidden(pid)]
    found = sorted((tree.project(pid) for pid in (named or prefixed)), key=model.order_key)
    if not found:
        raise NotFound("No project matches %r: it is not an id, a unique id prefix or an active project's name." % ref)
    if len(found) == 1:
        return found[0]
    _many(ref, "project", [_project_candidate(p) for p in found], _say_project)


def _say_item(c):
    return "%s %s (%s, in %s)" % (c["id"], c["title"], c["kind"], " / ".join(c["project_path"]))


def item(conn, ref):
    """The `Item` that `ref` names (see the module rules)."""
    ref = _text(ref, "an item id or an id prefix")
    tree = model.Tree(conn)
    full = ref if ref.startswith("i_") else "i_" + ref     # a whole id is its own one-match prefix
    rows = []
    if len(ref) >= MIN_PREFIX:
        rows = [dict(r) for r in conn.execute("SELECT * FROM items WHERE substr(id, 1, ?) = ? ORDER BY id",
                                              (len(full), full))]
    if not rows:
        raise NotFound("No item matches %r: it is not an item id or a unique id prefix." % ref)
    if len(rows) == 1:
        return items.to_item(rows[0], tree)
    found = [items.to_item(r, tree) for r in rows]
    _many(ref, "item", [{"id": i.id, "title": i.title, "kind": i.kind, "project_path": i.project_path} for i in found],
          _say_item)
