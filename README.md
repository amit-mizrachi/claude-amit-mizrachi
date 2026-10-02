# amit-mizrachi

Seven [Claude Code](https://claude.com/claude-code) skills for running work you are not
sitting and watching - handing a session off, turning a feature into a spec and tickets, taking
it through the night, researching a product question end to end, taking a feature from idea to
plan to PR, and keeping a big effort's map legible - plus the macOS hook that stops your machine
sleeping through it.

## Install

```
/plugin marketplace add amit-mizrachi/claude-amit-mizrachi
/plugin install amit-mizrachi@amit-mizrachi
```

Start a new session (or `/clear`). The skills then appear as `amit-mizrachi:next-prompt`,
`amit-mizrachi:night-sprint`, `amit-mizrachi:product-research`, `amit-mizrachi:to-spec`,
`amit-mizrachi:to-tickets`, `amit-mizrachi:night-marathon`, and `amit-mizrachi:mywayfinder`.

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
- **Finished sessions are removed.** Once a tag is terminal and the chain has moved past it, the
  runner stops its session and takes it off the agent list with `claude rm`. The shared worktree
  and the transcript are kept, so `claude --resume <sessionId>` still reopens it. At the end only
  the conductor, with the morning report, is left on the list.
- **Tests run once, at the end.** Implementers, continuations and checkpoint fixers run only the
  static checks (format / lint, typecheck or compile). `FIX-FINAL` runs the full suite over the
  finished branch and fixes whatever is red, whichever ticket caused it.
- **Prompts are rendered, not retyped.** `bootstrap.sh` assembles the workspace and fails loudly
  on a missing script or fact; `render.sh` fills each prompt from one `facts.env` and **refuses a
  template with an unfilled slot**, because an unfilled verify command is a session that wakes at
  3am not knowing how to check its own work. One kickoff once generated 22 prompts and 29,266
  words, mostly the same repo path and thresholds retyped. The model now authors only the
  judgement: each ticket's scope, gotchas and acceptance criteria.
- **A morning report with a full session ledger** - every session, including revived attempts,
  relays and budget waits, and what each one actually contributed.

Ships the plan skeleton, six prompt templates, eleven scripts, an offline test suite, and
`references/rationale.md` - the incident behind every rule above, kept out of the runtime path so
it costs nothing until somebody is deciding whether a rule can go.

It also has a **research mode** (`mode: research`), which `product-research` drives: the same
runner, but each ticket is a research question, the worktree is a local repo with no remote,
`VERIFY` is a citation check, the one review re-opens the sources, and the sprint ends in a
published artifact instead of a PR. See `references/research-mode.md`.

### `product-research`

Researches a product question with **one approval** and no supervision. In your session it
asks what to research, what decision it informs, who reads it, which sources to use (it offers
the connectors you actually have, plus the web) and how deep to go. Then it writes a one-page
brief and asks you to approve it. **That is the last question.**

After the approval, a background conductor takes over:

1. `to-spec` turns the brief into a research spec, and `to-tickets` cuts it into 3-8 research
   questions - both told that the caller owns the approval gate, so neither asks anything.
2. A `night-sprint` in research mode answers the questions one session at a time. Each writes a
   findings file in which **every claim ends in a source citation** (a URL, or a connector
   reference such as a Slack permalink) or is marked as inference, and `research-check.sh`
   refuses anything else.
3. A final review re-opens the sources to check they say what the findings claim, and a fixer
   corrects what they do not.
4. `SYNTH` writes one page - the answer and what it means for the decision, findings by theme
   with confidence, where the evidence disagrees, the gaps, every source - and publishes it as
   a private artifact. You get the link in a push notification and in `REPORT.md`.

Three rules hold everywhere in the run:

- **Connectors are read only.** No session sends, posts, drafts, edits, comments or reacts. A
  question only a person could answer becomes a gap in the report.
- **Nothing is invented.** A source that would not open is a gap, not a citation.
- **The workspace is `~/claude-research/<slug>/`, never under `~/.claude`.** Claude Code
  guards writes there, and a background session stops on that prompt with nobody awake to
  answer it.

Needs Claude Code with the `claude` command (it starts background sessions with `claude --bg`)
and an account where `auto` permission mode is available. A plain claude.ai chat cannot run it.

### `night-marathon`

Takes a feature from an idea to one PR, with **one approval** at the start. In your session it
asks for the feature, the mode, how to test the build, which connectors may hold earlier talk
about it, and how deep to research. It writes a brief; you approve it. Then:

1. **Research.** A `night-sprint` in research mode answers what the plan needs to know. The
   repo is a source, read from a detached snapshot of `origin/<base>` and cited as
   `repo:<path>:<line> @<sha>`. When the feature has UI, one question is always the UI kit:
   the token files, the component packages, and the screens the new UI must look like.
2. **Plan.** The research sprint's last stage publishes a **short, UI-first** artifact instead of
   a findings page: mockups drawn from the repo's real tokens and components, in their real page
   shell, in every state that exists, each captioned with its components and import paths. Only
   the decisions that change what users see, are expensive to reverse, or split the evidence
   reach the page - at most five, each with a recommendation and a **Pick this** radio. The rest
   are decided and listed in one collapsed line each. A sticky bar copies your picks as text.
3. **Build.** A code `night-sprint` runs `to-spec` and `to-tickets` on the chosen plan (local
   files only - nothing is posted to a tracker at night), with every UI ticket pointing at its
   mockup, and delivers one PR.

Two modes decide what happens between 2 and 3:

- **`autonomous`** (default) - the conductor takes every recommended option and starts the build.
  You get the plan link, then the PR.
- **`review`** - the conductor stops and sends you the plan link. Pick on the page, press **Copy
  decisions**, `claude attach` to the conductor and paste. Picking is the approval; the build
  then runs without asking.

**One runner watches the whole run.** Each conductor - research, then each build - is a phase
in a phase chain (`night-sprint`'s `phase-chain.sh`), and one runner, detached from every
session, watches them all. When a conductor writes `DONE`, the runner launches the next phase.
When a conductor dies on an API error, the runner resumes it the way a ticket is revived, in its
own repo. A conductor that ended its turn on purpose, for example to wait for your picks, is left
alone. Every launch, death and revive is logged in `<workspace>/phases/state/EVENTS.log`, and the
reports name the time each one cost.

`night-sprint` gained what this needs: a kickoff with `approval: delegated`, where a calling
skill has already run the approval gate and nothing is asked, and `repo:` source locators in the
research citation check.

### `to-spec` and `to-tickets`

Bundled from Matt Pocock's [`mattpocock/skills`](https://github.com/mattpocock/skills) (MIT),
so `night-sprint` can cut its own tickets on a machine that has nothing else installed.

- **`to-spec`** turns what the conversation already settled into a spec - problem, solution, a
  long list of user stories, implementation and testing decisions, out of scope - without
  interviewing you again.
- **`to-tickets`** cuts a spec, plan or conversation into **tracer-bullet** tickets: thin
  vertical slices that each land green on their own, each naming the tickets that block it, in
  dependency order. Wide mechanical refactors get expand - migrate - contract instead.

Two changes from upstream:

- **Agents can invoke them**, not only a human typing the slash command. Upstream sets
  `disable-model-invocation: true`; here it is gone, so a conductor session or any agent can
  call them. When no human can answer (a headless or background session, or a caller that owns
  the approval gate), they decide for themselves instead of waiting on a question: `to-spec`
  lists its choices as assumptions, and `to-tickets` publishes and marks the breakdown **not yet
  approved by a human**. With a human in the session they still ask.
- **No setup step is required.** Upstream expects `/setup-matt-pocock-skills` to have written
  the repo's tracker config to `docs/agents/issue-tracker.md`. That is still honoured when it
  exists; when it does not, both fall back to local markdown under `.scratch/<feature-slug>/`,
  which is exactly where `night-sprint` looks for tickets.

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
| `to-spec`, `to-tickets` | `night-sprint` | cutting a feature into tickets when none exist yet - ships here |
| a review skill (e.g. `code-review`) | `night-sprint` | the FIND half of each review pair |
| `address-review` (or equivalent) | `night-sprint` | the FIX half of each review pair |
| a dev-environment skill | `night-sprint` | the optional test session that boots the stack |
| `artifact-design` | `mywayfinder` | built into Claude Code |
| `next-prompt` | `night-sprint` | the conductor relay - ships here |
| `night-sprint`, `to-spec`, `to-tickets` | `product-research` | the whole run after the approval - all ship here |
| `artifact-design`, `dataviz` | `product-research` | the final page - built into Claude Code |
| `night-sprint`, `to-spec`, `to-tickets`, `next-prompt` | `night-marathon` | both sprints and the hand-offs - all ship here |
| `artifact-design`, `artifact-diagramming` | `night-marathon` | the plan page and its mockups - built into Claude Code |

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

MIT - see [LICENSE](LICENSE). `to-spec` and `to-tickets` are adapted from
[`mattpocock/skills`](https://github.com/mattpocock/skills), also MIT - see
[`amit-mizrachi/THIRD_PARTY_NOTICES.md`](amit-mizrachi/THIRD_PARTY_NOTICES.md).
