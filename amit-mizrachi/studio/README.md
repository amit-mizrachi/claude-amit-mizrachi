# Project Studio

One place for everything Claude runs for you on this Mac: your projects as a tree, and in each
project its night sprints, night marathons, Claude sessions (background and interactive),
artifacts, PRs and worktrees. Every such thing is an **item** with exactly one **home project**;
what the studio cannot place yet waits in the **Inbox**. Moving an item is how you file it, and
"Always file items like this here" turns a move into a **rule** for the next one; `rule-add`
(or "Add rule..." in a project's Rules section) writes one by pattern, like `sis-*`.

Three ways in, all over the same data:

| Way in | Who uses it | Where |
|---|---|---|
| `project-studio` | you, in a browser or a terminal | `bin/project-studio`, `studio/cli.py`, `studio/web.py`, `studio/static/` |
| the `project-studio` MCP server (`studio_*` tools) | agents | `studio/mcp_server.py`, registered in `.mcp.json` |
| the SessionStart hook | every new session, silently | `hooks/attach-session.sh` -> `studio/session_hook.py` |

All three are thin adapters. ALL logic - the tree, placement, readers, the cache, rules, what a
card or a row shows - lives in the SDK, `studio/sdk/`, and each adapter parses its input, calls
ONE function of `sdk.api`, and serialises the result. The SDK's full contract (every function,
its return type, its errors, the placement rules and the readers) is in
[`sdk/README.md`](sdk/README.md).

Stdlib Python 3.9+ and bash. No packages, no build step.

## `project-studio`

Every action the page and the MCP tools have, from the terminal. Each command calls one SDK
function (`studio/cli.py` only parses and formats). `project-studio help [command]` prints
every command, its options and an example.

