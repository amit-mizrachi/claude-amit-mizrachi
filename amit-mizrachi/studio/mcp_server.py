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

from sdk import api  # noqa: E402
from sdk.errors import StudioError  # noqa: E402
from sdk.results import to_dict  # noqa: E402

SERVER_VERSION = "0.1.0"
LIST_DEFAULT, LIST_MAX = 50, 200
PROJECT_ID = {"type": "string", "pattern": "^(inbox|p_[0-9a-f]{12})$"}

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
]


def tool_list(args):
    return api.list_projects(parent_id=args.get("parent_id"), top_level=args.get("top_level", False),
                             include_archived=args.get("include_archived", False),
                             limit=args.get("limit", LIST_DEFAULT))


def tool_create(args):
    return api.create_project(args["name"], parent_id=args.get("parent_id"))


HANDLERS = {
    "studio_list": tool_list,
    "studio_create": tool_create,
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
                "studio_list lists projects (bounded), studio_create makes one. Messages in tool "
                "errors are meant for the user as they are."
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
