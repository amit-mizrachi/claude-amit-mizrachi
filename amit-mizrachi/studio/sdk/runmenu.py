"""A night run's actions menu: the ONE list of what applies to a run, which home's run lines, the
project view's run panels, the CLI's `actions` and the MCP's `studio_run_actions` all draw.

Rules kept here, in menu order:
- Open plan: it has a plan page (`has_plan`: an artifact of it that is not dismissed; a gone one
  still counts, as Open plan opens it). Open PR: it has a PR with a URL.
- Open in Terminal: a ticket session of it is still listed by `claude agents` (`target_id` is that
  session). Open conductor: its conductor session is known (`target_id` is that session). Neither
  for a gone run.
- Move to...: always; the picker (`move_choices`, `move`), its attached items follow, Undo.
- Mark done: a Blocked or Waiting-on-you run that is not gone (`mark_done`).
- Dismiss, or Restore for a dismissed run (`dismiss_item`, `restore_item`).
- Throw away...: always last, the one destructive action, confirmed with what would go
  (`throw_away`). Nothing else here removes anything.
- Every run line, on home, in the project view and in `status`, shows its links after its name
  (`links`): its PR ("#733", its state and checks as the tooltip), Open plan (filled on a run
  waiting on you, quiet otherwise) and Open conductor, each one only when its action applies.
- Besides the menu and the links, a project view panel shows every other action but Move to...
  (the menu and drag) as a button too (`quick`); a home line shows none.
"""

from . import items, model, runstatus
from .actions import run_session
from .errors import Refused
from .reconcile import WORKSPACE_KINDS
from .results import RunAction, RunActions, RunLink

MARKABLE = runstatus.MARKABLE
LINKS = ("open-pr", "open-plan", "open-conductor")   # a run line's links after its name, in this order
MENU_ONLY = ("move",)                                # a run panel shows every other action as a button too
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


def has_plan(run, arts):
    """Whether `run` has a plan page among `arts` (artifact `Item`s): one of its own, not dismissed."""
    return any(a.workspace_item_id == run.item_id and not a.dismissed for a in arts)


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


def pr_label(pr):
    """A run's PR as its link says it: "#733", or "PR" when its number is not known."""
    return "#%d" % pr["number"] if pr and pr.get("number") else "PR"


def links(run, actions):
    """The `RunLink`s a line of `run` shows after its name, from `actions` (`for_run`'s list), in
    `LINKS` order: its PR ("#733", tooltip "PR #733 open - checks green"), Open plan (`primary` on
    a run waiting on you) and Open conductor, each only when its action is in the list."""
    by_id = {a.id: a for a in actions}
    found = []
    for link_id in LINKS:
        a = by_id.get(link_id)
        if not a:
            continue
        if link_id == "open-pr":
            found.append(RunLink(id=a.id, label=pr_label(run.pr), target_id=a.target_id,
                                 hint=run.pr_text or a.hint, url=run.pr.get("url") or ""))
        else:
            found.append(RunLink(id=a.id, label=a.label, target_id=a.target_id, hint=a.hint,
                                 primary=link_id == "open-plan" and run.status == "needs-you"))
    return found


def pr_links(runs):
    """A home row's PR line as links: one per PR (by URL) of `runs`, in their order, labelled with its
    whole text ("PR #738 open - checks running"); open-pr on the run that has it."""
    found, seen = [], set()
    for run in runs:
        url = (run.pr or {}).get("url") or ""
        if url and run.pr_text and url not in seen:
            seen.add(url)
            found.append(RunLink(id="open-pr", label=run.pr_text, target_id=run.item_id, hint=HINTS["open-pr"],
                                 url=url))
    return found


def panel_quick(actions):
    """The ids of `actions` a project view run panel draws as buttons besides its links: all but
    Move to... and the links."""
    return [a.id for a in actions if a.id not in MENU_ONLY and a.id not in LINKS]


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
    prs = items.every_pr(conn, tree)
    arts = [items.to_item(dict(a), tree) for a in conn.execute("SELECT * FROM items WHERE kind = 'artifact' AND "
                                                               "workspace_item_id = ? AND dismissed_at IS NULL", (r["id"],))]
    run = items.to_run(item, prs, arts, items.session_ids(conn))
    return RunActions(item_id=run.item_id, title=run.title, status=run.status,
                      word=run.word, project_id=run.project_id,
                      dismissed=bool(item.dismissed), actions=for_run(run, has_plan(run, arts), live_session(conn, run),
                                                                      bool(item.dismissed)))
