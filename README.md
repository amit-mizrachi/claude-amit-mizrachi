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
ticket, arm the runner, and then handle only what a script cannot decide.

The parts that make it survive an unattended night:

- **The watcher is a runner, not a narrator.** It advances the chain, revives dead sessions and
  waits out spending limits by itself, logging every action to `state/EVENTS.log`, and escalates
  only what needs a judgement: a real blocker, two agents on one tag, an auth failure, a budget
  gap, the first PR, the end of the sprint. It used to report everything it saw - one night, 28
  routine heartbeats and 21 successful handoffs, each of which the conductor read, logged and
  answered with the same scripted call it could not have answered any other way. That is a model
  doing a script's job with a model's context. Silence now means the sprint is running; a
  heartbeat follows any full hour with nothing to say.
- **One transition owner.** `advance.sh` is the only thing that decides what runs next. A session
  writes `state/<TAG>.next` **before** its status file, and both the session and the runner may
  call `advance.sh` - they get the same answer because it comes from the same code. Two things
  deciding off two different files is what once launched a review fixer before its finder had
  finished deciding whether there was anything to fix.
- **Failures are classified before they are retried.** `classify-error.sh` reads the transcript
  and names the class: a dropped connection, the rolling session limit **with the reset time it
  names**, the org spend cap, or an auth failure. Each gets a different response, because a retry
  can only fix the first. Two reviews once stopped on spend-limit errors and recovery treated
  them as ordinary stalls: the resume ladder burned out against a wall it could not climb, 3h32m
  went missing - about a third of that night - and the log recorded it as a permission stall.
  Faster polling cannot resolve a spending cap; naming the failure can. While the sprint is out
  of capacity nothing new launches, because every fresh session against a cap that is already
  refusing requests spends one more refused request.
- **Nothing interrupts a working session, and the sprint no longer pretends otherwise.** There
  is no way to push an instruction into a running background session. Two scripts used to fake
  one by stopping the session and resuming it with a new prompt - but `claude stop` matches only
  the short 8-character id, so handed the full session id it stopped nothing, and the resume
  **forked** the conversation: two agents in one worktree, overwriting each other, with the
  watcher following only one. Both scripts are deleted. The failure was removed rather than
  guarded.
- **So every session manages its own window.** It measures itself with `context-used.sh --self`
  at named checkpoints, narrows its scope at 20% USED, and at 30% writes its own continuation
  prompt and launches its own successor - one ticket becoming `T03 -> T03c2 -> T03c3`, still
  strictly one session at a time. The handoff line is early on purpose: a session with 70% of
  its window left writes a successor prompt worth reading. A floor holds the handoff back until
  the session has actually changed a file, so an early relay never buys a pure re-read; a 60%
  ceiling expires that floor.
- **A permission mode that cannot stall.** `acceptEdits` still prompts on shell commands, and
  a background session cannot answer a prompt - it just sits there. `bypassPermissions` needs
  a one-time interactive disclaimer nobody is awake to accept. So the default is `auto`: risky
  actions get denied and the session keeps going.
- **One tag, one session**, held at all three ways in: `launch.sh` claims a tag with an atomic
  `mkdir` so a double launch is harmless, nothing can fork a running session, and `revive.sh`
  refuses any session whose transcript is still growing.
- **Review lanes a diff actually earns.** Correctness always; security, architecture,
  observability, reuse and simplification only where the change gives them something to find.
  Running all six every time is how seven tickets produced 44 specialist invocations, with review
  plus fixes at 59% of the sprint's tokens. Reviewers are asked for demonstrable regressions and
  unmet acceptance criteria, not elective hygiene.
- **FIND and FIX stay separate, but the fixer need not be a stranger.** The finder writes a local
  findings manifest and posts **one** consolidated PR comment, with inline anchors only where the
  exact line is the point. For a small fix set in files the implementer itself just wrote,
  `handback.sh` resumes that implementer with the manifest rather than paying for a fresh window
  to re-read its own code - seven brand-new fixer sessions once cost 103M tokens, a quarter of a
  sprint. It refuses when that window is too full or the session is gone, and the fallback is a
  fresh fixer.
- **Resume before restart.** Most night-time deaths are the API dropping the call, not the
  session's fault - and the conversation survives on disk. So the reviver resumes that
  conversation with a "carry on, do not start over" prompt before it ever rebuilds a ticket
  from scratch. Resume mints a new session id and drops the display name, so it also repoints
  the watcher; doing this by hand leaves a live session nobody is watching. When the ladder
  (resume, restart, abandon) runs out, the ticket is abandoned and the sprint moves on - one
  that delivers 7 of 9 tickets and says so beats one that loops on ticket 3 all night.
- **Verification decides completion, not the session's own word for it.** `DONE` means a session
  finished its work; it has never meant the branch is acceptable. A sprint once reported all 21
  stages complete over a red PR, and every stage was telling the truth about itself - the local
  check and CI simply did not check the same things, and a formatter failure was twice read as a
  warning-only lint rule. So `accept.sh` compares local HEAD to the **pushed** head and then reads
  the required checks GitHub actually ran, writing `state/ACCEPTANCE.verdict`; the tester writes
  `state/GOLDEN.verdict` separately. The morning report's headline comes from those two files.
- **Prompts are rendered, not retyped.** `bootstrap.sh` assembles the workspace and fails loudly
  on a missing script or fact; `render.sh` fills each prompt from one `facts.env` and **refuses a
  template with an unfilled slot**, because an unfilled verify command is a session that wakes at
  3am not knowing how to check its own work. One kickoff once generated 22 prompts and 29,266
  words, mostly the same repo path and thresholds retyped. The model now authors only the
  judgement: each ticket's scope, gotchas and acceptance criteria.
- **A closing wizard that is only the commands a human must run** - an apply, a paste, a click.
  No preflight stages, no status stages, no "did it work" stages: anything an agent could do, the
  sprint does itself or files as a follow-up ticket. A stage asking the user to do an agent's
  chore reads as a requirement and is really a handover. It ends the moment the feature is on;
  the canary window and the rollback drill are a runbook the user paces, not stages. When nothing
  needs setting up, the session does not run at all.
- **And that wizard is driven before it ships, not read.** A wizard is a state machine, and its
  defects are orderings: a probe above the change it measures, a failed apply walked past into
  the stages that assumed it. One 713-line wizard passed `bash -n`, passed shellcheck, passed a
  human reading, and shipped four of those at once. `wizard-dryrun.sh` swaps the library half for
  an instrumented copy, puts shims on `PATH` and nothing else, and drives the authored stages
  once per branch - every default taken, each confirm declined in turn, each command failed in
  turn - checking the traces against the contract each mutating stage declares. `DONE` requires a
  `PASS`.
- **A morning report with a full session ledger** - every session, including revived attempts,
  relays and budget waits, and what each one actually contributed.

Ships the plan skeleton, six prompt templates, twelve scripts, an offline test suite, and
`references/rationale.md` - the incident behind every rule above, kept out of the runtime path so
it costs nothing until somebody is deciding whether a rule can go.

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
| a review skill (e.g. `code-review`) | `night-sprint` | the FIND half of each review pair |
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
