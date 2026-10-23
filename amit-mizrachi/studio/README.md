# Project Studio

One place for everything Claude runs for you on this Mac: your projects as a tree, and in each
project its night sprints, night marathons, Claude sessions (background and interactive),
artifacts, PRs and worktrees. Every such thing is an **item** with exactly one **home project**;
what the studio cannot place yet waits in the **Inbox**. Moving an item is how you file it, and
"Always file items like this here" turns a move into a **rule** for the next one.

Three ways in, all over the same data:

| Way in | Who uses it | Where |
|---|---|---|
| `project-studio` | you, in a browser | `bin/project-studio`, `studio/web.py`, `studio/static/` |
| the `project-studio` MCP server (`studio_*` tools) | agents | `studio/mcp_server.py`, registered in `.mcp.json` |
| the SessionStart hook | every new session, silently | `hooks/attach-session.sh` -> `studio/session_hook.py` |

All three are thin adapters. ALL logic - the tree, placement, readers, the cache, rules, what a
card or a row shows - lives in the SDK, `studio/sdk/`, and each adapter parses its input, calls
ONE function of `sdk.api`, and serialises the result. The SDK's full contract (every function,
its return type, its errors, the placement rules and the readers) is in
[`sdk/README.md`](sdk/README.md).

Stdlib Python 3.9+ and bash. No packages, no build step.

## `project-studio`

```
project-studio            same as `open`
project-studio open       start the studio if it is not running (or restart an older version), open it
project-studio status     say whether it runs, and where
project-studio stop       ask the running studio to stop
```

The studio is a local web server on `127.0.0.1` only. The home page is a grid of project cards
that show only each project's night-run status; a click on a card opens the project view
(runs, sessions, everything else), where a session row's **Open in Terminal** opens Terminal on
`claude attach <id>` (a background session) or `cd <cwd> && claude --resume <id>` (an
interactive one), or copies that command. The **Inbox** drawer files items by drag, by **Move
to...** or by **Accept** on a suggestion, with **Undo** on every move. Light and dark mode follow
the OS, with a manual toggle. The studio never stops, kills or removes a session.

It stops by itself after 30 minutes with no open page (`PROJECT_STUDIO_IDLE` seconds). It
listens on `PROJECT_STUDIO_PORT`, else a free port. Inside Claude Code the plugin's `bin/` is on
`PATH`; for your own terminals the plugin's `SessionStart` hook (`hooks/link-night-watch.sh`)
links `project-studio` next to `night-watch`.

## The MCP tools

Registered from the plugin's `.mcp.json` as `project-studio` (`plugin:amit-mizrachi:project-studio`).
Each tool is one SDK call:

| Tool | SDK function | Reads or writes |
|---|---|---|
| `studio_list` | `api.list_projects(parent_id, top_level, include_archived, limit)` | reads |
| `studio_create` | `api.create_project(name, parent_id)` | writes |
| `studio_find` | `api.find_items(query, kind, project_id, include_gone, limit)` | reads (refreshes due sources) |
| `studio_status` | `api.project_status(project_id)` | reads (refreshes due sources) |
| `studio_add` | `api.add_item(kind, key, project_id, title)` | writes |
| `studio_move` | `api.move(id, to_project_id, expected_revision=revision)` | writes; an item (`i_...`) or a project (`p_...`) |
| `studio_link` | `api.link_projects(a_id, b_id)` | writes |
| `studio_remove` | `api.remove_item(item_id)` | writes; back to the Inbox, never deletes the thing |
| `studio_archive` | `api.archive_project(project_id)` | writes |
| `studio_open` | `api.open_studio()` | starts the web page, returns its URL |

Every tool has a strict `inputSchema` (no unknown keys), an `outputSchema`, and annotations. A
result comes back as `structuredContent` and as the same JSON in a text block. An SDK refusal
(`Refused`, `NotFound`, `InvalidInput`, `ReadOnlyStore`) comes back as a tool error,
`<code>: <message>`, whose message is fit to show the user as it is. A status of `unknown` means
that item's source failed to read: never report such an item as gone.

