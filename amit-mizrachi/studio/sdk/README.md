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
- Schema v4: `projects`, `links`, `items`, `rules`, `moves`, `cache`, `schema_version` (v2: projects carry a `revision`, and a `moves` row is an item's or a project's move; v3: a move keeps the placement it replaced; v4: `items.dismissed_at`, and a `moves` row has a `kind` and `data_json`)
  (see `store.py`). A new version is one `_schema_v<n>(conn)` step in `store.MIGRATIONS` and
  `SCHEMA_VERSION` + 1: the backup and the one transaction come with it. The Inbox is a seeded project with the fixed id `inbox`.

## The contract: `sdk.api`

Every function opens the store for one call and returns a dataclass from `sdk.results`
(`sdk.results.to_dict(value)` makes it JSON-ready). Errors are `sdk.errors.StudioError`
subclasses with a stable `code` and a message fit to show a person as it is.

| Function | Returns | Notes |
|---|---|---|
| `create_project(name, parent_id=None)` | `Project` | Refused under the Inbox or an archived parent, or for an active sibling's name (any case). |
| `list_projects(parent_id=None, top_level=False, include_archived=False, limit=None, with_runs=False)` | `ProjectList` | Inbox first, then by path. `total` counts every match; `truncated` says the limit cut some. `with_runs` fills `run_lines` (id -> "running - 3 runs, 1 active" / "done - 2 runs done" / "no runs"; none for the Inbox), the CLI's `list` line. |
| `get_project(project_id)` | `Project` | Archived or not. |
| `resolve_project(ref)` | `Project` | What a person types: the exact id, then a unique id prefix (4+ characters, the `p_` optional), then a name (any case) among active projects. A unique name beats a prefix that matches several ids. `NotFound`, or `Ambiguous` with `candidates` ({id, name, parent_path}, at most 20). |
| `resolve_item(ref)` | `Item` | The exact id or a unique id prefix (4+ characters, the `i_` optional); no title matching. `NotFound`, or `Ambiguous` with `candidates` ({id, title, kind, project_path}, at most 20). |
| `move_project(project_id, new_parent_id=None)` | `Project` | `None` = top level. A cycle is refused as `Can't move <A> into <B>: it is inside <A>.` |
| `rename_project(project_id, name)` | `Project` | Same name rules as create; refused for the Inbox and an active sibling's name (any case). |
| `link_projects(a_id, b_id)` | `LinkResult` | Symmetric; `created` is False when it already existed. |
| `archive_project(project_id)` | `Project` | Hides it and everything under it from lists. Idempotent. |
| `delete_project(project_id)` | `DeleteResult` | Empty projects only (no sub-projects, no items); otherwise archive. |
| `delete_project_guarded(project_id, confirmed=False)` | `DeleteRequest` | The agent's delete: unless `confirmed`, changes nothing and returns `needs_confirm` with a `message` naming the project and its `links` / `rules` counts. Refused as `delete_project` is, before the ask. |
| `export_json(dest=None)` | `Export` | The whole store minus the cache; written to `dest` (0600, atomic) when given. |

