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

| `refresh(force=False)` | `RefreshResult` | Runs the due readers, stores what they said, reconciles. `sources` shows each reader's state. |
| `find_items(query=None, kind=None, project_id=None, include_gone=False, limit=None, refresh=True)` | `ItemList` | Text match on title, key, name, cwd, branch; `project_id` includes its sub-projects. |
| `project_status(project_id, refresh=True)` | `ProjectStatus` | Runs (status, reason, "T03 of 5", stage, PR, artifact) ranked needs-you > blocked > running > paused > latest; sessions, PRs, worktrees, artifacts; rolled up over sub-projects. |
| `add_item(kind, key, project_id, title=None)` | `MoveResult` | By hand (`placed_by = manual`). A known item is moved instead (`created` False). |
| `move_item(item_id, project_id, expected_revision=None)` | `MoveResult` | By hand; a stale revision is refused; a run's auto-attached items follow (`followed`). |
| `move(target_id, to_project_id, expected_revision=None)` | `MoveResult` | An item (`i_...`) or a project (`p_...`): the one call behind drop = move. |
| `undo_move(move_id)` | `MoveResult` | Refused when the item moved since. |
| `remove_item(item_id)` | `MoveResult` | Back to the Inbox, by hand. Never deletes the thing itself. |
| `inbox(limit=None, refresh=True)` | `InboxList` | Each entry has a `suggestion` with its `reason`, or None. |
| `accept_suggestion(item_id)` | `MoveResult` | Files an Inbox item where its suggestion says. |
| `save_rule_from_move(move_id)` | `Rule` | From the item's strongest signal: workspace slug > repo + branch prefix > cwd prefix. |
| `list_rules(project_id=None)` / `delete_rule(rule_id)` | `RuleList` / `Rule` | Strongest signal first. |
| `purge_gone(item_id=None)` | `PurgeResult` | Deletes gone items for good, only when asked. |
| `attach_session(session_id, cwd, job_dir=None, entrypoint=None)` | `AttachResult` | The SessionStart hook: files a starting session by title > cwd > rule > Inbox over what the store holds, no reader run. Headless (`sdk*`) runs are skipped; a known session stays put. |
| `home(refresh=False)` | `HomeState` | The studio's home page: cards in final order (needs-you, blocked, running, latest change), at most 3 runs per card with "+ n earlier runs", "2 inside", PR line, a banner per failed source (last-good states kept), `loading` before the first scan, `first_run` with no project. |
| `open_studio()` | `StudioServer` | Starts `studio/web.py` on 127.0.0.1 unless one of this code version runs (`started` False); asks an older one to stop first. Never opens a browser. `StartFailed` after 5 s (see `studio.log`). |
| `studio_status()` | `StudioServer` | The running studio, or `running` False. |
| `stop_studio()` | `StudioServer` | POST /shutdown with the token, waits up to 5 s. Never kills. |

The Inbox can't be moved, archived, deleted, linked, or hold sub-projects.

## Items, placement and the unknown-vs-gone rule

Item kinds: `session-bg`, `session-interactive`, `night-sprint`, `night-marathon`, `artifact`,
`pr`, `worktree`. Each has one home project and a stable `key` (session UUID, folder path, URL,
`owner/repo#n`). Placement, strongest first (`sdk/reconcile.py`):
manual > title (`ns-<slug>-<TAG>`, `state/<TAG>.session`) > cwd/worktree (cwd, `<WORKTREE>`,
`<WORKTREE>-<TAG>`, `state/<TAG>.cwd`, `<BRANCH>` / `<BRANCH>--<TAG>` for PRs) > rule > Inbox.
Archived projects get nothing new. A run's title/cwd-attached items follow it when it moves.

New sessions do not wait for a scan: the plugin's SessionStart hook (`hooks/attach-session.sh` ->
`studio/session_hook.py` -> `api.attach_session`, `sdk/attach.py`) files each one as it starts,
silently, in a few seconds at most, exiting 0 on any failure. Until a read finds it, its row has
no scope, so it can't be marked gone; after 10 minutes unseen it joins the "sessions" scope.

A failed or partial read keeps the last-good data and records the error in the cache; only a
complete read sets `gone_at`, and a gone item keeps its project. A failed `claude agents` read
makes every bg session `status = "unknown"`. Headless `claude -p` runs never become items.

## Readers and the cache

| Source | Reader | TTL | Env override |
|---|---|---|---|
| workspaces (discover) | `readers/runs.py` | 60 s | `PROJECT_STUDIO_ROOTS`, else `NIGHT_WATCH_ROOTS` |
| one live workspace's state files | `readers/runs.py` | 2 s | - |
| `claude agents --json --all` | `readers/sessions.py` | 10 s | `claude` on PATH |
| `jobs/*/state.json` | `readers/sessions.py` | 10 s | `PROJECT_STUDIO_CLAUDE_HOME` |
| transcripts `projects/*/*.jsonl` | `readers/sessions.py` | 60 s | `PROJECT_STUDIO_CLAUDE_HOME` |
| `git worktree list` per repo | `readers/git.py` | 60 s | `git` on PATH |
| `gh pr list` per repo (open and closed) | `readers/git.py` | 5 min | `gh` on PATH |

Results live in the store's `cache` table (`sdk/cache.py`), shared by every process.

| Error | `code` | When |
|---|---|---|
| `NotFound` | `not_found` | No project with that id (a malformed id included). |
| `InvalidInput` | `invalid_input` | Wrong type, empty or over-long name, a limit out of range. |
| `Refused` | `refused` | A rule says no: a cycle, a non-empty delete, the Inbox. |
| `ReadOnlyStore` | `read_only` | The store was written by a newer SDK. |
| `StartFailed` | `start_failed` | The studio web server did not come up (its log, `studio.log`, says why). |

`Project` fields: `id`, `name`, `parent_id`, `path` (names from the top level down),
`is_inbox`, `archived_at`, `created_at`, `updated_at` (ISO 8601 UTC), `child_count`,
`item_count`, `linked_ids`. Fields may be added; none is renamed or removed.

## night-watch's readers

`sdk.readers.workspace` reads night-sprint and night-marathon workspaces (`Sprint`,
`walk_chain`, `tag_state`, `World`, ...). They moved here from `bin/night-watch`, which imports
them back; its drawing and display filter stay in night-watch.
`studio/tests/test_night_watch_parity.py` holds night-watch's output byte-identical.

## Adding an agent tool

1. Add one documented function to `sdk/api.py` with a dataclass return type in `sdk/results.py`.
2. In `studio/mcp_server.py`, add one `TOOLS` entry (strict `inputSchema`, `outputSchema`,
   `annotations`) and one `HANDLERS` line that calls that function.
3. Test the function through `sdk.api` and the tool over stdin/stdout.

## The studio web server (ticket 04)

`studio/web.py` is a thin adapter: one SDK call per route. `sdk/server.py` holds its lifecycle and
guard. `server.json` in the data dir ({pid, port, version, token}, 0600) names the running server;
the version hashes every studio source file's name, size and mtime, so a code change restarts it
on the next open. It listens on 127.0.0.1 only (`$PROJECT_STUDIO_PORT`, else a free port), refuses
any `Host` but `127.0.0.1:<port>` (403), refuses a POST without the token (`X-Studio-Token`) or
with a foreign `Origin` (403), and stops after `$PROJECT_STUDIO_IDLE` seconds (default 1800) with
no open page and no request. `bin/project-studio [open|status|stop]` and the `studio_open` MCP tool
call `open_studio()`.