## Data

- `$PROJECT_STUDIO_HOME`, default `~/.project-studio/`:
  - `studio.db` - one SQLite file in WAL mode. Every write is one `BEGIN IMMEDIATE` transaction,
    so the MCP servers of several sessions, the web server and the hook share it safely.
  - `backups/` - a copy of the store before each schema migration.
  - `server.json` (0600) - the running web server's pid, port, version and token.
  - `studio.log` - the web server's log.
  - `open/` - the `.command` files Open in Terminal writes.
- Nothing is purged by itself. An item whose source no longer lists it is marked gone (and keeps
  its home); `api.purge_gone()` deletes gone items only when asked. `api.export_json(dest)` writes
  the whole store as JSON.
- Readers: `PROJECT_STUDIO_ROOTS` (else `NIGHT_WATCH_ROOTS`) for night-run workspaces,
  `PROJECT_STUDIO_CLAUDE_HOME` (default `~/.claude`) for jobs and transcripts, and `claude`,
  `git` and `gh` on `PATH`. A failed read keeps the last-good data and shows a banner; only a
  complete read ever marks an item gone.

## Adding an agent tool

New tools (`list_project`, `project_status`, ...) are a few lines each, because the logic they
need is an SDK function first. Say you want an agent to read the Inbox:

1. **The SDK function.** If `sdk/api.py` has none that answers the question, add one: a
   docstring, typed arguments, and a dataclass return type in `sdk/results.py`. All logic, SQL
   and rules go here, never in the adapter. Here `api.inbox(limit=None, refresh=True)` already
   exists and returns `InboxList`.
2. **The tool.** In `studio/mcp_server.py`, add one `TOOLS` entry and one handler:

   ```python
   {
       "name": "studio_inbox",
       "title": "List the Inbox",
       "description": "Every unfiled item, newest first, each with a suggested project and why.",
       "inputSchema": {"type": "object", "additionalProperties": False,
                       "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": LIST_MAX}}},
       "outputSchema": {"type": "object", "required": ["entries", "total", "truncated"],
                        "properties": {"entries": {"type": "array"}, "total": {"type": "integer"},
                                       "truncated": {"type": "boolean"}}},
       "annotations": {"title": "List the Inbox", "readOnlyHint": True, "destructiveHint": False,
                       "idempotentHint": True, "openWorldHint": False},
   },


   def tool_inbox(args):
       return api.inbox(limit=args.get("limit", LIST_DEFAULT))
   ```

   and `"studio_inbox": tool_inbox,` in `HANDLERS`. The plumbing (argument checks against the
   schema, `to_dict`, errors as tool errors) is shared; do not repeat it.
3. **The tests.** The function through `sdk.api` (as in `tests/test_api_items.py`), and the tool
   over stdin/stdout with its output checked against its `outputSchema`
   (`tests/test_mcp_server.py`, `support.validate`). Add the name to the tool set in
   `test_initialize_and_tools_list_show_schemas_and_annotations`. `tests/test_plugin.py` fails if
   a handler does more than call one SDK function, or if SQL appears outside `sdk/`.

The same function then serves the web page too: a route in `studio/web.py` is one line in
`ACTIONS` (POST) or one branch in `do_GET`.

## Tests

stdlib `unittest`, from the repo root:

```
python3 -m unittest discover -s amit-mizrachi/studio/tests -t .
```

Each test gets its own `PROJECT_STUDIO_HOME` and fixture folders, with `claude` and `gh` stubbed
on `PATH` (`tests/stubs/`), so no test reads this Mac. `tests/test_integration.py` drives the
pieces together as real processes: two MCP servers and the web server writing at once with no
lost update, the hook never blocking a session start (even with the store locked), night-watch's
board unchanged on the final tree, a reconnecting page getting a full state, a stale Undo
refused, and a failed source never marking an item gone. Run one file by name with
`-p test_integration.py`.
