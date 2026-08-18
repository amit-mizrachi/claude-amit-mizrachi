# amit-mizrachi

Three [Claude Code](https://claude.com/claude-code) skills for running work you are not
sitting and watching - handing a session off, taking a feature through the night, and keeping
a big effort's map legible - plus the macOS hook that stops your machine sleeping through it.

## Install

```
/plugin marketplace add amit-mizrachi/claude-amit-mizrachi
/plugin install amit-mizrachi@amit-mizrachi
```

Start a new session (or `/clear`). The skills then appear as `amit-mizrachi:next-prompt`,
`amit-mizrachi:night-sprint`, and `amit-mizrachi:mywayfinder`.

## What's in it

### `next-prompt`

Writes a self-contained continuation prompt for the next task and **launches it as a
background agent**, so the work carries on in a fresh session instead of dying with this one.

The prompt is built around what a new session *cannot* recover on its own. It can read git,
`CLAUDE.md`, and the codebase; it cannot read the decisions you made, the gotchas you hit, or
the state that never got written down. So the template spends its words there, and the
`Gotchas:` line is mandatory.

Handles a phased plan too: it generates every phase's prompt at once, then launches only the
next actionable one - because Phase 2 usually cannot start until Phase 1 lands, and starting
both just creates conflicting work. Say "launch them all" and it will, telling each session
to take an isolated worktree.

Use it when you are low on context, wrapping up, or want to queue work you will not be around for.

### `night-sprint`

Delivers a whole feature overnight as a **chain** of autonomous sessions. Ticket 01 lands and
hands off to ticket 02, and so on, with exactly one session touching code at a time - all in
one worktree, on one branch, landing as **one PR**. No frozen contracts, no disjoint-file
rules, no merge conflicts, no integration step.

You are the conductor and you write no product code. You set the sprint up, launch the first
ticket, then watch: revive what dies, fire reviews at the checkpoints you chose, run an
optional test session, and write the morning report.

The parts that make it survive an unattended night:

- **A permission mode that cannot stall.** `acceptEdits` still prompts on shell commands, and
  a background session cannot answer a prompt - it just sits there. `bypassPermissions` needs
  a one-time interactive disclaimer nobody is awake to accept. So the default is `auto`: risky
  actions get denied and the session keeps going.
- **An atomic claim before every launch.** It is the only thing keeping two agents out of one
  worktree.
- **A watcher** emitting `DONE` / `BLOCKED` / `STUCK` / `DIED` / `STALLED`, with a defined
  reaction to each. Two revival attempts per ticket, then it is marked abandoned and the
  sprint moves on - a sprint that delivers 7 of 9 tickets and says so beats one that loops on
  ticket 3 all night.
- **Conductor relay at 35% context.** The sprint outlives any one conductor; the workspace is
  written so a cold one can pick it up.
- **A morning report with a full session ledger** - every session, including revived attempts
  and relays, and what each one actually contributed.

Ships six reference files: the plan skeleton, implementer/review/test prompts, and the
`launch.sh` / `watch.sh` scripts.

### `mywayfinder`

The chart layer on top of `wayfinder`. It takes an effort's blocking graph and publishes it as
one interactive page: dependency tiers with drawn connectors, filters that cut the way a human
actually picks work ("what can I take right now", "what can I leave running while I sleep"),
and a detail panel per ticket.

Its real subject is **staleness**. The chart is hand-maintained and never reads the tracker, so
it will drift - and a stale view that cannot admit it is worse than no view, because it gets
read as current. So the page carries a dated log and a masthead stamp naming the last ticket
folded in, and prints its own staleness test. Everything derivable is derived at runtime from
the ticket array, because counts typed into markup go stale on their own schedule.

> **Requires [`wayfinder`](https://github.com/mattpocock), which this plugin does not ship.**
> `wayfinder` owns the map, the tickets, the fog and the frontier; this skill only draws them.
> It looks for `wayfinder` in your available skills, then `~/.claude/skills/`, then
> `~/.agents/skills/`, and stops with an explanation if it finds none rather than improvising
> a substitute.

### The `caffeinate` hook

`SessionStart` and `UserPromptSubmit` re-arm `caffeinate -i -s -t 28800`, giving a **sliding
8-hour window**: your Mac stays awake until 8 hours pass with no Claude activity, then sleeps
normally. The display still turns off and disks behave normally. Silent no-op off macOS.

Change the window via `TIMEOUT_SECONDS` in `amit-mizrachi/hooks/caffeinate.sh`, or the scope
via its flags:

| Want | Flags |
|------|-------|
| Idle sleep only, lightest touch | `-i -t 28800` |
| Also keep the screen on | `-d -i -s -t 28800` |
| Also keep disks awake | `-i -m -s -t 28800` |

## Optional companions

Nothing below is required. Where a skill is missing, the caller degrades and says so - except
`wayfinder`, which `mywayfinder` genuinely cannot work without.

| Skill | Used by | For |
|---|---|---|
| `wayfinder` | `mywayfinder` | the map itself (**required**) |
| `to-spec`, `to-tickets` | `night-sprint` | cutting a feature into tickets when none exist yet |
| a review skill (e.g. `quad-review-squad`) | `night-sprint` | the checkpoint and final reviews |
| a dev-environment skill | `night-sprint` | the optional test session that boots the stack |
| `artifact-design` | `mywayfinder` | built into Claude Code |
| `next-prompt` | `night-sprint` | the conductor relay - ships here |

`night-sprint` also references review and dev-environment skills generically. Substitute
whatever your repo uses; the sprint reads the names out of its own prompt files, which you fill
in at kickoff.

## Local development

Clone it and point Claude at the working copy instead of the published marketplace:

```
git clone https://github.com/amit-mizrachi/claude-amit-mizrachi.git
```

```
/plugin marketplace add ./claude-amit-mizrachi
/plugin install amit-mizrachi@amit-mizrachi
```

Validate before committing:

```
claude plugin validate .
claude plugin validate ./amit-mizrachi
```

That validator earns its keep. It is what caught `night-sprint` shipping an unquoted
colon-space inside `argument-hint` - one bad line that took down the entire YAML block, so the
skill loaded with no `name` and no `description` and only ever fired when invoked by hand.

## License

MIT - see [LICENSE](LICENSE).
