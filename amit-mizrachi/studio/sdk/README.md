# Project Studio SDK

The one layer that holds ALL Project Studio logic. The MCP server (`studio/mcp_server.py`), the
studio web server and the hooks are thin adapters: they parse input, call ONE function of
`sdk.api`, and serialise its result. No SQL, ranking or state rule lives outside `studio/sdk/`
(`studio/tests/test_plugin.py` checks the SQL part).

Stdlib Python 3.9+, no packages. An adapter puts `studio/` on `sys.path` and imports `sdk`.

## Data

- One SQLite file in WAL mode: `$PROJECT_STUDIO_HOME/studio.db`, default `~/.project-studio/`.
- Every write is one `BEGIN IMMEDIATE` transaction, so several processes can share the store.
- `schema_version` holds the schema version. An older store is copied to `backups/` and then
  migrated in one transaction. A store from a newer SDK opens read-only: reads work, writes
  raise `ReadOnlyStore`.
- Schema v1: `projects`, `links`, `items`, `rules`, `moves`, `cache`, `schema_version`
  (see `store.py`). The Inbox is a seeded project with the fixed id `inbox`.

## The contract: `sdk.api`

Every function opens the store for one call and returns a dataclass from `sdk.results`
(`sdk.results.to_dict(value)` makes it JSON-ready). Errors are `sdk.errors.StudioError`
subclasses with a stable `code` and a message fit to show a person as it is.

| Function | Returns | Notes |
|---|---|---|
| `create_project(name, parent_id=None)` | `Project` | Refused under the Inbox or an archived parent, or for an active sibling's name (any case). |
| `list_projects(parent_id=None, top_level=False, include_archived=False, limit=None)` | `ProjectList` | Inbox first, then by path. `total` counts every match; `truncated` says the limit cut some. |
| `get_project(project_id)` | `Project` | Archived or not. |
| `move_project(project_id, new_parent_id=None)` | `Project` | `None` = top level. A cycle is refused as `Can't move <A> into <B>: it is inside <A>.` |
| `link_projects(a_id, b_id)` | `LinkResult` | Symmetric; `created` is False when it already existed. |
| `archive_project(project_id)` | `Project` | Hides it and everything under it from lists. Idempotent. |
| `delete_project(project_id)` | `DeleteResult` | Empty projects only (no sub-projects, no items); otherwise archive. |
| `export_json(dest=None)` | `Export` | The whole store minus the cache; written to `dest` (0600, atomic) when given. |

The Inbox can't be moved, archived, deleted, linked, or hold sub-projects.

| Error | `code` | When |
|---|---|---|
| `NotFound` | `not_found` | No project with that id (a malformed id included). |
| `InvalidInput` | `invalid_input` | Wrong type, empty or over-long name, a limit out of range. |
| `Refused` | `refused` | A rule says no: a cycle, a non-empty delete, the Inbox. |
| `ReadOnlyStore` | `read_only` | The store was written by a newer SDK. |

`Project` fields: `id`, `name`, `parent_id`, `path` (names from the top level down),
`is_inbox`, `archived_at`, `created_at`, `updated_at` (ISO 8601 UTC), `child_count`,
`item_count`, `linked_ids`. Fields may be added; none is renamed or removed.

## Readers

`sdk.readers.workspace` reads night-sprint and night-marathon workspaces (`Sprint`,
`walk_chain`, `tag_state`, `World`, ...). They moved here from `bin/night-watch`, which imports
them back; its drawing and display filter stay in night-watch.
`studio/tests/test_night_watch_parity.py` holds night-watch's output byte-identical.

## Adding an agent tool

1. Add one documented function to `sdk/api.py` with a dataclass return type in `sdk/results.py`.
2. In `studio/mcp_server.py`, add one `TOOLS` entry (strict `inputSchema`, `outputSchema`,
   `annotations`) and one `HANDLERS` line that calls that function.
3. Test the function through `sdk.api` and the tool over stdin/stdout.