| `refresh(force=False)` | `RefreshResult` | Runs the due readers, stores what they said, reconciles. `sources` shows each reader's state. |
| `find_items(query=None, kind=None, project_id=None, include_gone=False, limit=None, refresh=True, include_dismissed=False)` | `ItemList` | Text match on title, key, name, cwd, branch; `project_id` includes its sub-projects. Dismissed items only with `include_dismissed` (last, `dismissed` True). |
| `project_status(project_id, refresh=True, limit=None)` | `ProjectStatus` | Runs (status, reason, "T03 of 5", stage, PR, artifact; `progress_text` and `pr_text` are the words home and show use) ranked needs-you > blocked > running > paused > latest; sessions, PRs, worktrees, artifacts; rolled up over sub-projects (each `SubProject.text` is its tile's line: "no runs", "3 runs, 1 active"). `limit` caps each list; `totals` and `truncated` say what was cut. |
| `add_item(kind, key, project_id, title=None)` | `MoveResult` | By hand (`placed_by = manual`). A known item is moved instead (`created` False). |
| `move_item(item_id, project_id, expected_revision=None)` | `MoveResult` | By hand; a stale revision is refused; a run's auto-attached items follow (`followed`). |
| `move(target_id, to_project_id, expected_revision=None)` | `MoveResult` | An item (`i_...`) or a project (`p_...`): the one call behind drop = move. A project's move gets a `move_id` too; `message` is the toast ("Moved to Project Studio"). |
| `undo_move(move_id)` | `MoveResult` | An item's or a project's move, a dismissal (restores it and what went with it) or a restore (dismisses them again). Refused ("Can't undo: <name> was moved again since." / "... was changed again since.") when it changed since. |
| `remove_item(item_id)` | `MoveResult` | Back to the Inbox, by hand. Never deletes the thing itself. |
| `dismiss_item(item_id)` | `MoveResult` | Hides it from home, the project view's lists (into its "Dismissed" fold), the Inbox, `list` / `status` and their counts, and `find` unless asked. Deletes nothing; it keeps its project; no refresh clears it (a gone item stays dismissed). A run's auto-attached items go with it (`followed`). `kind` "dismiss", toast "Dismissed <title>"; `move_id` None when already dismissed. |
| `restore_item(item_id)` | `MoveResult` | Shows it again, with what its newest dismissal took along. `kind` "restore"; `move_id` None when not dismissed. |
| `inbox(limit=None, refresh=True)` | `InboxList` | Each entry has a `suggestion` with its `reason`, or None. |
| `accept_suggestion(item_id)` | `MoveResult` | Files an Inbox item where its suggestion says. |
| `save_rule_from_move(move_id)` | `Rule` | From the item's strongest signal: workspace slug > repo + branch prefix > cwd prefix. Refused for a project's move. |
| `list_rules(project_id=None)` / `delete_rule(rule_id)` | `RuleList` / `Rule` | Strongest signal first. |
| `purge_gone(item_id=None, all_gone=None)` | `PurgeResult` | Deletes gone items for good, only when asked. `all_gone` False with no `item_id` is refused, True with one is `InvalidInput`; None (the CLI) reads no `item_id` as every gone item. |
| `attach_session(session_id, cwd, job_dir=None, entrypoint=None)` | `AttachResult` | The SessionStart hook: files a starting session by title > cwd > rule > Inbox over what the store holds, no reader run. Headless (`sdk*`) runs are skipped; a known session stays put. |
| `home(refresh=False)` | `HomeState` | The studio's home page: cards in final order (needs-you, blocked, running, latest change), a line per active sub-project (`HomeCard.sub_projects`, below), at most 3 runs per card with "+ n earlier runs" (a sub-project's run tagged "in <sub-project>"), PR line, a banner per failed source (last-good states kept), `first_run` with no project, `reading` / `reading_text` ("Still reading PRs...") for sources still being read. Answers from the store and never waits for a slow source. |
| `open_studio()` | `StudioServer` | Starts `studio/web.py` on 127.0.0.1 unless one of this code version runs (`started` False); asks an older one to stop first. Never opens a browser. `StartFailed` after 5 s (see `studio.log`). |
| `studio_status()` | `StudioServer` | The running studio, or `running` False. |
| `stop_studio()` | `StudioServer` | POST /shutdown with the token, waits up to 5 s. Never kills. |
| `project_view(project_id, refresh=False)` | `ProjectView` | The studio's `#/p/<id>`: breadcrumb, "Linked: ..." text, link choices, sub-project tiles, run panels (Open plan / Open PR / Open in Terminal when they apply), session rows (bg live, bg done, interactive, gone), "Everything else" folds (sessions too when none is active), and the project's `rules` (each deletable). |
| `terminal_command(item_id)` | `TerminalCommand` | A session (or a run's listed session): `claude attach <short>` when `claude agents` lists it, else `cd <cwd> && claude --resume <id>`; pattern-checked, shlex-quoted; `confirm` set when its transcript changed in the last 5 min. Runs nothing ("Copy command"). |
| `open_in_terminal(item_id, confirmed=False)` | `TerminalOpen` | Writes `<data dir>/open/<item id>.command` (0700) and opens it in the `terminal` setting's app (`app`): no setting `open <file>`, `Terminal` `open -a Terminal <file>`, `iTerm` `osascript` (a fixed script: new window, default profile, `write text` the quoted path, which is the script's argument). An unknown stored name falls back to Terminal and the message says so. On failure `pbcopy` (`copied`). `needs_confirm` until `confirmed` when the guard asks. Never stops, kills or removes a session. |
| `settings()` / `set_terminal(app)` | `Settings` | `<data dir>/settings.json` (0600). `terminal`: `Terminal`, `iTerm` or "" (the default). `set_terminal` takes any case and `iTerm2` / `Terminal.app`; `default` clears it; any other name is `InvalidInput`. |
| `open_target(item_id, target="default")` | `OpenResult` | `open` on the item's own URL or path (`plan` / `pr` for a run): http(s) URLs, or paths under the known roots; folders in Finder, pages in their app, other files only revealed (`open -R`). |
| `inbox_view(limit=200)` | `InboxView` | The studio's Inbox drawer: rows with name, kind and one fact ("interactive", "2 h"), the suggestion chip and its reason, whether Accept applies; the full count and the hint. Store only. |
| `move_choices(target_id)` | `MoveChoices` | "Move to..." for an item (every active project but its own, the Inbox included) or "Set parent" for a project (the top level and every other active project), in tree order. |