| Command | Example | Does |
|---|---|---|
| (none), `open` | `project-studio` | start the studio if it is not running (or restart an older version), open it |
| `stop` | `project-studio stop` | ask the running studio to stop |
| `status` | `project-studio status` | whether the studio runs, and where |
| `status <project>` | `project-studio status 'Project Studio'` | a project's night runs and items |
| `list` | `project-studio list --by activity` | the project tree with each project's night runs in words ("2 blocked, 1 running, 4 done"); `--by activity` puts the latest activity first, as home does, and says when ("12 min ago"); `--all` adds archived ones |
| `show` | `project-studio show p_1a2b3c` | one project's view: sub-projects, its own runs, then each sub-project's runs under an "In <name>" heading (one indent per level), sessions, PRs, rules; `--json` has them as `sub_runs` |
| `find` | `project-studio find alpha --kind session-bg` | items that match, newest activity first (`--gone`, `--dismissed` include those) |
| `inbox` | `project-studio inbox --limit 20` | unfiled items with the suggested project |
| `refresh` | `project-studio refresh --force` | re-read the sources; say what changed and what failed |
| `rules` | `project-studio rules --project 'Shapes evals'` | the filing rules |
| `create` | `project-studio create Docs --under Alpha` | a new project, top-level or under another |
| `rename` | `project-studio rename Docs 'Docs site'` | a new name |
| `archive` | `project-studio archive 'Old work'` | archive a project and everything under it |
| `unarchive` | `project-studio unarchive p_1a2b3c` | bring an archived project back (by id or id prefix; `list --all` shows them), with the sub-projects archived with it; refused inside a still-archived project or when an active sibling now has its name |
| `delete` | `project-studio delete Scratch --yes` | delete an EMPTY project; without `--yes` it says what it would delete |
| `remove-project` | `project-studio remove-project Scratch --yes` | remove a project that holds things: its runs and items go to its parent (a top-level one's to the Inbox), its sub-projects move up; nothing on disk changes. Without `--yes` it lists what moves where (y/N on a tty); prints the move id whose `undo` brings it all back |
| `nest` | `project-studio nest Docs --under Beta` | a new parent (`--under`), or the top level (`--top`) |
| `link` | `project-studio link Alpha Beta` | link two projects |
| `unlink` | `project-studio unlink Alpha Beta` | remove the link between two projects; not linked changes nothing |
| `add` | `project-studio add artifact https://claude.ai/artifact/abc Alpha` | file a session, folder, URL, file or PR by hand |
| `file` | `project-studio file i_1a2b3c4d Alpha` | move an item into a project |
| `undo` | `project-studio undo 42` | put back what a move did |
| `remove` | `project-studio remove i_1a2b3c4d` | an item back to the Inbox; it deletes nothing |
| `dismiss` | `project-studio dismiss i_1a2b3c4d` | hide an item (a night run with its attached sessions, PRs, worktrees) from every list; it deletes nothing |
| `restore` | `project-studio restore i_1a2b3c4d` | show a dismissed item again (`find --dismissed` and `show` list them) |
| `mark-done` | `project-studio mark-done i_1a2b3c4d` | a night run whose state files froze on a word no longer true shows Done, "marked done by you", until its files change again |
| `actions` | `project-studio actions i_1a2b3c4d` | what a night run's actions menu offers now, one line each: id (`open-plan`, `open-pr`, `open-terminal`, `open-conductor`, `move`, `mark-done`, `dismiss` or `restore`, `throw-away`), label and the command that does it; `--json` is `api.run_actions`'s shape. Changes nothing, so an agent can ask first |
| `throw` | `project-studio throw i_1a2b3c4d --yes` | throw away a night run: its folder to the macOS Trash, its worktrees removed with `git worktree remove` (never forced), the run and its attached items purged. Without `--yes` it prints what goes and asks y/N on a tty (exit 2, `confirm_needed`, without one). Refused while its runner or a session of it is live. The one command that removes things, see below |
| `accept` | `project-studio accept i_1a2b3c4d` | file an Inbox item into its suggested project |
| `rule-save` | `project-studio rule-save 42` | "Always file items like this here", from a move id |
| `rule-add` | `project-studio rule-add Shapes --workspace 'sis-*' --dry-run` | write a rule by pattern: `--workspace GLOB`, `--repo NAME [--branch-prefix eval/]` or `--cwd-prefix FOLDER`. Says how many Inbox items it files now and names up to 5; `--dry-run` saves nothing; `--apply` files them now, one `undo` line each. `*`, `/` and `~` alone are refused |
| `rule-delete` | `project-studio rule-delete r_1a2b3c4d5e6f` | delete one rule; what it filed stays |
| `export` | `project-studio export ~/studio.json` | the whole store as JSON, printed or written to a file |
| `purge` | `project-studio purge` | delete gone items for good (one, or all) |
| `terminal` | `project-studio terminal i_1a2b3c4d` | Open in Terminal (in your terminal app, see `settings`); asks y/N when the session may be open elsewhere. `--conductor` on a night run: its conductor session (`status` lists them under "Conductors") |
| `settings` | `project-studio settings terminal iTerm` | print the settings, or set one: `terminal` is `Terminal`, `iTerm` or `default` |
| `command` | `eval "$(project-studio command i_1a2b3c4d)"` | print only the command that opens a session again (`--conductor`: a night run's conductor) |
| `open-item` | `project-studio open-item i_1a2b3c4d --target plan` | open a URL, folder or file with `open` |

References: a project is its id, a unique id prefix (4+ characters, the `p_` optional) or its
name (any case, active projects only); an item is its id or a unique id prefix. An ambiguous
name lists the candidates. A move (`file`, `add` of a known item, `accept`, `nest`, `remove`,
`dismiss`, `restore`, `mark-done`, `undo`) prints `Move <id>. Undo: project-studio undo <id>`. An `add` that creates a new item is
not a move; it prints the `remove` command instead.

**Your terminal app.** Open in Terminal (the page's button and the `terminal` command alike)
opens a session in the app the `terminal` setting names. With no setting
(the default) it runs `open <file>.command`, which macOS gives to Terminal. To change it, a person
or their Claude runs one command; "set my Project Studio terminal to iTerm" means:

```
project-studio settings terminal iTerm      # or Terminal; `default` clears it
project-studio settings                     # prints the current value
```

iTerm gets a new window with its default profile, and the `.command` file runs in it. The first
time, macOS asks once to let the studio control iTerm. A name the studio does not know is refused;
an unknown name written into `settings.json` by hand falls back to Terminal, and the message says so.
A running web server reads the setting on each open, so no restart is needed.

**The `--json` contract.** `--json` goes before or after the command. On success stdout is
`to_dict(result)` with sorted keys: the same shape the MCP tools and the web routes return.
On an error stdout is `{"error": {"code", "message", ...}}` (an ambiguous name adds
`candidates`); without `--json` the error is `project-studio: <code>: <message>` on stderr.

Exit codes: 0 ok; 1 a studio error (`not_found`, `ambiguous`, `invalid_input`, `refused`, ...);
2 a usage error (argparse prints the usage), or `confirm_needed`: `delete` without `--yes`, and
`terminal`, `throw` and `remove-project` without `--yes` when no tty can answer the y/N question.

**Leaving, renaming and removing a project.** Every project view has a way back at its top left:
"< Projects", or "< <parent>" in a sub-project; Esc and the browser's Back go the same way. Its
"..." menu has **Rename** (the name turns into a field: Enter saves, Esc cancels), **Archive** and
**Remove project...**: the dialog lists what is inside (sub-projects, night runs, other items) and
where each goes, OK removes it (one `remove_project` call), the page goes to the parent (or home)
and the toast's **Undo** brings the project back with the same id and everything in it.

The studio is a local web server on `127.0.0.1` only. The home page is a scrolling list of
full-width project rows, latest activity first (the newest run state change, session transcript
write or PR update in the project or under it). The order is fixed when the page loads: a live
update changes what a row says, never its place, and a small **Re-sort** link shows when the
activity order has changed since. A row says the project's status, its night runs in words and
its last activity ("12 min ago"), then up to 6 of its own runs across the width (needs-you
first, "+ n more"), then each active sub-project as an indented block with its own status and up
to 3 runs. Projects with no runs and nothing new in 14 days fold into "n quiet projects" at the
bottom. A long name ends in "..." and shows in full on hover; nothing runs past a row's edge. A
click on a row (or Enter on it) opens the project view
(its own runs, then a section per sub-project with that sub-project's runs, sessions, everything
else), where a session row's **Open in Terminal** opens Terminal on
`claude attach <id>` (a background session) or `cd <cwd> && claude --resume <id>` (an
interactive one), or copies that command. A sub-project section's header names it, its status
word and its runs in words ("2 blocked, 1 running, 4 done"), with **Open** to go to it; it shows
at most 5 run panels, needs-you first, and **+ n more** shows the rest in place. A section starts
open when a run in it (or under it) waits on you, is blocked or is running, else folded; deeper
levels nest one indent per level. A run panel's **Open conductor** opens the same way the
session that set the run up and watches its runner (from the run's `state/CONDUCTOR.session`,
which night-sprint writes, else the session whose transcript ran its `runner.sh start`); its
**Open in Terminal** stays the live ticket session. The **Inbox** drawer files items by drag, by **Move
to...** or by **Accept** on a suggestion, with **Undo** on every move. **Dismiss** on a run panel
or an item row hides it (a run with its attached items) from the cards, the project view's lists,
the Inbox and the counts, and deletes nothing; it waits in the **Dismissed** fold at the bottom of
the project view, where **Restore** shows it again. **Mark done** on a Blocked or Waiting-on-you
run panel says the run is done when its files froze on a stale word (a BLOCKED fixed by hand, an
early "CI red"): it shows Done, "marked done by you", everywhere, until the run's files change
again; Undo takes the mark back. **Show archived** under the cards lists every archived project
with **Unarchive** (an archived project's view has the button too), and the **x** after a name on
the project view's "Linked: ..." line unlinks it. Light and dark mode follow
the OS, with a manual toggle. Every night run line on home and every run panel in a project view
has the same actions menu, **...** or a right-click on the run, drawn only from `api.run_actions`'s
list: Open plan, Open PR, Open in Terminal, Open conductor (each when there is one), **Move to...**
(the picker; the run's attached items follow, Undo in the toast), Mark done (Blocked or Waiting on
you), Dismiss (Restore once dismissed) and Throw away... last. A run panel also shows all of them
but Move to... as buttons; a home line waiting on you keeps its **Open plan** and gains **Open
conductor** beside it when the conductor is known. A run also moves by drag: from a home line onto
another project's row or sub-project block, or from a run panel onto a sub-project's tile or
section. **Throw away...** on a run panel lists what goes (the folder, each
worktree, the item count) in a confirm dialog and does it only on OK. The studio never stops, kills
or removes a session.

**The one thing the studio removes.** Everything else only reads, files, hides or purges its own
records. A confirmed throw away (`throw --yes`, a y, `studio_throw_away` with `confirm` true, OK in
the dialog) of a night run is the one exception, and it removes exactly this, in this order,
stopping at the first step that fails with a message that says what was done and what was not:
each of the run's worktrees with `git worktree remove` (never `--force`: git refuses one with
changes, and every branch and its commits stay; git does not count gitignored files such as `.env` or
`.scratch/` as changes and deletes them for good, not to the Trash, so the plan and the dialog name
them first), then the run's folder to the macOS Trash through
Finder (never a plain delete; the first time, macOS asks once to let the studio control Finder),
then the run and its attached items from the store. Only a folder inside a run root
(`PROJECT_STUDIO_ROOTS`, symlinks resolved, `..` refused) is accepted, and a run whose runner or a
session of it is still live is refused before anything happens. A session found again later (its
transcript stays) comes back as an Inbox item.

It stops by itself after 30 minutes with no open page (`PROJECT_STUDIO_IDLE` seconds). It
listens on `PROJECT_STUDIO_PORT`, else a free port. Inside Claude Code the plugin's `bin/` is on
`PATH`; for your own terminals the plugin's `SessionStart` hook (`hooks/link-night-watch.sh`)
links `project-studio` next to `night-watch`.

## The MCP tools

Registered from the plugin's `.mcp.json` as `project-studio` (`plugin:amit-mizrachi:project-studio`).
Each tool is one SDK call:

| Tool | SDK function | Reads or writes |
|---|---|---|
| `studio_list` | `api.list_projects(parent_id, top_level, include_archived, limit, by)` | reads |
| `studio_create` | `api.create_project(name, parent_id)` | writes |
| `studio_find` | `api.find_items(query, kind, project_id, include_gone, limit, include_dismissed)` | reads (refreshes due sources) |
| `studio_status` | `api.project_status(project_id)` | reads (refreshes due sources); `groups` has the runs by sub-project |
| `studio_add` | `api.add_item(kind, key, project_id, title)` | writes |
| `studio_move` | `api.move(id, to_project_id, expected_revision=revision)` | writes; an item (`i_...`) or a project (`p_...`) |
| `studio_link` | `api.link_projects(a_id, b_id)` | writes |
| `studio_unlink` | `api.unlink_projects(a_id, b_id)` | writes; `removed` False when they were not linked |
| `studio_remove` | `api.remove_item(item_id)` | writes; back to the Inbox, never deletes the thing |
| `studio_dismiss` | `api.dismiss_item(item_id)` | writes; hides an item (a run with its attached items) from every list, never deletes anything |
| `studio_restore` | `api.restore_item(item_id)` | writes; shows a dismissed item again |
| `studio_run_actions` | `api.run_actions(item_id)` | read-only; what a night run's actions menu offers now, in menu order (id, label, `destructive` / `needs_confirm` only for throw-away, `target_id`, hint); other kinds refused |
| `studio_mark_done` | `api.mark_done(item_id)` | writes; a night run shows Done, "marked done by you", until its files change; other kinds refused |
| `studio_archive` | `api.archive_project(project_id)` | writes |
| `studio_unarchive` | `api.unarchive_project(project_id)` | writes; with the sub-projects archived with it |
| `studio_rename` | `api.rename_project(project_id, name)` | writes |
| `studio_delete` | `api.delete_project_guarded(project_id, confirmed)` | destructive; an empty project only. Without `confirmed` true it changes nothing and says what it would delete (`needs_confirm`) |
| `studio_remove_project` | `api.remove_project(project_id, confirmed=confirm)` | destructive; a project that holds things: contents up to the parent (or the Inbox), sub-projects up, then the project goes; nothing on disk. `confirm` is required; false changes nothing and lists what moves where (`needs_confirm`). `move_id` is one `studio_undo` handle that brings it all back |
| `studio_undo` | `api.undo_move(move_id)` | writes; puts back what a move, add, accept, remove, dismiss, restore or mark-done did |
| `studio_rules` | `api.list_rules(project_id)` | reads |
| `studio_rule_save` | `api.save_rule_from_move(move_id)` | writes; "Always file items like this here" |
| `studio_rule_add` | `api.add_rule(project_id, signal, pattern, apply, dry_run)` | writes; a rule by pattern, `dry_run` first for the count |
| `studio_rule_delete` | `api.delete_rule(rule_id)` | destructive; items it filed stay put |
| `studio_inbox` | `api.inbox(limit)` | reads (refreshes due sources) |
| `studio_accept` | `api.accept_suggestion(item_id)` | writes; files an Inbox item where its suggestion says |
| `studio_purge` | `api.purge_gone(item_id, all_gone)` | destructive; one gone item, or every gone item only with `all_gone` true |
| `studio_throw_away` | `api.throw_away(item_id, confirmed=confirm)` | destructive; the one tool that removes things (a night run's folder to the Trash, its worktrees, its store records). `confirm` is required; false changes nothing and says what would go (`needs_confirm`) |
| `studio_terminal` | `api.open_in_terminal(item_id, confirmed=confirm, target=target)` | opens a session (or a night run's live ticket session; `target` `conductor`: its conductor, `conductor_item_id` in `studio_status`) in the terminal app; `confirm` when it may be open elsewhere. Never stops a session |
| `studio_open` | `api.open_studio()` | starts the web page, returns its URL |

Nesting a project is `studio_move` with a `p_...` id.

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
  - `settings.json` (0600) - the person's settings: `{"terminal": "iTerm"}`; no file means the defaults.
  - `studio.log` - the web server's log.
  - `open/` - the `.command` files Open in Terminal writes.
- Nothing is purged by itself, and nothing on disk is removed except by a confirmed throw away (above). An item whose source no longer lists it is marked gone (and keeps
  its home); `api.purge_gone()` deletes gone items only when asked. `api.export_json(dest)` writes
  the whole store as JSON.
- Readers: `PROJECT_STUDIO_ROOTS` (else `NIGHT_WATCH_ROOTS`) for night-run workspaces,
  `PROJECT_STUDIO_CLAUDE_HOME` (default `~/.claude`) for jobs and transcripts, and `claude`,
  `git` and `gh` on `PATH`. A failed read keeps the last-good data and shows a banner; only a
  complete read ever marks an item gone.

## Adding an agent tool

New tools (`list_project`, `project_status`, ...) are a few lines each, because the logic they
need is an SDK function first. This is how `studio_inbox` was added:

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
   (`tests/test_mcp_server.py`, `support.validate`). The tool-set test reads the server's own
   `TOOLS`, so it needs no edit. `tests/test_plugin.py` fails if a handler does more than call one
   SDK function, if `TOOLS` and `HANDLERS` name different tools, or if SQL appears outside `sdk/`.

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
