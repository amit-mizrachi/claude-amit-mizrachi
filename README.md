# amit-mizrachi (Claude Code plugin)

Amit Mizrachi's personal Claude Code skills, packaged as one installable plugin, plus the
macOS caffeinate hook that keeps the machine awake while they run.

## What's in it

| Skill | What it does |
|---|---|
| `next-prompt` | Writes a self-contained continuation prompt for the next task and launches it as a background agent, so work survives a session ending or running out of context. Handles one prompt or a whole phased sequence. |
| `night-sprint` | Delivers a whole feature overnight as a chain of autonomous sessions - one conductor that writes no code, one implementer per ticket, all on one branch landing as one PR. Revives dead sessions, fires reviews at chosen checkpoints, and writes a morning report with a full session ledger. |
| `mywayfinder` | `wayfinder` plus a published chart: the map's blocking graph drawn as an interactive artifact, updated as the last step of resolving every ticket. |

| Hook | What it does |
|---|---|
| `caffeinate` | `SessionStart` + `UserPromptSubmit` re-arm `caffeinate -i -s -t 28800`, giving a sliding 8-hour window: the Mac stays awake until 8 hours pass with no Claude activity, then sleeps normally. Silent no-op off macOS. |

## Install

```
/plugin marketplace add /Users/amitmizrachi/Documents/development/claude-amit-mizrachi
/plugin install amit-mizrachi@amit-mizrachi
```

Then start a new session (or `/clear`). Verify:

- Skills appear as `amit-mizrachi:next-prompt`, `amit-mizrachi:night-sprint`, `amit-mizrachi:mywayfinder`
- The hook is live: `pgrep -fl caffeinate`

## Prerequisites this plugin does not ship

These skills call out to skills that live elsewhere. Everything still runs without them -
the calling skill degrades and says so - except where marked **hard**.

| Skill | Needs | Where it comes from |
|---|---|---|
| `mywayfinder` | `wayfinder` (**hard** - it is the map; this skill only draws it) | Matt Pocock's engineering skills |
| `night-sprint` | `to-spec`, `to-tickets` (only when no ticket breakdown exists yet) | Matt Pocock's engineering skills |
| `night-sprint` | `quad-review-squad` | `agent-skills@shapes` |
| `night-sprint` | `address-review`, `shapes-dev-environment` | Amit's personal skills, not in this plugin |
| `night-sprint` | `next-prompt` (conductor relay at 35% context) | ships here |
| `mywayfinder` | `artifact-design` | built into Claude Code |

## Migrating off the loose copies

These three skills were copied out of `~/.claude/skills/`; the originals are still there.
That means each one is loaded twice until you clean up - once as `next-prompt` and once as
`amit-mizrachi:next-prompt`. Once the plugin is verified working:

```
rm -rf ~/.claude/skills/next-prompt ~/.claude/skills/night-sprint ~/.claude/skills/mywayfinder
```

Note that `next-prompt` also exists in the `agent-skills@shapes` team plugin as a different,
shorter version. That one is unaffected by this cleanup and will keep loading as
`agent-skills:next-prompt`.

The `caffeinate` hook supersedes the standalone `caffeinate@amit-local` plugin at
`~/claude-caffeinate`. Running both is harmless - they share a pidfile, so the second just
kills and replaces the first's timer - but it fires two hooks on every prompt for no reason:

```
/plugin uninstall caffeinate@amit-local
```

## Customizing the caffeinate window

Edit `TIMEOUT_SECONDS` in `amit-mizrachi/hooks/caffeinate.sh` (default 28800 = 8 hours), or
change the flags:

| Want | Flags |
|------|-------|
| Idle sleep only, lightest touch | `-i -t 28800` |
| Also keep the screen on | `-d -i -s -t 28800` |
| Also keep disks awake | `-i -m -s -t 28800` |

## Adding more skills later

Drop the skill directory into `amit-mizrachi/skills/` and reinstall. Candidates still sitting
in `~/.claude/skills/`: `orchestrating-parallel-delivery`, `plan-architecture`, `test-browser`,
`address-review`, `rtk-switch`, `save-note`, the Monday board suite (`add-task`, `do-task`,
`review-task`, `track-tasks`, `create-task`, `create-branch`), and the Shapes-specific set
(evals, flags, logfire, dev-env, sherlock, conventions).
