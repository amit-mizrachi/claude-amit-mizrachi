#!/usr/bin/env python3
"""project-studio - a local stdio MCP server over the Project Studio SDK.

Registered in the plugin's .mcp.json as `project-studio`. Each tool parses its arguments, calls
ONE function of `sdk.api`, and returns the result as structured content (and as JSON text for
clients that read only text). All logic, SQL and rules live in `studio/sdk/`; a new tool is one
TOOLS entry plus one HANDLERS line over one SDK function.

Zero dependencies. Python 3.9+. Data in `$PROJECT_STUDIO_HOME`, default `~/.project-studio`.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sdk import api, store  # noqa: E402
from sdk.errors import StudioError  # noqa: E402
from sdk.results import to_dict  # noqa: E402

SERVER_VERSION = "0.1.0"
LIST_DEFAULT, LIST_MAX = 50, 200
PROJECT_ID = {"type": "string", "pattern": "^(inbox|p_[0-9a-f]{12})$"}
ITEM_ID = {"type": "string", "pattern": "^i_[0-9a-f]{12}$"}
NULLABLE_TEXT = {"type": ["string", "null"]}

PROJECT_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "parent_id", "path", "is_inbox", "archived_at", "created_at",
                 "updated_at", "child_count", "item_count", "linked_ids"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "parent_id": {"type": ["string", "null"]},
        "path": {"type": "array", "items": {"type": "string"},
                 "description": "Names from the top level down, this project last."},
        "is_inbox": {"type": "boolean"},
        "archived_at": {"type": ["string", "null"]},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "child_count": {"type": "integer"},
        "item_count": {"type": "integer"},
        "linked_ids": {"type": "array", "items": {"type": "string"}},
    },
}

ITEM_SCHEMA = {
    "type": "object",
    "required": ["id", "kind", "key", "title", "project_id", "project_path", "placed_by", "workspace_item_id",
                 "revision", "status", "gone", "gone_at", "seen_at", "data"],
    "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": list(store.ITEM_KINDS)},
        "key": {"type": "string", "description": "Stable id: session UUID, folder path, URL or owner/repo#n."},
        "title": {"type": "string"},
        "project_id": {"type": "string"},
        "project_path": {"type": "array", "items": {"type": "string"}},
        "placed_by": {"type": "string", "enum": list(store.PLACED_BY)},
        "workspace_item_id": NULLABLE_TEXT,
        "revision": {"type": "integer"},
        "status": {"type": "string", "description": "From the item's reader; \"unknown\" when its source failed."},
        "gone": {"type": "boolean"},
        "gone_at": NULLABLE_TEXT,
        "seen_at": NULLABLE_TEXT,
        "data": {"type": "object"},
        "dismissed": {"type": "boolean", "description": "Hidden from every list by studio_dismiss; nothing deleted."},
        "dismissed_at": NULLABLE_TEXT,
        "done_marked_at": dict(NULLABLE_TEXT, description="When a night run was marked done by studio_mark_done; "
                               "it no longer counts once the run's files changed after it."),
    },
}
NULLABLE_ITEM = dict(ITEM_SCHEMA, type=["object", "null"])
NULLABLE_PROJECT = dict(PROJECT_SCHEMA, type=["object", "null"])
SOURCE_SCHEMA = {
    "type": "object",
    "required": ["source", "key", "ok", "error", "fetched_at", "good_at", "partial"],
    "properties": {"source": {"type": "string"}, "key": {"type": "string"}, "ok": {"type": "boolean"},
                   "error": {"type": "string"}, "fetched_at": NULLABLE_TEXT, "good_at": NULLABLE_TEXT,
                   "partial": {"type": "boolean"}},
}
MOVE_SCHEMA = {
    "type": "object",
    "required": ["item", "project", "move_id", "from_project_id", "to_project_id", "followed", "rule_preview", "created",
                 "message"],
    "properties": {
        "item": NULLABLE_ITEM,
        "project": NULLABLE_PROJECT,
        "move_id": {"type": ["integer", "null"], "description": "The studio page's Undo / learn-a-rule handle; null when nothing moved."},
        "from_project_id": NULLABLE_TEXT,
        "to_project_id": NULLABLE_TEXT,
        "followed": {"type": "array", "items": {"type": "string"},
                     "description": "Auto-attached items that moved with a run."},
        "rule_preview": {"type": ["object", "null"]},
        "created": {"type": "boolean"},
        "message": {"type": "string", "description": "What moved where: \"Moved to Project Studio\"."},
        "kind": {"type": "string", "enum": list(store.MOVE_KINDS),
                 "description": "What the change was: move, dismiss, restore, mark-done, unmark-done or "
                                "remove-project (an undone removal)."},
    },
}
RUN_SCHEMA = {
    "type": "object",
    "required": ["item_id", "kind", "title", "project_id", "status", "reason", "progress", "stage", "stages",
                 "pr", "artifact_url", "started_at", "updated_at", "gone"],
    "properties": {
        "item_id": {"type": "string"},
        "kind": {"type": "string", "enum": ["night-sprint", "night-marathon"]},
        "title": {"type": "string"},
        "project_id": {"type": "string"},
        "status": {"type": "string", "enum": ["needs-you", "blocked", "running", "paused", "pending", "done", "unknown"]},
        "reason": {"type": "string"},
        "progress": {"type": ["object", "null"], "description": "{current, index, total, text: \"T03 of 5\"}"},
        "stage": {"type": "string"},
        "stages": {"type": "array", "items": {"type": "object"}},
        "pr": {"type": ["object", "null"]},
        "artifact_url": {"type": "string"},
        "started_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "gone": {"type": "boolean"},
        "progress_text": {"type": "string", "description": "\"T03 of 5\", \"5 of 5\" once done, or \"\""},
        "pr_text": {"type": "string", "description": "\"PR #12 draft - checks green\", or \"\""},
        "marked_done": {"type": "boolean", "description": "Done because studio_mark_done marked it, not its files "
                        "(reason \"marked done by you\")."},
        "conductor_item_id": dict(NULLABLE_TEXT, description="The session item that conducts the run (set it up, "
                                  "watches its runner); studio_terminal with target conductor opens it. null: unknown."),
    },
}
ITEMS = {"type": "array", "items": ITEM_SCHEMA}
MOVE_ID = {"type": "integer", "minimum": 1, "description": "The move_id a move, add, accept or remove returned."}
RULE_SCHEMA = {
    "type": "object",
    "required": ["id", "project_id", "project_name", "signal", "pattern", "description", "created_at", "created",
                 "parts"],
    "properties": {
        "id": {"type": "string"},
        "project_id": {"type": "string"},
        "project_name": {"type": "string"},
        "signal": {"type": "string", "description": "workspace, repo-branch or cwd: what the rule matches on."},
        "pattern": {"type": "string"},
        "description": {"type": "string", "description": "The rule in words: \"repo shapes-platform, branch eval/*\"."},
        "created_at": {"type": "string"},
        "created": {"type": "boolean", "description": "False when the same rule already existed."},
        "parts": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
    },
}
RULE_ADD_SCHEMA = {
    "type": "object",
    "required": ["preview", "project_id", "project_name", "rule", "dry_run", "created", "matching", "sample", "filed",
                 "message"],
    "properties": {
        "preview": {"type": "object", "required": ["signal", "pattern", "description", "parts"],
                    "description": "The rule as it is stored and shown: sis-* stays sis-*, a branch prefix eval/ "
                                   "becomes eval/*."},
        "project_id": {"type": "string"},
        "project_name": {"type": "string"},
        "rule": dict(RULE_SCHEMA, type=["object", "null"], description="The saved rule; null on a dry run."),
        "dry_run": {"type": "boolean"},
        "created": {"type": "boolean", "description": "False on a dry run or when the same rule was already there."},
        "matching": {"type": "integer", "description": "Inbox items the rule files now."},
        "sample": {"type": "array", "description": "Up to 5 of them, newest first.",
                   "items": {"type": "object", "required": ["item_id", "title", "kind"]}},
        "filed": {"type": "array", "description": "With apply: one move per filed item, move_id for studio_undo.",
                  "items": {"type": "object", "required": ["item_id", "title", "move_id", "followed"]}},
        "message": {"type": "string"},
    },
}
SUGGESTION_SCHEMA = {
    "type": ["object", "null"],
    "required": ["project_id", "project_name", "reason"],
    "properties": {"project_id": {"type": "string"}, "project_name": {"type": "string"},
                   "reason": {"type": "string", "description": "\"same run as ...\", \"rule: ...\", \"repo x: 4 items there\""}},
}

TOOLS = [
    {
        "name": "studio_list",
        "title": "List projects",
        "description": (
            "List Project Studio projects in tree order: the Inbox first, then by path. Each "
            "project has its id, name, parent, path, sub-project and item counts, and linked "
            "project ids. Archived projects are left out unless include_archived is true. The "
            "list is bounded: `total` counts every match and `truncated` says some were cut."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "parent_id": dict(PROJECT_ID, description="Only the direct sub-projects of this project."),
                "top_level": {"type": "boolean", "description": "Only top-level projects. Default false."},
                "include_archived": {"type": "boolean", "description": "Also list archived projects. Default false."},
                "limit": {"type": "integer", "minimum": 1, "maximum": LIST_MAX,
                          "description": "At most this many projects, default %d, max %d." % (LIST_DEFAULT, LIST_MAX)},
            },
        },
        "outputSchema": {
            "type": "object",
            "required": ["projects", "total", "truncated"],
            "properties": {
                "projects": {"type": "array", "items": PROJECT_SCHEMA},
                "total": {"type": "integer"},
                "truncated": {"type": "boolean"},
            },
        },
        "annotations": {"title": "List projects", "readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_create",
        "title": "Create a project",
        "description": (
            "Create a Project Studio project, top-level or under parent_id, and return it. "
            "Refused when the parent is the Inbox or archived, or a sibling already has the name."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["name"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 120, "description": "The project's name."},
                "parent_id": dict(PROJECT_ID, description="Create it under this project. Omit for top level."),
            },
        },
        "outputSchema": PROJECT_SCHEMA,
        "annotations": {"title": "Create a project", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": False, "openWorldHint": False},
    },
    {
        "name": "studio_find",
        "title": "Find items",
        "description": (
            "Find Project Studio items - Claude sessions (bg and interactive), night sprints, night "
            "marathons, artifacts, PRs, worktrees - whose title, key, name, cwd or branch holds "
            "query. Refreshes due sources first. kind keeps one kind; project_id keeps items in that "
            "project or under it. Gone items only with include_gone. Bounded: total and truncated."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "maxLength": 200, "description": "Text to look for, any case."},
                "kind": {"type": "string", "enum": list(store.ITEM_KINDS)},
                "project_id": dict(PROJECT_ID, description="Only items in this project or under it."),
                "include_gone": {"type": "boolean", "description": "Also gone items. Default false."},
                "include_dismissed": {"type": "boolean",
                                      "description": "Also dismissed items (listed last). Default false."},
                "limit": {"type": "integer", "minimum": 1, "maximum": LIST_MAX,
                          "description": "At most this many, default %d, max %d." % (LIST_DEFAULT, LIST_MAX)},
            },
        },
        "outputSchema": {"type": "object", "required": ["items", "total", "truncated"],
                         "properties": {"items": ITEMS, "total": {"type": "integer"}, "truncated": {"type": "boolean"}}},
        "annotations": {"title": "Find items", "readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_status",
        "title": "Project status",
        "description": (
            "A project's night runs (status, reason, progress like \"T03 of 5\", stage, PR state, plan "
            "artifact) ranked needs-you > blocked > running > latest, plus its sessions, PRs, "
            "worktrees and artifacts, rolled up over its sub-projects, and each source's state (a "
            "failed source keeps its last-good data and shows its error). Refreshes due sources first. "
            "Each list holds at most `limit` entries; `totals` counts them all and `truncated` says one was cut."
        ),
        "inputSchema": {"type": "object", "required": ["project_id"], "additionalProperties": False,
                        "properties": {
                            "project_id": PROJECT_ID,
                            "limit": {"type": "integer", "minimum": 1, "maximum": LIST_MAX,
                                      "description": "At most this many of each list, default %d, max %d."
                                                     % (LIST_DEFAULT, LIST_MAX)}}},
        "outputSchema": {
            "type": "object",
            "required": ["project", "runs", "sessions", "prs", "worktrees", "artifacts", "sub_projects", "sources",
                         "totals", "truncated"],
            "properties": {
                "project": PROJECT_SCHEMA,
                "runs": {"type": "array", "items": RUN_SCHEMA},
                "sessions": ITEMS, "prs": ITEMS, "worktrees": ITEMS, "artifacts": ITEMS,
                "sub_projects": {"type": "array", "items": {"type": "object", "required": ["project", "runs", "runs_active", "top_status"],
                                                                "properties": {"text": {"type": "string", "description": "\"no runs\", \"3 runs, 1 active\", \"2 runs done\""}}}},
                "sources": {"type": "array", "items": SOURCE_SCHEMA},
                "totals": {"type": "object", "additionalProperties": {"type": "integer"}},
                "truncated": {"type": "boolean"},
            },
        },
        "annotations": {"title": "Project status", "readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_add",
        "title": "Add an item to a project",
        "description": (
            "File an item into a project by hand; no rule moves it again. key is its stable id: a "
            "session UUID, a folder path (a run, a worktree or an ad-hoc folder), an https URL or file "
            "path for an artifact, owner/repo#n for a PR. A known item is moved there instead."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["kind", "key", "project_id"],
            "additionalProperties": False,
            "properties": {
                "kind": {"type": "string", "enum": list(store.ITEM_KINDS)},
                "key": {"type": "string", "minLength": 1, "maxLength": 1000},
                "project_id": PROJECT_ID,
                "title": {"type": "string", "maxLength": 300, "description": "Shown name. Default: from the key."},
            },
        },
        "outputSchema": MOVE_SCHEMA,
        "annotations": {"title": "Add an item to a project", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_move",
        "title": "Move an item or a project",
        "description": (
            "Move an item (id i_...) into a project, or a project (id p_...) under another (null = top "
            "level). Either returns move_id, the handle studio_undo and the studio page's Undo take; "
            "an item move is by hand and also returns the rule "
            "\"Always file items like this here\" would save; a run's auto-attached items follow it. Pass revision "
            "to refuse the move if the item changed since you read it. Cycles are refused."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["id", "to_project_id"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "pattern": "^(i_[0-9a-f]{12}|p_[0-9a-f]{12})$"},
                "to_project_id": {"type": ["string", "null"], "pattern": PROJECT_ID["pattern"]},
                "revision": {"type": "integer", "minimum": 1, "description": "The item revision you saw."},
            },
        },
        "outputSchema": MOVE_SCHEMA,
        "annotations": {"title": "Move an item or a project", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_link",
        "title": "Link two projects",
        "description": "Link two projects (symmetric, shown as text). Linking twice changes nothing.",
        "inputSchema": {"type": "object", "required": ["a_id", "b_id"], "additionalProperties": False,
                        "properties": {"a_id": PROJECT_ID, "b_id": PROJECT_ID}},
        "outputSchema": {"type": "object", "required": ["a_id", "b_id", "created"],
                         "properties": {"a_id": {"type": "string"}, "b_id": {"type": "string"},
                                        "created": {"type": "boolean"}}},
        "annotations": {"title": "Link two projects", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_unlink",
        "title": "Unlink two projects",
        "description": ("Remove the link between two projects (either order). removed is false, and "
                        "nothing changes, when they were not linked."),
        "inputSchema": {"type": "object", "required": ["a_id", "b_id"], "additionalProperties": False,
                        "properties": {"a_id": PROJECT_ID, "b_id": PROJECT_ID}},
        "outputSchema": {"type": "object", "required": ["a_id", "b_id", "removed"],
                         "properties": {"a_id": {"type": "string"}, "b_id": {"type": "string"},
                                        "removed": {"type": "boolean"}}},
        "annotations": {"title": "Unlink two projects", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_remove",
        "title": "Remove an item from its project",
        "description": (
            "Take an item out of its project, back to the Inbox. It never deletes the session, run, PR "
            "or folder itself. Returns move_id, the handle studio_undo and the studio page's Undo take."
        ),
        "inputSchema": {"type": "object", "required": ["item_id"], "additionalProperties": False,
                        "properties": {"item_id": ITEM_ID}},
        "outputSchema": MOVE_SCHEMA,
        "annotations": {"title": "Remove an item from its project", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_dismiss",
        "title": "Dismiss an item",
        "description": (
            "Hide an item (a night run first of all, or a session, PR, worktree or artifact) from the "
            "studio's cards, project views, Inbox and the list / status counts. It deletes nothing: no "
            "file, session or PR is touched, the item keeps its project, and no refresh brings it back. "
            "A night run's attached sessions, PRs and worktrees are dismissed with it (followed). "
            "studio_find with include_dismissed still finds it; studio_restore or studio_undo with the "
            "returned move_id shows it again."
        ),
        "inputSchema": {"type": "object", "required": ["item_id"], "additionalProperties": False,
                        "properties": {"item_id": ITEM_ID}},
        "outputSchema": MOVE_SCHEMA,
        "annotations": {"title": "Dismiss an item", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_restore",
        "title": "Restore a dismissed item",
        "description": (
            "Show a dismissed item again, with the attached items its dismissal took along. Returns "
            "move_id for studio_undo; move_id is null when the item was not dismissed."
        ),
        "inputSchema": {"type": "object", "required": ["item_id"], "additionalProperties": False,
                        "properties": {"item_id": ITEM_ID}},
        "outputSchema": MOVE_SCHEMA,
        "annotations": {"title": "Restore a dismissed item", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_mark_done",
        "title": "Mark a night run done",
        "description": (
            "Mark a night run (night-sprint or night-marathon item) done when its state files froze on a "
            "word that is no longer true: a BLOCKED a person fixed later, an early \"CI red\" while the PR "
            "is now green. The run then shows status done, reason \"marked done by you\" (marked_done "
            "true) everywhere a run shows, and its stages stay as the files say. It touches no file. If "
            "the run's files change after the mark, the mark is dropped and the files' word wins again. "
            "Any other item kind is refused. Returns move_id for studio_undo; move_id is null when the "
            "run is already marked or already done."
        ),
        "inputSchema": {"type": "object", "required": ["item_id"], "additionalProperties": False,
                        "properties": {"item_id": ITEM_ID}},
        "outputSchema": MOVE_SCHEMA,
        "annotations": {"title": "Mark a night run done", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_archive",
        "title": "Archive a project",
        "description": (
            "Archive a project: it and everything under it leave the lists and get no new "
            "auto-attached items. Nothing is deleted. Archiving twice changes nothing."
        ),
        "inputSchema": {"type": "object", "required": ["project_id"], "additionalProperties": False,
                        "properties": {"project_id": PROJECT_ID}},
        "outputSchema": PROJECT_SCHEMA,
        "annotations": {"title": "Archive a project", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_unarchive",
        "title": "Unarchive a project",
        "description": (
            "Bring an archived project back to the lists, with the sub-projects archived with it (one "
            "archived on its own before stays archived). Unarchiving an active project changes nothing. "
            "Refused inside a project that is still archived, and when an active sibling now has its "
            "name (any case). studio_list with include_archived true shows archived projects' ids."
        ),
        "inputSchema": {"type": "object", "required": ["project_id"], "additionalProperties": False,
                        "properties": {"project_id": PROJECT_ID}},
        "outputSchema": PROJECT_SCHEMA,
        "annotations": {"title": "Unarchive a project", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_rename",
        "title": "Rename a project",
        "description": (
            "Give a project a new name and return it. Refused for the Inbox and when an active sibling "
            "already has the name (any case)."
        ),
        "inputSchema": {"type": "object", "required": ["project_id", "name"], "additionalProperties": False,
                        "properties": {"project_id": PROJECT_ID,
                                       "name": {"type": "string", "minLength": 1, "maxLength": 120,
                                                "description": "The new name."}}},
        "outputSchema": PROJECT_SCHEMA,
        "annotations": {"title": "Rename a project", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_delete",
        "title": "Delete an empty project",
        "description": (
            "Delete an EMPTY project (no sub-projects, no items) for good, with its links and rules. "
            "Without confirmed true it changes nothing and returns needs_confirm and a message saying "
            "what it would delete: show that to the user, and call again confirmed only once they agree. "
            "Refused for the Inbox and for a project that holds anything (archive that instead)."
        ),
        "inputSchema": {"type": "object", "required": ["project_id"], "additionalProperties": False,
                        "properties": {"project_id": PROJECT_ID,
                                       "confirmed": {"type": "boolean",
                                                     "description": "Really delete it. Default false: only say what it would delete."}}},
        "outputSchema": {
            "type": "object",
            "required": ["id", "name", "deleted", "needs_confirm", "links", "rules", "message"],
            "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "deleted": {"type": "boolean"},
                           "needs_confirm": {"type": "boolean", "description": "True when nothing changed: ask, then call again confirmed."},
                           "links": {"type": "integer"}, "rules": {"type": "integer"},
                           "message": {"type": "string"}},
        },
        "annotations": {"title": "Delete an empty project", "readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": False, "openWorldHint": False},
    },
    {
        "name": "studio_remove_project",
        "title": "Remove a project and move what it holds up",
        "description": (
            "Remove a project that may still hold things (studio_delete is for empty ones). Its night "
            "runs and other items move to its parent project (a top-level project's go to the Inbox) "
            "and its sub-projects move up to the parent (or the top level), each recorded as a move; "
            "its links and rules go; then the project is deleted. No session, folder or PR is touched. "
            "confirm is required: with confirm false it changes nothing and returns needs_confirm and "
            "a message listing what is inside and where each part goes - show that to the user, and "
            "call again with confirm true only once they agree. The result's move_id is one "
            "studio_undo handle that brings the project back (same id, name and parent) with "
            "everything in it. Refused for the Inbox, an archived project, and a sub-project that "
            "would land next to an active project of its name."
        ),
        "inputSchema": {"type": "object", "required": ["project_id", "confirm"], "additionalProperties": False,
                        "properties": {"project_id": PROJECT_ID,
                                       "confirm": {"type": "boolean",
                                                   "description": "Really remove it. false: only say what would move where."}}},
        "outputSchema": {
            "type": "object",
            "required": ["id", "name", "parent_id", "to_project_id", "to_name", "sub_projects", "runs", "run_titles",
                         "items", "removed", "needs_confirm", "move_id", "message"],
            "properties": {
                "id": {"type": "string"}, "name": {"type": "string"},
                "parent_id": dict(NULLABLE_TEXT, description="Where the sub-projects go; null: the top level."),
                "to_project_id": {"type": "string", "description": "Where the runs and items go: the parent, or inbox."},
                "to_name": {"type": "string"},
                "sub_projects": {"type": "array", "items": {"type": "object", "required": ["id", "name"],
                                                            "properties": {"id": {"type": "string"},
                                                                           "name": {"type": "string"}}}},
                "runs": {"type": "integer", "description": "Night runs that move."},
                "run_titles": {"type": "array", "items": {"type": "string"}, "description": "Up to 5 of them."},
                "items": {"type": "integer", "description": "Other items that move (sessions, PRs, worktrees, artifacts)."},
                "removed": {"type": "boolean"},
                "needs_confirm": {"type": "boolean", "description": "True when nothing changed: ask, then call again with confirm true."},
                "move_id": {"type": ["integer", "null"], "description": "studio_undo's handle once removed; null before."},
                "message": {"type": "string"},
            },
        },
        "annotations": {"title": "Remove a project", "readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": False, "openWorldHint": False},
    },
    {
        "name": "studio_undo",
        "title": "Undo a move",
        "description": (
            "Put back what a move did (studio_move, studio_add, studio_accept, studio_remove, an item's or "
            "a project's): the item or project goes back where move_id took it from. A studio_dismiss "
            "move is undone by restoring the item, a studio_restore move by dismissing it again, a "
            "studio_mark_done move by taking the mark back, a studio_remove_project move by bringing "
            "the project back (same id, name and parent) with everything that was in it. Refused "
            "when it changed again since."
        ),
        "inputSchema": {"type": "object", "required": ["move_id"], "additionalProperties": False,
                        "properties": {"move_id": MOVE_ID}},
        "outputSchema": MOVE_SCHEMA,
        "annotations": {"title": "Undo a move", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": False, "openWorldHint": False},
    },
    {
        "name": "studio_rules",
        "title": "List filing rules",
        "description": (
            "The filing rules (\"Always file items like this here\"), strongest signal first: workspace "
            "slug > repo + branch prefix > cwd prefix. project_id keeps one project's rules."
        ),
        "inputSchema": {"type": "object", "additionalProperties": False,
                        "properties": {"project_id": dict(PROJECT_ID, description="Only this project's rules.")}},
        "outputSchema": {"type": "object", "required": ["rules", "total"],
                         "properties": {"rules": {"type": "array", "items": RULE_SCHEMA},
                                        "total": {"type": "integer"}}},
        "annotations": {"title": "List filing rules", "readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_rule_save",
        "title": "Save a filing rule from a move",
        "description": (
            "\"Always file items like this here\": save a rule from the moved item's strongest signal into "
            "the project the move took it to. The next refresh files matching new and Inbox items there. "
            "Saving the same rule twice returns the existing one (created false). Refused for a project's "
            "move and a move into the Inbox."
        ),
        "inputSchema": {"type": "object", "required": ["move_id"], "additionalProperties": False,
                        "properties": {"move_id": MOVE_ID}},
        "outputSchema": RULE_SCHEMA,
        "annotations": {"title": "Save a filing rule from a move", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_rule_add",
        "title": "Write a filing rule by pattern",
        "description": (
            "Write a filing rule directly, not from a move: file what pattern matches on signal into "
            "project_id. signal workspace: a glob on a run's slug (\"sis-*\"; \"*\" alone is refused). "
            "repo-branch: \"<repo>\" or \"<repo> <branch prefix>\" (\"shapes-platform eval/\"; the repo "
            "is matched exactly, no branch means every branch). cwd: an absolute folder and everything under "
            "it (\"/\" and the home folder are refused). It ranks and matches exactly like a learned rule: "
            "workspace > repo-branch > cwd, newest first. Returns matching, the Inbox items it files now, with "
            "a sample of up to 5. dry_run true saves and files nothing: call it first and show the count. "
            "apply true also files each matching Inbox item now, one move_id each for studio_undo; items filed "
            "elsewhere are left alone. Writing the same rule twice keeps the one there (created false)."
        ),
        "inputSchema": {"type": "object", "required": ["project_id", "signal", "pattern"], "additionalProperties": False,
                        "properties": {
                            "project_id": dict(PROJECT_ID, description="The project the rule files into (not the Inbox)."),
                            "signal": {"type": "string", "enum": ["workspace", "repo-branch", "cwd"]},
                            "pattern": {"type": "string", "minLength": 1, "maxLength": 300,
                                        "description": "sis-*, shapes-platform eval/, or /Users/me/work/shapes."},
                            "apply": {"type": "boolean", "description": "Also file the matching Inbox items now."},
                            "dry_run": {"type": "boolean", "description": "Say what it would file; save nothing."}}},
        "outputSchema": RULE_ADD_SCHEMA,
        "annotations": {"title": "Write a filing rule by pattern", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_rule_delete",
        "title": "Delete a filing rule",
        "description": "Delete one rule (ids from studio_rules) and return it. Items it filed stay where they are.",
        "inputSchema": {"type": "object", "required": ["rule_id"], "additionalProperties": False,
                        "properties": {"rule_id": {"type": "string", "pattern": "^r_[0-9a-f]{12}$"}}},
        "outputSchema": RULE_SCHEMA,
        "annotations": {"title": "Delete a filing rule", "readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_inbox",
        "title": "List the Inbox",
        "description": (
            "Every unfiled item active in the last 14 days, newest first, each with a suggested project "
            "and its reason, or suggestion null. Refreshes due sources first. Bounded: total and truncated."
        ),
        "inputSchema": {"type": "object", "additionalProperties": False,
                        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": LIST_MAX,
                                                 "description": "At most this many, default %d, max %d."
                                                                % (LIST_DEFAULT, LIST_MAX)}}},
        "outputSchema": {
            "type": "object",
            "required": ["entries", "total", "truncated"],
            "properties": {
                "entries": {"type": "array", "items": {"type": "object", "required": ["item", "suggestion"],
                                                       "properties": {"item": ITEM_SCHEMA,
                                                                      "suggestion": SUGGESTION_SCHEMA}}},
                "total": {"type": "integer"},
                "truncated": {"type": "boolean"},
            },
        },
        "annotations": {"title": "List the Inbox", "readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_accept",
        "title": "Accept an Inbox suggestion",
        "description": (
            "File an Inbox item into the project studio_inbox suggests for it, as a move by hand. Returns "
            "move_id for studio_undo and studio_rule_save. Refused when the item has no suggestion."
        ),
        "inputSchema": {"type": "object", "required": ["item_id"], "additionalProperties": False,
                        "properties": {"item_id": ITEM_ID}},
        "outputSchema": MOVE_SCHEMA,
        "annotations": {"title": "Accept an Inbox suggestion", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_purge",
        "title": "Purge gone items",
        "description": (
            "Delete gone items from the store for good (a gone item's session, run or folder no longer "
            "exists). Give item_id for one gone item (refused if it is not gone), or all_gone true for "
            "every gone item; with neither it is refused. It never touches the thing itself."
        ),
        "inputSchema": {"type": "object", "additionalProperties": False,
                        "properties": {"item_id": ITEM_ID,
                                       "all_gone": {"type": "boolean",
                                                    "description": "Purge every gone item. Needed when item_id is left out."}}},
        "outputSchema": {"type": "object", "required": ["ids", "count"],
                         "properties": {"ids": {"type": "array", "items": {"type": "string"}},
                                        "count": {"type": "integer"}}},
        "annotations": {"title": "Purge gone items", "readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "studio_throw_away",
        "title": "Throw away a night run",
        "description": (
            "The ONE studio action that removes things. Throws away a night run: its workspace folder "
            "goes to the macOS Trash (recoverable), each of its worktrees is removed with git worktree "
            "remove (never forced: a worktree with changes is refused, every branch and its commits "
            "stay; gitignored files in a worktree are not changes to git and are deleted for good, "
            "each worktree's ignored lists them), then the run and its attached items are purged "
            "from the studio. confirm is "
            "required: with confirm false it changes nothing and returns needs_confirm and a message "
            "listing what would go - show that to the user, and call again with confirm true only "
            "once they agree. Refused before anything happens for a run that is still running or has "
            "a live session (the studio never stops one), and for a folder outside the run roots. A "
            "step that fails stops the rest; the error says what was done and what was not."
        ),
        "inputSchema": {"type": "object", "required": ["item_id", "confirm"], "additionalProperties": False,
                        "properties": {"item_id": ITEM_ID,
                                       "confirm": {"type": "boolean",
                                                   "description": "Really throw it away. false: only say what would go."}}},
        "outputSchema": {
            "type": "object",
            "required": ["item_id", "title", "folder", "worktrees", "items", "thrown", "needs_confirm", "message", "done"],
            "properties": {
                "item_id": {"type": "string"}, "title": {"type": "string"},
                "folder": {"type": "string", "description": "The folder that goes to the Trash; empty when it is no longer on this Mac."},
                "worktrees": {"type": "array", "items": {"type": "object", "required": ["path", "repo_path", "branch"],
                                                         "properties": {"path": {"type": "string"},
                                                                        "repo_path": {"type": "string"},
                                                                        "branch": {"type": "string"},
                                                                        "ignored": {"type": "array",
                                                                                    "items": {"type": "string"}}}}},
                "items": {"type": "integer", "description": "Attached items purged with the run."},
                "thrown": {"type": "boolean"},
                "needs_confirm": {"type": "boolean", "description": "True when nothing changed: ask, then call again with confirm true."},
                "message": {"type": "string"},
                "done": {"type": "array", "items": {"type": "string"}},
            },
        },
        "annotations": {"title": "Throw away a night run", "readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "studio_terminal",
        "title": "Open a session in the terminal",
        "description": (
            "Open a session again in the user's terminal app (the studio's terminal setting): claude attach "
            "<short id> when claude agents lists it, else cd <its folder> && claude --resume <id>. item_id is "
            "a session, or a night run: target session (the default) opens its live ticket session, target "
            "conductor its conductor session (conductor_item_id in studio_status), e.g. the one waiting for "
            "the user's picks at a plan gate. A session whose transcript changed in the last 5 minutes may be "
            "open elsewhere: with confirm false nothing runs and needs_confirm comes back; ask, then call "
            "again with confirm true. When the app does not open, the command is copied. Never stops, kills "
            "or removes a session."
        ),
        "inputSchema": {"type": "object", "required": ["item_id"], "additionalProperties": False,
                        "properties": {"item_id": ITEM_ID,
                                       "target": {"type": "string", "enum": ["session", "conductor"],
                                                  "description": "For a night run: its live ticket session "
                                                                 "(default) or its conductor."},
                                       "confirm": {"type": "boolean",
                                                   "description": "Open it even when it may be open elsewhere."}}},
        "outputSchema": {
            "type": "object",
            "required": ["command", "opened", "copied", "needs_confirm", "path", "message", "app"],
            "properties": {
                "command": {"type": "object", "required": ["item_id", "mode", "command", "session_id", "short", "cwd",
                                                           "confirm"],
                            "properties": {"item_id": {"type": "string"}, "mode": {"type": "string",
                                                                                   "enum": ["attach", "resume"]},
                                           "command": {"type": "string"}, "session_id": {"type": "string"},
                                           "short": {"type": "string"}, "cwd": {"type": "string"},
                                           "confirm": {"type": "string"}}},
                "opened": {"type": "boolean"}, "copied": {"type": "boolean"},
                "needs_confirm": {"type": "boolean", "description": "True when nothing ran: ask, then call again with confirm true."},
                "path": NULLABLE_TEXT, "message": {"type": "string"}, "app": {"type": "string"},
            },
        },
        "annotations": {"title": "Open a session in the terminal", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "studio_open",
        "title": "Open the studio",
        "description": (
            "Make sure the Project Studio web page runs on this Mac and return its URL (127.0.0.1 only). "
            "A running studio of the same version is reused; an older one is restarted. It does not open "
            "a browser: give the user the URL, or tell them to run `project-studio` in a terminal."
        ),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
        "outputSchema": {"type": "object", "required": ["url", "pid", "port", "version", "running", "started"],
                         "properties": {"url": {"type": "string"}, "pid": {"type": "integer"},
                                        "port": {"type": "integer"}, "version": {"type": "string"},
                                        "running": {"type": "boolean"},
                                        "started": {"type": "boolean",
                                                    "description": "True when this call started it."}}},
        "annotations": {"title": "Open the studio", "readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
]


def tool_list(args):
    return api.list_projects(parent_id=args.get("parent_id"), top_level=args.get("top_level", False),
                             include_archived=args.get("include_archived", False),
                             limit=args.get("limit", LIST_DEFAULT))


def tool_create(args):
    return api.create_project(args["name"], parent_id=args.get("parent_id"))


def tool_find(args):
    return api.find_items(query=args.get("query"), kind=args.get("kind"), project_id=args.get("project_id"),
                          include_gone=args.get("include_gone", False), limit=args.get("limit", LIST_DEFAULT),
                          include_dismissed=args.get("include_dismissed", False))


def tool_status(args):
    return api.project_status(args["project_id"], limit=args.get("limit", LIST_DEFAULT))


def tool_add(args):
    return api.add_item(args["kind"], args["key"], args["project_id"], title=args.get("title"))


def tool_move(args):
    return api.move(args["id"], args["to_project_id"], expected_revision=args.get("revision"))


def tool_link(args):
    return api.link_projects(args["a_id"], args["b_id"])


def tool_unlink(args):
    return api.unlink_projects(args["a_id"], args["b_id"])


def tool_remove(args):
    return api.remove_item(args["item_id"])


def tool_dismiss(args):
    return api.dismiss_item(args["item_id"])


def tool_restore(args):
    return api.restore_item(args["item_id"])


def tool_mark_done(args):
    return api.mark_done(args["item_id"])


def tool_archive(args):
    return api.archive_project(args["project_id"])


def tool_unarchive(args):
    return api.unarchive_project(args["project_id"])


def tool_rename(args):
    return api.rename_project(args["project_id"], args["name"])


def tool_delete(args):
    return api.delete_project_guarded(args["project_id"], confirmed=args.get("confirmed", False))


def tool_remove_project(args):
    return api.remove_project(args["project_id"], confirmed=args["confirm"])


def tool_undo(args):
    return api.undo_move(args["move_id"])


def tool_rules(args):
    return api.list_rules(args.get("project_id"))


def tool_rule_save(args):
    return api.save_rule_from_move(args["move_id"])


def tool_rule_add(args):
    return api.add_rule(args["project_id"], args["signal"], args["pattern"], apply=args.get("apply", False),
                        dry_run=args.get("dry_run", False))


def tool_rule_delete(args):
    return api.delete_rule(args["rule_id"])


def tool_inbox(args):
    return api.inbox(limit=args.get("limit", LIST_DEFAULT))


def tool_accept(args):
    return api.accept_suggestion(args["item_id"])


def tool_purge(args):
    return api.purge_gone(args.get("item_id"), all_gone=args.get("all_gone", False))


def tool_throw_away(args):
    return api.throw_away(args["item_id"], confirmed=args["confirm"])


def tool_terminal(args):
    return api.open_in_terminal(args["item_id"], confirmed=args.get("confirm", False),
                                target=args.get("target", "session"))


def tool_open(args):
    return api.open_studio()


HANDLERS = {
    "studio_list": tool_list,
    "studio_create": tool_create,
    "studio_find": tool_find,
    "studio_status": tool_status,
    "studio_add": tool_add,
    "studio_move": tool_move,
    "studio_link": tool_link,
    "studio_unlink": tool_unlink,
    "studio_remove": tool_remove,
    "studio_dismiss": tool_dismiss,
    "studio_restore": tool_restore,
    "studio_mark_done": tool_mark_done,
    "studio_archive": tool_archive,
    "studio_unarchive": tool_unarchive,
    "studio_rename": tool_rename,
    "studio_delete": tool_delete,
    "studio_remove_project": tool_remove_project,
    "studio_undo": tool_undo,
    "studio_rules": tool_rules,
    "studio_rule_save": tool_rule_save,
    "studio_rule_add": tool_rule_add,
    "studio_rule_delete": tool_rule_delete,
    "studio_inbox": tool_inbox,
    "studio_accept": tool_accept,
    "studio_purge": tool_purge,
    "studio_throw_away": tool_throw_away,
    "studio_terminal": tool_terminal,
    "studio_open": tool_open,
}
SCHEMAS = {t["name"]: t["inputSchema"] for t in TOOLS}


# --------------------------------------------------------------------------- #
# MCP plumbing (JSON-RPC 2.0 over stdio, line delimited) - the codex-bridge pattern
# --------------------------------------------------------------------------- #

def log(msg):
    sys.stderr.write("[project-studio] %s\n" % msg)
    sys.stderr.flush()


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def bad_args(name, args):
    """A message when `args` breaks the tool's inputSchema shape (unknown or missing keys), else ''."""
    if not isinstance(args, dict):
        return "arguments must be an object"
    schema = SCHEMAS[name]
    unknown = sorted(set(args) - set(schema["properties"]))
    if unknown:
        return "unknown argument(s): %s" % ", ".join(unknown)
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        return "missing argument(s): %s" % ", ".join(missing)
    return ""


