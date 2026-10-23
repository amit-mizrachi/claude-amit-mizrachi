"""The public Project Studio SDK. Every adapter (MCP server, studio web server, hooks) calls these.

This module IS the contract (studio/sdk/README.md lists it too). Each function:
- opens the store under `$PROJECT_STUDIO_HOME` (default `~/.project-studio`) for one call,
- runs every write in one BEGIN IMMEDIATE transaction,
- returns a structured value from `sdk.results` (serialise it with `sdk.results.to_dict`),
- raises an `sdk.errors.StudioError` subclass whose message is fit to show a person as it is:
  `NotFound`, `InvalidInput`, `Refused` (a rule says no), `ReadOnlyStore` (newer store).

An adapter parses its input, calls ONE of these, and serialises the result. No SQL, ranking or
state rule lives outside `studio/sdk/`. A new agent tool (say `project_status`) is a new
function here plus a few adapter lines.
"""

import json
import os
import tempfile
from typing import Optional

from . import attach, home as homepage, items, model, refresh as scan, server, store
from .errors import InvalidInput
from .results import (AttachResult, DeleteResult, Export, HomeState, InboxList, ItemList, LinkResult, MoveResult, Project,
                      ProjectList, ProjectStatus, PurgeResult, RefreshResult, Rule, RuleList, StudioServer)

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
                  include_archived: bool = False, limit: Optional[int] = None) -> ProjectList:
    """Projects in tree order (the Inbox first, then by path), at most `limit` of them.

    `parent_id` keeps only that project's direct sub-projects; `top_level` keeps only
    top-level projects. Archived projects, and everything under them, are left out unless
    `include_archived`. `total` counts every match before the limit.
    """
    parent_id = _optional_id(parent_id, "parent_id")
    top_level, include_archived = _flag(top_level, "top_level"), _flag(include_archived, "include_archived")
    limit = _limit(limit)
    with store.read() as conn:
        found = model.list_projects(conn, parent_id, top_level, include_archived)
    shown, total, truncated = _page(found, limit)
    return ProjectList(projects=shown, total=total, truncated=truncated)


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


def _maybe_refresh(fresh):
    if _flag(fresh, "refresh"):
        scan.refresh()


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


def project_status(project_id: str, refresh: bool = True) -> ProjectStatus:
    """A project's night runs (each with status, reason, "T03 of 5" progress, stage, PR state and
    artifact), ranked needs-you > blocked > running > paused > latest, plus its sessions, PRs,
    worktrees and artifacts, all rolled up over its active sub-projects, the sub-projects with a
    run count, and every source's state. Refreshes due sources first unless `refresh` is False.
    """
    _maybe_refresh(refresh)
    with store.read() as conn:
        found = items.status(conn, project_id)
    project, runs, sessions, prs, worktrees, artifacts, subs, sources = found
    return ProjectStatus(project=project, runs=runs, sessions=sessions, prs=prs, worktrees=worktrees,
                         artifacts=artifacts, sub_projects=subs, sources=sources)


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

    A project goes under `to_project_id` (None = top level) as `move_project` does; an item goes
    into it as `move_item` does.
    """
    if isinstance(target_id, str) and items.ITEM_ID.match(target_id):
        if to_project_id is None:
            raise InvalidInput("An item needs a project to move into.")
        return move_item(target_id, to_project_id, expected_revision)
    project = move_project(target_id, to_project_id)
    return MoveResult(item=None, project=project, move_id=None, from_project_id=None, to_project_id=to_project_id)


def undo_move(move_id: int) -> MoveResult:
    """Put an item back where `move_id` took it from. Refused when it moved again since."""
    with store.write() as conn:
        return items.undo(conn, move_id)


def remove_item(item_id: str) -> MoveResult:
    """Take an item out of its project, back to the Inbox. It never deletes the thing itself,
    and it stays in the Inbox (placed by hand) until filed again."""
    with store.write() as conn:
        return items.move(conn, item_id, store.INBOX_ID, None)


def inbox(limit: Optional[int] = None, refresh: bool = True) -> InboxList:
    """Every unfiled item, newest first, each with a suggested project and the reason
    ("same run as ...", "rule: ...", "repo shapes-platform: 4 items there"), or none."""
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


def purge_gone(item_id: Optional[str] = None) -> PurgeResult:
    """Delete gone items for good: one (refused if it is not gone), or every gone item."""
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
    """The studio's home page: one card per active top-level project (at most 3 runs of it and its
    sub-projects, ranked needs-you > blocked > running > latest, "+ n earlier runs", "2 inside",
    the newest PR state), cards ordered needs-you, blocked, running, then latest change; plus the
    Inbox count, the PR source age, a banner per failed source (last-good states kept), `loading`
    before the first scan and `first_run` when there is no project. Refreshes due sources first
    only when `refresh` is True.
    """
    _maybe_refresh(refresh)
    with store.read() as conn:
        return homepage.state(conn)


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
