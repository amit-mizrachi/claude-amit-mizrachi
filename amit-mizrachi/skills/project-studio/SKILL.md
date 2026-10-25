---
name: project-studio
description: Drives Project Studio, the local board of the user's projects, night sprints, night marathons, Claude sessions, PRs and worktrees, through its `project-studio` CLI (or its studio_* MCP tools). Files items into projects, writes filing rules, finds PRs by repo, monday id or state, lists a project's likely but unfiled items, dismisses or restores runs, and opens sessions - every change undoable and logged. Use when the user says "project studio", "studio", "file this PR", "why don't I see my PR in <project>", "add a rule", "dismiss/hide this run", "what is waiting on me", "move to project", "inbox", or names an item id like i_1a2b3c.
---

# Project Studio

## Overview

The studio holds the user's REAL data in `~/.project-studio/studio.db`. Read and change it only
through the CLI (or the `studio_*` MCP tools, the same SDK): never `sqlite3`, never edit a file
there, never stop the studio server. Every change prints a move id and its undo; report each one.

The CLI is `project-studio` (on `PATH` in Claude Code; in a checkout it is
`amit-mizrachi/bin/project-studio`). `project-studio help <command>` prints a command's options.
Put `--json` before the command when you parse the output: stdout is then exactly the MCP shape.

## References

- A project: its id (`p_36f9a363e240`), a unique id prefix (4+ characters) or its name (any case,
  quote it: `'Shapes in Shapes'`). An ambiguous name lists the candidates; pick by id.
- An item: its id (`i_30de23a9904d`) or a unique id prefix (`i_30de23`). `find` does NOT match ids;
  use `item <id>` to look one up.
- Kinds: `night-sprint`, `night-marathon`, `session-bg`, `session-interactive`, `pr`, `worktree`, `artifact`.

## Commands by task

| Task | Command |
|---|---|
| Overview of every project | `list --by activity` |
| One project: runs (status, reason, PR), sessions, PRs with state | `status <project>` (`--limit 50` for more) |
| What the page shows for a project | `show <project>` |
| One item, every field | `item <item>` |
| Find items | `find [text] [--kind pr] [--project P] [--repo shapes-platform] [--monday 13216938828] [--pr-state open\|draft\|merged\|closed] [--status needs-you\|blocked\|in-review\|...]` |
| Items likely belonging to a project, unfiled | `likely <project> --kind pr` |
| Unfiled items with a suggestion | `inbox`, then `accept <item>` |
| File an item | `file <item> <project>` |
| Put it back | `undo <move id>` |
| A rule for future items | `rule-add <project> --monday ID \| --workspace 'sis-*' \| --repo NAME [--branch-prefix eval/] \| --cwd-prefix FOLDER` with `--dry-run` first, then `--apply` |
| List / delete rules | `rules --project <project>`, `rule-delete <rule id>` |
| Hide a run (with its sessions, PRs, worktrees) | `dismiss <item>`; `restore <item>` brings it back |
| A run frozen on a stale Blocked word | `mark-done <item>` |
| What a run's "..." menu offers | `actions <item>` |
| Open a session or a run's conductor | `terminal <item> [--conductor]`, or `command <item>` to print it |
| Projects | `create`, `rename`, `nest --under`, `link`, `archive`, `remove-project` |
| Re-read sources now | `refresh` |
| The web page | `open` (also restarts it on new code; it may get a new port) |

## Recipe: "I have an open PR for X, why don't I see it?"

1. Find it: `find --kind pr --pr-state open --repo <repo> --monday <id>` (or text from its title).
   The project column says where it is; usually `Inbox`, because only a run's own PRs follow the run.
2. See what else is missing: `likely '<project>' --kind pr`. It names the Inbox PRs that share a
   monday id with the project's items, the project's main id first.
3. File each one: `file <item> '<project>'`. Log every `Move N. Undo: project-studio undo N`.
4. Make future ones land there: `rule-add '<project>' --monday <id> --dry-run`. Read what it would
   file now (worktrees, runs and merged PRs with that id too), then the same with `--apply`.
5. Check: `status '<project>'` lists the PRs with their state; `show` has "Open pull requests".

## Rules

- Dry-run first: every `rule-add` with `--dry-run`, every `remove-project` and `throw` without `--yes`.
- `dismiss`, never `throw`, to hide a run. `throw` moves the run's folder to the Trash and removes
  its worktrees: only when the user says to throw it away.
- Log every move id with its undo command in your report, and every rule id with its `rule-delete`.
- A status of `unknown` means its source failed to read. Never call such an item gone.
- Tests of studio code use fixture homes (`PROJECT_STUDIO_HOME`), never `~/.project-studio`.

## Red Flags - STOP

| Thought | Do instead |
|---|---|
| "The move printed `rule-save N`, I'll take it" | It learns the strongest signal of ONE item: for a PR with no run that is `repo X + branch feat/*`, every feature PR of the repo. Write the rule with `rule-add --monday` or `--workspace`, `--dry-run` first. |
| "I'll query studio.db directly, it's faster" | Real data, shared by several processes. Use the CLI; if it can't answer, that is a gap (below). |
| "`find i_30de23` returned nothing, so it's gone" | `find` matches text, not ids. Use `item i_30de23`. |
| "This run is noise, throw it away" | `dismiss` it. Throwing away removes files. |
| "The studio shows an old port, stop it and restart" | `project-studio open` restarts it. Never `stop` or kill it. |

## When the CLI can't do it

That is a gap in the studio, not a reason to go around it. Say so, then (if asked to fix it) add it
the studio's way: one SDK function in `studio/sdk/api.py` with all the logic, then a CLI command in
`studio/cli.py` and an MCP tool in `studio/mcp_server.py` that each make ONE call to it
(`studio/README.md`, "Adding an agent tool"; `tests/test_plugin.py` enforces it). Stdlib only,
ASCII only. Run only the test files you touch, by name.