def tool_error(text):
    return {"content": [{"type": "text", "text": text}], "isError": True}


class InvalidParams(ValueError):
    """A request the server can name as bad (JSON-RPC -32602), not an internal failure."""


def call_tool(name, args):
    fn = HANDLERS.get(name)
    if not fn:
        raise InvalidParams("unknown tool %r" % (name,))
    problem = bad_args(name, args)
    if problem:
        return tool_error("invalid_input: " + problem)
    try:
        result = to_dict(fn(args))
    except StudioError as exc:
        return tool_error("%s: %s" % (exc.code, exc))
    except Exception as exc:  # surface as a tool error, not a protocol error
        log("tool %s failed: %r" % (name, exc))
        return tool_error("project-studio error: %s" % exc)
    return {"content": [{"type": "text", "text": json.dumps(result, sort_keys=True)}],
            "structuredContent": result}


def handle(req):
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "project-studio", "version": SERVER_VERSION},
            "instructions": (
                "Project Studio keeps Amit's projects as a tree, with an Inbox for unfiled items. "
                "Every Claude session, night sprint, night marathon, artifact, PR and worktree is an "
                "item with one home project. studio_list lists projects, studio_status shows a "
                "project's night runs and items, studio_find finds items, studio_inbox lists unfiled items "
                "with a suggestion each. studio_create / studio_rename / studio_add / studio_move / "
                "studio_accept / studio_link / studio_unlink / studio_remove / studio_archive / "
                "studio_unarchive / studio_delete change the tree; studio_dismiss hides an item (a night run with its attached items) from every list "
                "without deleting anything, studio_restore shows it again; studio_mark_done marks a night run "
                "whose state files froze on a stale word done; studio_undo takes a move_id back; "
                "studio_rules / studio_rule_save / "
                "studio_rule_delete manage filing rules; studio_purge drops gone items. studio_delete and "
                "studio_purge are destructive: studio_delete only says what it would delete until called "
                "confirmed, so ask the user first. studio_open "
                "starts the studio web page and returns its URL (give it to the user). Status "
                "\"unknown\" means a source failed: never report such an item as gone. Messages in "
                "tool errors are meant for the user as they are."
            ),
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        return call_tool(params.get("name"), params.get("arguments") or {})
    if rid is None:
        return None
    raise LookupError("method not found: %s" % method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if not isinstance(req, dict):
            continue
        rid = req.get("id")
        try:
            result = handle(req)
        except LookupError as exc:
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": str(exc)}})
            continue
        except InvalidParams as exc:
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": str(exc)}})
            continue
        except Exception as exc:
            log("request failed: %r" % exc)
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(exc)}})
            continue
        if rid is not None and result is not None:
            send({"jsonrpc": "2.0", "id": rid, "result": result})


if __name__ == "__main__":
    main()
