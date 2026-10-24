"""The public Project Studio SDK. Every adapter (MCP server, studio web server, hooks) calls these.

This module IS the contract (studio/sdk/README.md lists it too). Each function:
- opens the store under `$PROJECT_STUDIO_HOME` (default `~/.project-studio`) for one call,
- runs every write in one BEGIN IMMEDIATE transaction,
- returns a structured value from `sdk.results` (serialise it with `sdk.results.to_dict`),
- raises an `sdk.errors.StudioError` subclass whose message is fit to show a person as it is:
  `NotFound`, `Ambiguous` (a reference matches more than one), `InvalidInput`, `Refused` (a rule
  says no), `ReadOnlyStore` (newer store). `to_dict()` gives `{code, message}` (and `candidates`).

An adapter parses its input, calls ONE of these, and serialises the result. No SQL, ranking or
state rule lives outside `studio/sdk/`. A new agent tool (say `project_status`) is a new
function here plus a few adapter lines.
"""

import json
import os
import tempfile
from typing import Optional

from . import (actions, attach, home as homepage, inboxview, items, model, projectview, refresh as scan, refs, server,
               settings as user_settings, store)
from .errors import InvalidInput, Refused
from .results import (AttachResult, DeleteRequest, DeleteResult, Export, HomeState, InboxList, InboxView, Item, ItemList,
                      LinkResult, MoveChoices, MoveResult, OpenResult, Project, ProjectList, ProjectStatus, ProjectView,
                      PurgeResult, RefreshResult, Rule, RuleList, Settings, StudioServer, TerminalCommand,
                      TerminalOpen)

MAX_LIST_LIMIT = 1000


def _optional_id(value, name):
    if value is not None and not isinstance(value, str):
        raise InvalidInput("%s must be a project id or null." % name)
    return value or None


def _limit(value):
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LIST_LIMIT):
        raise InvalidInput("limit must be a whole number from 1 to %d." % MAX_LIST_LIMIT)
    return value


def _page(found, limit):
    shown = found[:limit] if limit else found
    return shown, len(found), len(shown) < len(found)


def _flag(value, name):
    if not isinstance(value, bool):
        raise InvalidInput("%s must be true or false." % name)
    return value


def create_project(name: str, parent_id: Optional[str] = None) -> Project:
    """Create a project, top-level or under `parent_id`, and return it.

    Refused when the parent is the Inbox or archived, or an active sibling already has the
    name (ignoring case). The name is trimmed; 1-120 characters, no control characters.
    """
    parent_id = _optional_id(parent_id, "parent_id")
    with store.write() as conn:
        pid = model.create_project(conn, name, parent_id)
        return model.Tree(conn).project(pid)


def list_projects(parent_id: Optional[str] = None, top_level: bool = False,
                  include_archived: bool = False, limit: Optional[int] = None, with_runs: bool = False) -> ProjectList:
    """Projects in tree order (the Inbox first, then by path), at most `limit` of them.

    `parent_id` keeps only that project's direct sub-projects; `top_level` keeps only
    top-level projects. Archived projects, and everything under them, are left out unless
    `include_archived`. `total` counts every match before the limit. `with_runs` also fills
    `run_lines`: each shown project's night-run line, rolled up over its sub-projects.
    """
    parent_id = _optional_id(parent_id, "parent_id")
    top_level, include_archived = _flag(top_level, "top_level"), _flag(include_archived, "include_archived")
    limit, with_runs = _limit(limit), _flag(with_runs, "with_runs")
    with store.read() as conn:
        found = model.list_projects(conn, parent_id, top_level, include_archived)
        shown, total, truncated = _page(found, limit)
        lines = projectview.run_lines(conn, [p.id for p in shown]) if with_runs else {}
    return ProjectList(projects=shown, total=total, truncated=truncated, run_lines=lines)


def resolve_project(ref: str) -> Project:
    """The project a person names: its exact id, then a unique id prefix (4+ characters, the `p_`
    optional), then a case-insensitive exact name among active projects (archived ones, and those
    under them, are left out). NotFound when nothing matches; Ambiguous, with `candidates`
    ({id, name, parent_path}), when more than one does.
    """
    with store.read() as conn:
        return refs.project(conn, ref)


