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

from . import model, store
from .errors import InvalidInput
from .results import DeleteResult, Export, LinkResult, Project, ProjectList

MAX_LIST_LIMIT = 1000


def _optional_id(value, name):
    if value is not None and not isinstance(value, str):
        raise InvalidInput("%s must be a project id or null." % name)
    return value or None


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
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIST_LIMIT):
        raise InvalidInput("limit must be a whole number from 1 to %d." % MAX_LIST_LIMIT)
    with store.read() as conn:
        found = model.list_projects(conn, parent_id, top_level, include_archived)
    shown = found[:limit] if limit else found
    return ProjectList(projects=shown, total=len(found), truncated=len(shown) < len(found))


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
