"""The studio's Inbox drawer and its "Move to..." / "Set parent" picker.

Every rule the drawer and the picker show lives here, not in the web server or the page script:
- An Inbox row is the item's name, its kind and one fact ("interactive - 2 h", "night run - Done",
  "PR - open"), and, when the Inbox has a suggestion, the chip "-> <project>" (the reason as its
  tooltip) and Accept.
- "Move to..." for an item offers every active project but the one it is in (the Inbox included,
  which takes it out). "Set parent" for a project offers the top level and every other active
  project; one inside it is offered too, and the move refuses it with "Can't move A into B: it is
  inside A.", so the tree stays a tree and the person sees why.
"""

import time

from . import items, model, store
from .home import WORDS
from .projectview import span
from .reconcile import WORKSPACE_KINDS
from .results import InboxRow, InboxView, MoveChoice, MoveChoices

DOT, ARROW = " · ", "→ "
KIND_WORDS = {"session-bg": "bg session", "session-interactive": "interactive", "night-sprint": "night run",
              "night-marathon": "night run", "pr": "PR", "worktree": "worktree", "artifact": "artifact"}
HINT = "Drag a row onto a card, or Accept the suggestion."
EMPTY = "Nothing waiting. New sessions and night runs that no rule files land here."
TOP_LEVEL = "Top level"


def _fact(item, now):
    data = item.data
    if item.kind in WORKSPACE_KINDS:
        return WORDS.get(item.status, item.status.capitalize())
    if item.kind == "pr":
        return "draft" if data.get("draft") and data.get("state") == "open" else str(data.get("state") or "")
    stamp = data.get("last_active") or data.get("started_at") or data.get("updated_at") or item.seen_at
    return span(stamp, now)


def row(entry, now):
    """One drawer row from an InboxEntry."""
    item, hint = entry.item, entry.suggestion
    fact = _fact(item, now)
    return InboxRow(item_id=item.id, revision=item.revision, title=item.title,
                    meta=KIND_WORDS.get(item.kind, item.kind) + (DOT + fact if fact else ""),
                    chip=ARROW + hint.project_name if hint else "", chip_title=hint.reason if hint else "",
                    can_accept=hint is not None)


def state(conn, limit, now=None):
    """The whole drawer as one InboxView, newest first, at most `limit` rows."""
    now = time.time() if now is None else now
    entries = items.inbox(conn)
    rows = [row(e, now) for e in entries[:limit]]
    return InboxView(rows=rows, count=len(entries), truncated=len(rows) < len(entries), hint=HINT, empty=EMPTY)


def _label(project):
    return " / ".join(project.path)


def choices(conn, target_id):
    """What "Move to..." (an item) or "Set parent" (a project) offers, in tree order."""
    active = model.list_projects(conn, None, False, False)
    if isinstance(target_id, str) and items.ITEM_ID.match(target_id):
        item = items.to_item(items.row(conn, target_id), model.Tree(conn))
        offer = [MoveChoice(id=p.id, label=_label(p)) for p in active if p.id != item.project_id]
        return MoveChoices(target_id=item.id, kind="item", name=item.title, title="Move %s to..." % item.title,
                           revision=item.revision, choices=offer)
    project = model.Tree(conn).project(target_id)
    if project.is_inbox:
        offer = []
    else:
        offer = [MoveChoice(id=None, label=TOP_LEVEL)] if project.parent_id else []
        offer += [MoveChoice(id=p.id, label=_label(p)) for p in active
                  if p.id not in (project.id, project.parent_id, store.INBOX_ID)]
    return MoveChoices(target_id=project.id, kind="project", name=project.name,
                       title="Set parent of %s" % project.name, revision=None, choices=offer)