def resolve_item(ref: str) -> Item:
    """The item a person names: its exact id or a unique id prefix (4+ characters, the `i_`
    optional). No title matching: titles are not unique. NotFound when nothing matches; Ambiguous,
    with `candidates` ({id, title, kind, project_path}), when more than one does.
    """
    with store.read() as conn:
        return refs.item(conn, ref)


def get_project(project_id: str) -> Project:
    """One project by id, archived or not. NotFound when there is none."""
    with store.read() as conn:
        return model.Tree(conn).project(project_id)


def move_project(project_id: str, new_parent_id: Optional[str] = None) -> Project:
    """Give a project a new parent (`None` = top level) and return it.

    Refused with "Can't move <A> into <B>: it is inside <A>." when B is A or under A, and when
    the target is the Inbox or archived, or already holds an active project with A's name.
    Moving to the parent it already has changes nothing.
    """
    new_parent_id = _optional_id(new_parent_id, "new_parent_id")
    with store.write() as conn:
        model.move_project(conn, project_id, new_parent_id)
        return model.Tree(conn).project(project_id)


def rename_project(project_id: str, name: str) -> Project:
    """Give a project a new name and return it. Same name rules as `create_project`; refused for
    the Inbox and when an active sibling already has the name (ignoring case).
    """
    with store.write() as conn:
        model.rename_project(conn, project_id, name)
        return model.Tree(conn).project(project_id)


def link_projects(a_id: str, b_id: str) -> LinkResult:
    """Link two projects (a symmetric relation, shown as text). Linking twice changes nothing.

    Refused for a project and itself, and for the Inbox.
    """
    with store.write() as conn:
        created = model.link_projects(conn, a_id, b_id)
    lo, hi = sorted((a_id, b_id))
    return LinkResult(a_id=lo, b_id=hi, created=created)


def archive_project(project_id: str) -> Project:
    """Archive a project: it and everything under it leave the lists and get no new auto-attached items.

    Archiving an archived project changes nothing. Refused for the Inbox.
    """
    with store.write() as conn:
        model.archive_project(conn, project_id)
        return model.Tree(conn).project(project_id)


def delete_project(project_id: str) -> DeleteResult:
    """Delete an EMPTY project (no sub-projects, no items), with its links and rules.

    Refused for a project that holds anything (archive it instead) and for the Inbox.
    """
    with store.write() as conn:
        name = model.delete_project(conn, project_id)
    return DeleteResult(id=project_id, name=name)


