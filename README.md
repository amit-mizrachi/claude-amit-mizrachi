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
- **A watcher** emitting `DONE` / `BLOCKED` / `RELAYED` / `WARN` / `FAT` / `STUCK` / `DIED` /
  `STALLED`, with a defined reaction to each. It reads the dead session's transcript to tell an
  API error apart from a clean silent exit, because the two deserve different treatment.
- **Two context rungs, measured not guessed.** A gauge reads each session's transcript for how
  much of its window it has USED. At 20% the conductor nudges it to start nothing new; at 30% it
  hands its tag to a fresh session. The handoff line is early on purpose - a session with 70% of
  its window left writes a successor prompt worth reading, and several sessions per ticket is the
  intended shape. A floor holds the handoff back until the session has actually changed
  something, so an early relay never buys a pure re-read.
- **Reviews are two sessions, never one.** One runs the review squad and posts its findings as
  inline PR comments, writing no code at all; a second, with a clean window, implements them.
  Consolidating five specialist reports and then editing code in the same session was what used
  to exhaust a review mid-triage, which loses the triage - the most valuable thing it had.
- **Resume before restart.** Most night-time deaths are the API dropping the call, not the
  session's fault - and the conversation survives on disk. So the reviver resumes that
  conversation with a "carry on, do not start over" prompt before it ever rebuilds a ticket
  from scratch. Resume mints a new session id and drops the display name, so it also repoints
  the watcher; doing this by hand leaves a live session nobody is watching. When the ladder
  (resume, restart, abandon) runs out, the ticket is abandoned and the sprint moves on - one
  that delivers 7 of 9 tickets and says so beats one that loops on ticket 3 all night.
- **The conductor holds itself to the same rungs.** It is the longest-lived session of the night
  and the one whose death costs the most, so it relays itself into a fresh conductor at 30% used;
  the workspace is written so a cold one can pick the sprint up.
- **A closing wizard that is only the commands a human must run** - an apply, a paste, a click.
  No preflight stages, no status stages, no "did it work" stages: anything an agent could do, the
  sprint does itself or files as a follow-up ticket. A stage asking the user to do an agent's
  chore reads as a requirement and is really a handover.
- **A morning report with a full session ledger** - every session, including revived attempts
  and relays, and what each one actually contributed.

Ships thirteen reference files: the plan skeleton, the implementer / review-find / review-fix /
test / wizard / continuation prompts, and the `launch.sh` / `watch.sh` / `revive.sh` /
`remind.sh` / `relay.sh` / `context-used.sh` scripts.

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
| a review skill (e.g. `quad-review-squad`) | `night-sprint` | the FIND half of each review pair |
| `address-review` (or equivalent) | `night-sprint` | the FIX half of each review pair |
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
