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
    "required": ["item", "project", "move_id", "from_project_id", "to_project_id", "followed", "rule_preview", "created"],
    "properties": {
        "item": NULLABLE_ITEM,
        "project": NULLABLE_PROJECT,
        "move_id": {"type": ["integer", "null"], "description": "Undo / learn-a-rule handle; null when nothing moved."},
        "from_project_id": NULLABLE_TEXT,
        "to_project_id": NULLABLE_TEXT,
        "followed": {"type": "array", "items": {"type": "string"},
                     "description": "Auto-attached items that moved with a run."},
        "rule_preview": {"type": ["object", "null"]},
        "created": {"type": "boolean"},
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
    },
}
ITEMS = {"type": "array", "items": ITEM_SCHEMA}

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
            "failed source keeps its last-good data and shows its error). Refreshes due sources first."
        ),
        "inputSchema": {"type": "object", "required": ["project_id"], "additionalProperties": False,
                        "properties": {"project_id": PROJECT_ID}},
        "outputSchema": {
            "type": "object",
            "required": ["project", "runs", "sessions", "prs", "worktrees", "artifacts", "sub_projects", "sources"],
            "properties": {
                "project": PROJECT_SCHEMA,
                "runs": {"type": "array", "items": RUN_SCHEMA},
                "sessions": ITEMS, "prs": ITEMS, "worktrees": ITEMS, "artifacts": ITEMS,
                "sub_projects": {"type": "array", "items": {"type": "object", "required": ["project", "runs", "runs_active", "top_status"]}},
                "sources": {"type": "array", "items": SOURCE_SCHEMA},
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
            "level). An item move is by hand and returns move_id (for Undo) and the rule \"Always file "
            "items like this here\" would save; a run's auto-attached items follow it. Pass revision "
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
        "name": "studio_remove",
        "title": "Remove an item from its project",
        "description": (
            "Take an item out of its project, back to the Inbox. It never deletes the session, run, PR "
            "or folder itself. Returns move_id, so it can be undone."
        ),
        "inputSchema": {"type": "object", "required": ["item_id"], "additionalProperties": False,
                        "properties": {"item_id": ITEM_ID}},
        "outputSchema": MOVE_SCHEMA,
        "annotations": {"title": "Remove an item from its project", "readOnlyHint": False, "destructiveHint": False,
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
                          include_gone=args.get("include_gone", False), limit=args.get("limit", LIST_DEFAULT))


def tool_status(args):
    return api.project_status(args["project_id"])


def tool_add(args):
    return api.add_item(args["kind"], args["key"], args["project_id"], title=args.get("title"))


def tool_move(args):
    return api.move(args["id"], args["to_project_id"], expected_revision=args.get("revision"))


def tool_link(args):
    return api.link_projects(args["a_id"], args["b_id"])


def tool_remove(args):
    return api.remove_item(args["item_id"])


def tool_archive(args):
    return api.archive_project(args["project_id"])


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
    "studio_remove": tool_remove,
    "studio_archive": tool_archive,
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


def call_tool(name, args):
    fn = HANDLERS.get(name)
    if not fn:
        raise ValueError("unknown tool %r" % (name,))
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
                "project's night runs and items, studio_find finds items, studio_create / studio_add / "
                "studio_move / studio_link / studio_remove / studio_archive change the tree. studio_open "
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
        except Exception as exc:
            log("request failed: %r" % exc)
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(exc)}})
            continue
        if rid is not None and result is not None:
            send({"jsonrpc": "2.0", "id": rid, "result": result})


if __name__ == "__main__":
    main()