The Inbox can't be moved, archived, deleted, linked, or hold sub-projects.

## The move ledger

Every undoable change is one `moves` row: `kind` (`store.MOVE_KINDS`: `move`, `dismiss`,
`restore`), the item or project, from / to, the `revision` it produced (a newer revision makes its
Undo stale), and `data_json`, what its Undo needs (a dismissal's `followed` items). `items.undo`
checks the revision and hands the row to `items.UNDO[kind]`. A new kind is: its name in
`MOVE_KINDS`, a function that changes the item, bumps its revision and calls
`items._record(conn, row, to_project, revision, kind, data)`, and one `UNDO` entry that puts it
back (returning a `MoveResult` with that `kind`). No migration: `kind` has no CHECK and
`data_json` is free-form. `save_rule_from_move` learns only from a `move`.

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

A night sprint is `needs-you` / "CI red" when `state/ACCEPTANCE.verdict` is FAIL, unless its CI
ticket later wrote `PASS at <same head>` to `state/CI.summary` (accept.sh writes FAIL when
`gh pr checks` exits 1, which it also does on a PR with no checks). A finished sprint whose CI
summary says it had no checks (`no CI`, `0 checks`) is `done` with the reason "no CI".

A run's state files freeze when its sessions end, so a `blocked` or `needs-you` run whose PR is
merged (and that has no open PR) is `done` with the reason "PR merged" wherever a `Run` is shown
(home, project view, `status`, `list`); `find` and the Inbox keep the reader's word. A run blocked
at a stage after its tickets (CI, FIX-FINAL) says so in its progress words, "at CI - 17 of 17
done", not "T17 of 17"; a done run says how many tickets settled, "12 of 13".

| Error | `code` | When |
|---|---|---|
| `NotFound` | `not_found` | No project with that id (a malformed id included). |
| `Ambiguous` | `ambiguous` | A reference (`resolve_project` / `resolve_item`) matches more than one; `candidates` lists them. |
| `InvalidInput` | `invalid_input` | Wrong type, empty or over-long name, a limit out of range. |
| `Refused` | `refused` | A rule says no: a cycle, a non-empty delete, the Inbox. |
| `ReadOnlyStore` | `read_only` | The store was written by a newer SDK. |
| `StartFailed` | `start_failed` | The studio web server did not come up (its log, `studio.log`, says why). |

`HomeCard` fields: `project`, `sub_projects`, `runs` (at most 3), `more` ("+ 2 earlier runs"), `pr`,
`attention` (`needs-you`, `blocked` or ''), `empty` ("No night runs yet"), `changed_at`. Each of
`sub_projects` is a `HomeSubProject`, the card's active (not archived) sub-projects in tree order
(by name, any case): `project_id` (what a click opens), `name`, `status` (`pending` with no runs,
else the top run's, as the project view's tile says it), `glyph`, `word` ("Running"; '' with no
runs), `text` ("3 runs, 1 active", "2 runs done", "no runs"; over its own active sub-projects too,
runs not gone) and `inside` ("2 inside" for its active sub-projects, '' with none; deeper levels
stay a count). A card run (`HomeRun`) that lives in a sub-project, or under one, carries that
sub-project's `sub_project_id` and its tag `sub_project` ("in Machina decision units"); both are ''
for the card's own runs. A card has no "n inside" count any more: the lines replace it.

`Project` fields: `id`, `name`, `parent_id`, `path` (names from the top level down),
`is_inbox`, `archived_at`, `created_at`, `updated_at` (ISO 8601 UTC), `child_count`,
`item_count`, `linked_ids`. Fields may be added; none is renamed or removed. The Inbox's
`item_count` is what the Inbox shows: items not gone, active in the last 14 days
(`model.INBOX_DAYS`), the same number as `home().inbox_count`.

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
