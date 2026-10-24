"""A night run's actions menu: the ONE list of what applies to a run, which home's run lines, the
project view's run panels, the CLI's `actions` and the MCP's `studio_run_actions` all draw.

Rules kept here, in menu order:
- Open plan: it has a plan page. Open PR: it has a PR with a URL.
- Open in Terminal: a ticket session of it is still listed by `claude agents` (`target_id` is that
  session). Open conductor: its conductor session is known (`target_id` is that session). Neither
  for a gone run.
- Move to...: always; the picker (`move_choices`, `move`), its attached items follow, Undo.
- Mark done: a Blocked or Waiting-on-you run that is not gone (`mark_done`).
- Dismiss, or Restore for a dismissed run (`dismiss_item`, `restore_item`).
- Throw away...: always last, the one destructive action, confirmed with what would go
  (`throw_away`). Nothing else here removes anything.
- Besides the menu, some show as buttons (`quick`): on a home line waiting on you, Open conductor
  beside its Open plan; on a project view panel, every action but Move to... (the menu and drag).
"""

from . import items, model
from .actions import run_session
from .errors import Refused
from .home import WORDS
from .reconcile import WORKSPACE_KINDS
from .results import RunAction, RunActions

MARKABLE = ("needs-you", "blocked")
HOME_QUICK = {"needs-you": ("open-conductor",)}   # a home line's buttons beside its Open plan, by status
MENU_ONLY = ("move",)                              # a run panel shows every other action as a button too
HINTS = {
    "open-plan": "Open its plan page.",
    "open-pr": "Open its pull request.",
    "open-terminal": "Open its live ticket session in your terminal app.",
    "open-conductor": "Open the session that conducts this run.",
    "move": "Move it to another project; its sessions, PRs and worktrees follow. Undoable.",
    "mark-done": "Its files froze on a word no longer true. Shows Done until they change again. Undoable.",
    "dismiss": "Hide it from every list. Deletes nothing; Restore it from Dismissed.",
    "restore": "Show it again, with what its dismissal took along. Undoable.",
    "throw-away": "Its folder to the Trash, its worktrees removed (never forced), the run out of the studio. "
                  "Asks first.",
}
LABELS = {"open-plan": "Open plan", "open-pr": "Open PR", "open-terminal": "Open in Terminal",
          "open-conductor": "Open conductor", "move": "Move to...", "mark-done": "Mark done", "dismiss": "Dismiss",
          "restore": "Restore", "throw-away": "Throw away..."}


def _action(action_id, target_id):
    removes = action_id == "throw-away"
    return RunAction(id=action_id, label=LABELS[action_id], destructive=removes, needs_confirm=removes,
                     target_id=target_id, hint=HINTS[action_id])


def for_run(run, has_plan, terminal_item_id=None, dismissed=False):
    """The `RunAction`s that apply to `run` (a `Run`), in menu order. `has_plan`: it has a plan page;
    `terminal_item_id`: its live ticket session (`actions.run_session`), None for none."""
    found = []
    if has_plan:
        found.append(_action("open-plan", run.item_id))
    if run.pr and run.pr.get("url"):
        found.append(_action("open-pr", run.item_id))
    if terminal_item_id and not run.gone:
        found.append(_action("open-terminal", terminal_item_id))
    if run.conductor_item_id and not run.gone:
        found.append(_action("open-conductor", run.conductor_item_id))
    found.append(_action("move", run.item_id))
    if run.status in MARKABLE and not run.gone:
        found.append(_action("mark-done", run.item_id))
    found.append(_action("restore" if dismissed else "dismiss", run.item_id))
    found.append(_action("throw-away", run.item_id))
    return found


def home_quick(run, actions):
    """The ids of `actions` a home line draws as buttons: Open conductor on a line waiting on you."""
    wanted = HOME_QUICK.get(run.status, ())
    return [a.id for a in actions if a.id in wanted]


def panel_quick(actions):
    """The ids of `actions` a project view run panel draws as buttons: all but Move to...."""
    return [a.id for a in actions if a.id not in MENU_ONLY]


def live_session(conn, run):
    """The item id of `run`'s live ticket session, or None (always None for a gone run)."""
    found = run_session(conn, run.item_id) if not run.gone else None
    return found["id"] if found else None


def of(conn, item_id):
    """`RunActions` for the night run `item_id`, from the store: the same list its home line and its
    project view panel show. Refused for any other kind of item."""
    r = items.row(conn, item_id)
    if r["kind"] not in WORKSPACE_KINDS:
        raise Refused("Only a night run has run actions; %s is %s." % (r["title"], items.NOT_A_RUN.get(r["kind"],
                                                                                                      r["kind"])))
    tree = model.Tree(conn)
    item = items.to_item(r, tree)
    prs = [items.to_item(dict(p), tree) for p in conn.execute("SELECT * FROM items WHERE kind = 'pr' AND "
                                                              "dismissed_at IS NULL")]
    arts = [items.to_item(dict(a), tree) for a in conn.execute("SELECT * FROM items WHERE kind = 'artifact' AND "
                                                               "workspace_item_id = ? AND gone_at IS NULL", (r["id"],))]
    run = items.to_run(item, prs, arts, items.session_ids(conn))
    return RunActions(item_id=run.item_id, title=run.title, status=run.status,
                      word=WORDS.get(run.status, run.status.title()), project_id=run.project_id,
                      dismissed=bool(item.dismissed), actions=for_run(run, bool(arts), live_session(conn, run),
                                                                      bool(item.dismissed)))