def _count(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def delete_project_guarded(project_id: str, confirmed: bool = False) -> DeleteRequest:
    """`delete_project` for an agent: unless `confirmed`, change nothing and say what it would delete
    (`needs_confirm` True, `message` "This deletes the project Scratch (p_...) for good, with its
    1 link and 0 rules. Call again confirmed."). Confirmed, it deletes the project. Either way it is
    refused for the Inbox and for a project that holds anything, so a refusal comes before the ask.
    """
    confirmed = _flag(confirmed, "confirmed")
    with store.write() as conn:
        name, links, rules = model.delete_plan(conn, project_id)
        if confirmed:
            model.delete_project(conn, project_id)
    if confirmed:
        message = "Deleted %s." % name
    else:
        message = ("This deletes the project %s (%s) for good, with its %s and %s. Call again confirmed."
                   % (name, project_id, _count(links, "link"), _count(rules, "rule")))
    return DeleteRequest(id=project_id, name=name, deleted=confirmed, needs_confirm=not confirmed, links=links,
                         rules=rules, message=message)


def export_json(dest: Optional[str] = None) -> Export:
    """The whole store as one JSON document, so the data is never locked in SQLite.

    With `dest`, also writes it there (mode 0600, atomically) and returns the absolute path.
    The cache is left out: any refresh rebuilds it.
    """
    with store.read() as conn:
        version = store.version_of(conn)
        document = model.export_document(conn, version)
    path = None
    if dest:
        path = os.path.abspath(os.path.expanduser(dest))
        fd, tmp = tempfile.mkstemp(prefix=".export-", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(document, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise
    return Export(document=document, path=path)


# ---------------------------------------------------------------- items (ticket 02)

def refresh(force: bool = False) -> RefreshResult:
    """Run every reader whose cache row is due (all of them when `force`), store what each said,
    and reconcile: new items are filed (manual > title > cwd/worktree > rule > Inbox), runs pull
    their auto-attached items along, and only a COMPLETE read marks an item gone. A failed read
    keeps the last-good data and shows up in `sources` with its error; `claude agents` failing
    leaves bg sessions with status "unknown". TTLs: state files 2 s (live runs), discover 60 s,
    `claude agents` 10 s, `gh pr list` 5 min per repo.
    """
    reads, counts, entries = scan.refresh(force=_flag(force, "force"))
    with store.read() as conn:
        sources = items.sources(conn)
    return RefreshResult(reads=[{"source": s, "key": k, "ok": ok} for s, k, ok in reads], sources=sources, **counts)


def _maybe_refresh(fresh, slow=True):
    if _flag(fresh, "refresh"):
        scan.refresh(strict=False, slow=slow)


def find_items(query: Optional[str] = None, kind: Optional[str] = None, project_id: Optional[str] = None,
               include_gone: bool = False, limit: Optional[int] = None, refresh: bool = True) -> ItemList:
    """Items whose title, key, name, cwd or branch holds `query` (any case), newest activity first,
    gone ones last. `kind` keeps one kind; `project_id` keeps items in that project or under it.
    Refreshes due sources first unless `refresh` is False.
    """
    if query is not None and not isinstance(query, str):
        raise InvalidInput("query must be text.")
    if kind is not None and kind not in store.ITEM_KINDS:
        raise InvalidInput("kind must be one of: %s." % ", ".join(store.ITEM_KINDS))
    project_id, limit = _optional_id(project_id, "project_id"), _limit(limit)
    include_gone = _flag(include_gone, "include_gone")
    _maybe_refresh(refresh)
    with store.read() as conn:
        found = items.find(conn, query, kind, project_id, include_gone)
    shown, total, truncated = _page(found, limit)
    return ItemList(items=shown, total=total, truncated=truncated)


def project_status(project_id: str, refresh: bool = True, limit: Optional[int] = None) -> ProjectStatus:
    """A project's night runs (each with status, reason, "T03 of 5" progress, stage, PR state and
    artifact), ranked needs-you > blocked > running > paused > latest, plus its sessions, PRs,
    worktrees and artifacts, all rolled up over its active sub-projects, the sub-projects with a
    run count, and every source's state. Refreshes due sources first unless `refresh` is False.
    `limit` keeps at most that many of each list; `totals` counts them all and `truncated` says one was cut.
    """
    limit = _limit(limit)
    _maybe_refresh(refresh)
    with store.read() as conn:
        found = items.status(conn, project_id)
    project, runs, sessions, prs, worktrees, artifacts, subs, sources = found
    lists = {"runs": runs, "sessions": sessions, "prs": prs, "worktrees": worktrees, "artifacts": artifacts}
    paged = {name: _page(found, limit) for name, found in lists.items()}
    return ProjectStatus(project=project, sub_projects=subs, sources=sources,
                         totals={name: page[1] for name, page in paged.items()},
                         truncated=any(page[2] for page in paged.values()),
                         **{name: page[0] for name, page in paged.items()})


def add_item(kind: str, key: str, project_id: str, title: Optional[str] = None) -> MoveResult:
    """File an item into a project by hand (`placed_by = manual`, so no rule ever moves it).

    `key` is the item's stable id: a session UUID, a folder path (a run or worktree, ad-hoc
    folders included), an https URL or file path for an artifact, `owner/repo#n` for a PR. An item
    the studio already knows is moved there instead (`created` False). Refused into an archived project.
    """
    with store.write() as conn:
        return items.add(conn, kind, key, project_id, title)


def move_item(item_id: str, project_id: str, expected_revision: Optional[int] = None) -> MoveResult:
    """Move an item to a project by hand. With `expected_revision`, refused when the item moved
    since that revision. A run's auto-attached sessions, PRs, worktrees and artifacts follow it;
    ones placed by hand stay. Returns the `move_id` for `undo_move` / `save_rule_from_move` and
    the `rule_preview` "Always file items like this here" would save.
    """
    if expected_revision is not None and (isinstance(expected_revision, bool) or not isinstance(expected_revision, int)):
        raise InvalidInput("expected_revision must be a whole number.")
    with store.write() as conn:
        return items.move(conn, item_id, project_id, expected_revision)


def move(target_id: str, to_project_id: Optional[str], expected_revision: Optional[int] = None) -> MoveResult:
    """Move an item (id `i_...`) or a project (id `p_...`) - the one call behind drop = move.

    A project goes under `to_project_id` (None = top level) as `move_project` does, and its move
    gets a `move_id` for `undo_move` too; an item goes into it as `move_item` does. `message` is
    the toast ("Moved to Project Studio").
    """
    if isinstance(target_id, str) and items.ITEM_ID.match(target_id):
        if to_project_id is None:
            raise InvalidInput("An item needs a project to move into.")
        return move_item(target_id, to_project_id, expected_revision)
    to_project_id = _optional_id(to_project_id, "to_project_id")
    with store.write() as conn:
        return items.move_project(conn, target_id, to_project_id)


def undo_move(move_id: int) -> MoveResult:
    """Put an item back where `move_id` took it from, or a project back under its old parent.
    Refused ("Can't undo: <name> was moved again since.") when it moved again since."""
    with store.write() as conn:
        return items.undo(conn, move_id)


def remove_item(item_id: str) -> MoveResult:
    """Take an item out of its project, back to the Inbox. It never deletes the thing itself,
    and it stays in the Inbox (placed by hand) until filed again."""
    with store.write() as conn:
        return items.move(conn, item_id, store.INBOX_ID, None)


def inbox(limit: Optional[int] = None, refresh: bool = True) -> InboxList:
    """Every unfiled item active in the last 14 days, newest first, each with a suggested project
    and the reason ("same run as ...", "rule: ...", "repo shapes-platform: 4 items there"), or none.
    Older unfiled items stay in the store: `find_items`, rules and moves still reach them."""
    limit = _limit(limit)
    _maybe_refresh(refresh)
    with store.read() as conn:
        found = items.inbox(conn)
    shown, total, truncated = _page(found, limit)
    return InboxList(entries=shown, total=total, truncated=truncated)


def accept_suggestion(item_id: str) -> MoveResult:
    """File an Inbox item into its suggested project, as a move by hand (undoable)."""
    with store.write() as conn:
        return items.accept(conn, item_id)


def save_rule_from_move(move_id: int) -> Rule:
    """"Always file items like this here": save a rule from the moved item's strongest signal
    (workspace slug > repo + branch prefix > cwd prefix) into the project the move went to.
    Refused for a project's move.
    The next refresh files matching new and Inbox items there. Saving the same rule twice
    returns the existing one (`created` False)."""
    with store.write() as conn:
        return items.save_rule(conn, move_id)


def list_rules(project_id: Optional[str] = None) -> RuleList:
    """The attach rules, strongest signal first; only one project's with `project_id`."""
    project_id = _optional_id(project_id, "project_id")
    with store.read() as conn:
        found = items.list_rules(conn, project_id)
    return RuleList(rules=found, total=len(found))


def delete_rule(rule_id: str) -> Rule:
    """Delete one rule. Items it filed stay where they are."""
    with store.write() as conn:
        return items.delete_rule(conn, rule_id)


def purge_gone(item_id: Optional[str] = None, all_gone: Optional[bool] = None) -> PurgeResult:
    """Delete gone items for good: one (refused if it is not gone), or every gone item.

    `all_gone` makes "every gone item" explicit, for an agent that must not purge them all by
    leaving `item_id` out: False with no `item_id` is refused, True with an `item_id` is
    InvalidInput. None (the CLI) keeps the old reading: no `item_id` means every gone item.
    """
    if all_gone is not None:
        all_gone = _flag(all_gone, "all_gone")
        if item_id is None and not all_gone:
            raise Refused("Say which gone item to purge (item_id), or set all_gone to purge every gone item.")
        if item_id is not None and all_gone:
            raise InvalidInput("Give item_id or all_gone, not both.")
    with store.write() as conn:
        ids = items.purge(conn, item_id)
    return PurgeResult(ids=ids, count=len(ids))


# ---------------------------------------------------------------- session start (ticket 03)

def _optional_text(value, name):
    if value is not None and not isinstance(value, str):
        raise InvalidInput("%s must be text or null." % name)
    return value or None


def attach_session(session_id: str, cwd: str, job_dir: Optional[str] = None,
                   entrypoint: Optional[str] = None) -> AttachResult:
    """File a session as it starts (the SessionStart hook), so it shows in its project at once.

    Same rules as the reconcile (title `ns-<slug>-<TAG>` > cwd/worktree > rule > Inbox), over the
    runs and rules the store already holds; it runs no reader, so it stays fast. `job_dir` is the
    session's `$CLAUDE_JOB_DIR` when it is a bg session (its `state.json` gives the name);
    `entrypoint` is `$CLAUDE_CODE_ENTRYPOINT`: a headless `sdk*` run is skipped without opening the
    store. A session the store already knows (a resume) stays where it is (`created` False).
    """
    if not isinstance(session_id, str) or not items.SESSION_KEY.match(session_id):
        raise InvalidInput("session_id must be a full session id (a UUID).")
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        raise InvalidInput("cwd must be an absolute path.")
    job_dir, entrypoint = _optional_text(job_dir, "job_dir"), _optional_text(entrypoint, "entrypoint")
    if attach.headless(entrypoint):
        return AttachResult(item=None, created=False, skipped="headless")
    with store.write() as conn:
        item, created = attach.attach(conn, session_id, cwd.rstrip("/") or "/", job_dir)
    return AttachResult(item=item, created=created)


# ---------------------------------------------------------------- the studio (ticket 04)

def home(refresh: bool = False) -> HomeState:
    """The studio's home page: one card per active top-level project (its active sub-projects as
    lines of their own in tree order, each with its glyph, status word, run line and "2 inside";
    at most 3 runs of it and its sub-projects, ranked needs-you > blocked > running > latest, a
    sub-project's run tagged "in <sub-project>"; "+ n earlier runs"; the newest PR state), cards ordered needs-you, blocked, running, then latest change; plus the
    Inbox count (items active in the last 14 days), the PR source age, a banner per failed source
    (last-good states kept), `first_run` when there is no project, and `reading` / `reading_text`
    naming the sources still being read ("Still reading PRs..."). It answers from what the store
    holds and never waits for a slow source: `refresh` True reads only the due fast ones first.
    """
    _maybe_refresh(refresh, slow=False)
    with store.read() as conn:
        return homepage.state(conn, reading=scan.reading())


def open_studio() -> StudioServer:
    """Make sure the studio web server runs, and return its URL. A live server of the same code
    version is reused (`started` False); an older one is asked to stop and a new one starts
    (`started` True). StartFailed when it does not come up within 5 s (see `studio.log` in the
    data dir). It never opens a browser: `bin/project-studio` does that.
    """
    return server.open_studio()


def studio_status() -> StudioServer:
    """The running studio (`running` True, with its URL and pid), or `running` False."""
    return server.studio_status()


def stop_studio() -> StudioServer:
    """Ask the running studio to stop (POST /shutdown with its token) and wait up to 5 s. It never
    kills a process. `running` False afterwards means it stopped (or was not running).
    """
    return server.stop_studio()


# ---------------------------------------------------------------- the project view and open actions (ticket 05)

def project_view(project_id: str, refresh: bool = False) -> ProjectView:
    """The studio's project view: breadcrumb, "Linked: ..." text, the projects "Link..." can offer,
    sub-project tiles ("1 run done", "no runs"), run panels (which of Open plan, Open PR and Open in
    Terminal apply), session rows (bg live "working - 2 min", bg done "finished - 3 h", interactive
    "last active 1 d", gone "(removed)"), and the "Everything else" folds (PRs, worktrees, artifacts,
    and sessions when none is active). Refreshes due sources first only when `refresh` is True.
    """
    _maybe_refresh(refresh)
    with store.read() as conn:
        return projectview.state(conn, project_id)


def terminal_command(item_id: str) -> TerminalCommand:
    """The command that opens a session again, built from the store: `claude attach <short id>` when
    `claude agents` lists the session, else `cd <recorded cwd> && claude --resume <session id>`
    (every value pattern-checked and shlex-quoted). `item_id` is a session, or a night run (its
    newest listed session). `confirm` is set when the transcript changed in the last 5 minutes.
    It runs nothing: this is what "Copy command" copies.
    """
    with store.read() as conn:
        found = actions.session_of(conn, item_id)
    return actions.terminal_command(found)


def open_in_terminal(item_id: str, confirmed: bool = False) -> TerminalOpen:
    """Open a session (or a night run's live session) in a terminal: write the `terminal_command` to
    `<data dir>/open/<item id>.command` (mode 0700) and open it in the `terminal` setting's app
    (`settings()`): by default `open <file>` (Terminal), or Terminal or iTerm by name. A setting
    it does not know falls back to Terminal and the message says so. When the open fails, the
    command goes to the clipboard (`copied`). A resume whose transcript changed in the last
    5 minutes runs nothing and returns `needs_confirm` until called with `confirmed` True.
    It never stops, kills or removes a session.
    """
    confirmed = _flag(confirmed, "confirmed")
    return actions.open_in_terminal(terminal_command(item_id), confirmed)


def settings() -> Settings:
    """The person's settings, from `<data dir>/settings.json`. `terminal` is the app Open in
    Terminal uses: "Terminal", "iTerm", or "" for the default (the app that opens .command files).
    """
    return user_settings.current()


def set_terminal(app: str) -> Settings:
    """Set the app Open in Terminal uses: "Terminal" or "iTerm" (any case; "iTerm2" and
    "Terminal.app" work too), or "default" to clear it. Refused (`InvalidInput`) for any other name.
    """
    if not isinstance(app, str):
        raise InvalidInput("app must be a string.")
    return user_settings.set_terminal(app)


def open_target(item_id: str, target: str = "default") -> OpenResult:
    """Open an item with `open`: an http(s) URL in the browser, a folder in Finder, a page or text
    file in its app, any other file revealed in Finder (`open -R`). The value is the item's own,
    from the store: `target` "plan" is a night run's plan page, "pr" its PR, "default" the item
    itself (a run's or worktree's folder, a PR's URL, an artifact). Refused for a path outside
    the known roots and for anything that is not an http(s) URL or a path.
    """
    with store.read() as conn:
        found_id, value, how, argv = actions.resolve_target(conn, item_id, target)
    return actions.run_open(found_id, target, value, how, argv)


# ---------------------------------------------------------------- the Inbox drawer and moving (ticket 06)

INBOX_VIEW_LIMIT = 200


def inbox_view(limit: Optional[int] = INBOX_VIEW_LIMIT) -> InboxView:
    """The studio's Inbox drawer: one row per unfiled item, newest first (name, "interactive - 2 h"
    style kind and fact, the suggestion chip with its reason, whether Accept applies), the full
    count, and the hint "Drag a row onto a card, or Accept the suggestion.". Reads the store only.
    """
    limit = _limit(limit)
    with store.read() as conn:
        return inboxview.state(conn, limit)


def move_choices(target_id: str) -> MoveChoices:
    """What "Move to..." offers an item (`i_...`: every active project but its own, the Inbox
    included) or "Set parent" offers a project (`p_...`: the top level and every other active
    project), in tree order. Pass the chosen id (None = top level) to `move`.
    """
    with store.read() as conn:
        return inboxview.choices(conn, target_id)
