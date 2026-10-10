---
name: night-sprint
description: Delivers a whole feature overnight through autonomous sessions, run one after another by default or side by side in blitz mode (`speed: blitz`, tickets on a dependency graph, each in its own worktree, landed onto the branch one by one), and asks the user nothing once it is invoked, all on ONE branch landing as ONE pull request. A conductor session writes no code - it sets the sprint up, then a deterministic runner launches each ticket, advances the chain, revives what dies and waits out spending limits, escalating only what needs judgement. Each implementer watches its own context window and hands its ticket to a fresh session before it fills. Gets or builds a ticket breakdown first (via a spec and a ticket-splitting skill), decides whether to review once at the end or also at checkpoints, runs every checkpoint review ASYNC (it reads a snapshot while the next ticket keeps building, and nothing waits for it) and fixes every finding of the night once, at the end, with only the review lanes that diff actually earns, optionally runs a test session that boots the stack or runs evals, and hands CI to a detached watcher session that fixes red checks on its own, so no sprint session (and nobody) waits on CI. Also runs in research mode (`mode: research`), where each ticket is a research question answered from cited sources and the sprint ends in one published artifact instead of a PR. Use when the user says "night sprint", "sprint this feature", "build this overnight", "run this while I sleep", "ticket after ticket", "blitz", or wants a feature taken end to end unattended in a single PR.
argument-hint: "<feature | spec path | ticket dir | issue URL> [speed: serial|blitz] [parallel: <n>] [test: none|dev-stack|evals|<command>] [permission: auto|<mode>] [approval: delegated] [mode: research]"
---

# Night Sprint

## Overview

One feature, delivered overnight by a **chain** of sessions: ticket 01 lands, hands off to
ticket 02, and so on. **Exactly one session touches code at a time**, all in **one worktree on
one branch**, so the sprint ends as **one PR** with no integration step.

**Reviews never stop the chain.** A checkpoint review is ASYNC: it reads a frozen snapshot of the
branch in its own worktree while the next ticket keeps building, writes its findings down, and
fixes nothing. `REVIEW-FINAL` carries every still-true finding forward, and `FIX-FINAL` fixes the
whole night's findings at once. The only review anything waits for is the final one.

**Blitz mode** (`speed: blitz`) is the exception to "one at a time", chosen at invocation and
never by default. Tickets run on their dependency graph instead of their numbering: every ticket
whose blockers have landed starts at once, up to `MAX_PARALLEL` (default 3, `parallel: <n>`),
each in its own worktree on its own branch. A finished ticket lands with `land.sh`, which merges
the sprint branch into it under a lock, has the ticket's own session fix the combined tree, and
fast-forwards the sprint branch. Still one branch, still one PR. See "Blitz mode" below.

You are the **conductor**. You never write product code. You set the sprint up, launch the first
ticket, arm the runner, and then handle only what a script cannot decide.

**`watch.sh` is a runner, not just a watcher.** It advances the chain, revives dead sessions and
waits out spending limits by itself, logging everything to `state/EVENTS.log`. It escalates a
short list of exceptions to you. Silence from it means the sprint is running. It runs
**detached**, started by `runner.sh start`, so nothing that happens to you or to your Monitor
stops it. You hear it through a Monitor on `runner.sh follow`.

**By default this is the sequential sibling of `orchestrating-parallel-delivery`.** That skill
splits work across concurrent sessions to save wall-clock. A serial sprint deliberately does not:
it is night time, nobody is waiting, and serial execution buys correctness - no frozen contracts,
no disjoint-file rules, no merge conflicts, no tracker. Blitz mode buys the wall-clock back with
the dependency graph and `land.sh`, and only when the invocation asks for it. If you catch
yourself fanning out implementers in a serial sprint, stop: that is blitz, and the user did not
choose it.

**Research mode.** If the invocation says `mode: research`, `facts.env` has `MODE=research`, or
`product-research` launched you, read `references/research-mode.md` now. It replaces the
kickoff, the reviews, acceptance and the PR below; the runner, the context rungs and everything
about reviving apply unchanged. A calling skill may render `SYNTH` from its own template
(`night-marathon` does, to publish a plan instead of a findings page); the chain is the same.

`references/rationale.md` holds the incident history behind every rule here. Read it when you
are changing the skill, not when you are running a sprint.

## Prerequisites - check these before kickoff, not at 3am

`next-prompt`, `to-spec` and `to-tickets` ship in this plugin. The rest are named by ROLE;
substitute whatever you use, and write the real names into `PLAN.md` at kickoff so the sessions
invoke the right thing.

| Role | What it does | Without it |
|---|---|---|
| a **code-review** skill | the review lanes the FIND step runs | nothing reviews the diff |
| an **address-review** skill | replies on external bot / human PR threads | external comments go unanswered |
| **`next-prompt`** (ships here) | the conductor handing itself on | the sprint dies when the conductor fills up |
| a **spec** skill (`to-spec` ships here) | turning a feature into a spec at kickoff | bring your own spec |
| a **ticket-splitting** skill (`to-tickets` ships here) | cutting that spec into tickets | bring your own breakdown |

A prompt naming an uninstalled skill is a session that stops at 3am with nobody awake to fix
it, and that is the cheapest failure to prevent. The **review step is the one hard dependency**:
a sprint without it still builds the feature and opens the PR, but nothing reviews the diff.
Decide that deliberately rather than discovering it in the morning.

## Kickoff (conductor, when the skill fires)

0. **Ask nothing - from the moment the skill fires.** Never call `AskUserQuestion` and never ask
   a question in text, at kickoff or after it. Every setting comes from the invocation or a
   default below; every judgement call you would have asked about goes into `LOG.md` under
   `## Decided without asking` and into the kickoff summary, so the user can read it later and
   stop the sprint if a call was wrong. The feature is the invocation's text, else the
   conversation that led here; with neither, stop and say what is missing - a failed kickoff,
   not a question. `approval: delegated` (a calling skill such as `night-marathon` started you)
   changes nothing here; it only says the caller may already have written the tickets.
1. **Settle speed, permission mode and the test session - FIRST, without asking.** Kickoff takes a
   while, so fix these before you read a ticket or check a verify command.
   - **Speed**: `speed: blitz` in the invocation (or "blitz" in its words) sets `BLITZ=1` in
     `facts.env`, and `parallel: <n>` sets `MAX_PARALLEL` (default `3`). Anything else is serial,
     `BLITZ=0`. Never choose blitz yourself: it costs more tokens and more quota per hour, and that
     is the user's trade to make.
   - **Permission mode**: `permission:` from the invocation, else **`auto`**. Record it in
     `PERMISSION_MODE`. `acceptEdits` still prompts on shell commands and a background session
     cannot answer a prompt, so it stalls in `blocked` all night. `bypassPermissions` needs a
     one-time interactive disclaimer nobody can accept for the user: if the invocation names it
     and `T01` then stalls on that disclaimer, switch `PERMISSION_MODE` to `auto`, relaunch, and
     log the switch.
   - **Test session**: `test: none|dev-stack|evals|<cmd>` from the invocation, else **`none`**.
     For the stack, find your repo's dev-environment skill and its boot command yourself and
     write both into `PLAN.md`; if you cannot find them, fall back to `none` and log it.
2. **Get the tickets.** The sprint needs a plan already cut into tickets in dependency order.
   Tickets exist (a `.scratch/<slug>/issues/` dir, tracker issues, a plan with numbered slices)?
   Read them all. None? Run the spec skill on the feature, then the ticket-splitting skill,
   **headless**: tell both that you own the approval gate and no human can answer, so they ask
   nothing and return their output unapproved. Do not show the plan to the user for approval;
   name the tickets in the kickoff summary instead. Copy the final tickets into
   `tickets/<NN>-<slug>.md` so the sprint has a frozen local copy even if the tracker changes
   overnight. **Blitz needs the "Blocked by" edges to be real**: an edge that only reflects the
   numbering serializes the graph and buys nothing. Tell the ticket skill so, and read each
   ticket's edges once yourself - a ticket that edits what another ticket edits heavily should
   block on it rather than race it.
3. **Ground the run, into `facts.env`.** One `KEY=VALUE` per line, and this file is what the
   renderer fills every prompt from:

       REPO, REPO_PATH, REPO_SLUG, SLUG, USER, WS, WORKTREE, BRANCH, BASE, TOOLCHAIN,
       VERIFY, FORMAT_CHECK, CONVENTIONS, TOTAL,
       CONTEXT_WINDOW, WARN_AT_USED, RELAY_AT_USED, CEILING_USED,
       BLITZ, MAX_PARALLEL

   **`VERIFY` is what PR CI runs, recorded for the watcher - never run it locally**, not even to
   check it resolves: the full suite runs only on the PR. **`FORMAT_CHECK` is the formatter or
   lint gate CI runs that the static checks would otherwise miss**; find it now, because local
   green that is not CI green is how a sprint reports 21 finished stages over a red PR.

   **`CONTEXT_WINDOW`** is `200000` normally and `1000000` on a 1M model. It cannot be inferred
   later - a 1M model records the same name in the transcript as the 200k one - and getting it
   wrong fires every rung at the wrong moment. Then the three thresholds, **all percent USED**,
   counting up from 0 exactly as `/context` reports it: **`WARN_AT_USED`** (`20`) the session
   starts nothing new; **`RELAY_AT_USED`** (`30`) the session hands its tag on; **`CEILING_USED`**
   (`60`) it hands off even with nothing to show. Defaults unless the user says otherwise.
4. **Decide the review cadence AND the review lanes** (see below) and state both.
5. **Bootstrap the workspace and the branch.** One command, and it is not optional:

       bash <SKILL_DIR>/references/bootstrap.sh <WS> <SKILL_DIR>/references

   It copies every script and template into the workspace so that editing the skill never
   changes a running sprint, chmods them, derives the one-value files the scripts read from
   `facts.env` so the two cannot drift, and **fails loudly if a script or a required fact is
   missing**. Four scripts `source "$WS/agents.sh"`: a workspace missing one file is a launcher,
   a reviver, a runner and a closer that all fail on their first line at 3am.
6. **Render the prompts rather than writing them.**

       bash <WS>/render.sh <WS> <WS>/implementer-prompt.md <WS>/prompt-T01.txt <WS>/vars-T01.env

   The renderer fills every slot from `facts.env` and **fails if one is left unfilled**, so the
   per-tag vars file has to be complete. You author only the judgement in it; this is the full
   set, by role, and nothing outside it is a slot:

   | Role | `vars-<TAG>.env` must set |
   |---|---|
   | implementer `T<NN>` | `TAG`, `NN`, `TICKET_TITLE`, `GOTCHAS`, `NEXT_TAG` (empty in blitz), `CONVENTIONS`, `TOTAL` |
   | review finder (`REVIEW-C<n>`, `REVIEW-FINAL`) | `TAG`, `CHECKPOINT`, `SCOPE`, `REVIEW_LANES`, `FIX_TAG=FIX-FINAL`, `NEXT_AFTER_FIX` |
   | `FIX-FINAL` | `TAG=FIX-FINAL`, `CHECKPOINT`, `FIND_TAG=REVIEW-FINAL`, `NEXT_TAG` |
   | `TEST` | `TOTAL`, `FIND_FINAL_TAG` |
   | `FIX-TEST` | `TAG=FIX-TEST`, `CHECKPOINT`, `FIND_TAG=TEST`, `NEXT_TAG` (leave empty - it decides its own) |
   | continuation (filled by the relaying session, not you) | `CONT_TAG`, `PREV_TAG`, `NN`, `TICKET_TITLE`, `NEXT_TAG` |

   **There is no `PR` slot, deliberately.** The draft PR does not exist at kickoff - it opens
   after `T01` lands - so a prompt that baked the number in could never render. The review
   prompts discover it themselves with `gh pr view --json number -q .number`.

   **`{{#BLITZ}}` / `{{^BLITZ}}` blocks resolve themselves.** `bootstrap.sh` resolves them in
   every workspace template from `BLITZ`, so the rendered prompts already hold only this sprint's
   mode. Never delete a blitz section by hand.

   **A checkpoint finder's `SCOPE` is a range, not a ticket list**, because in an async (and above
   all a blitz) sprint other work lands between two checkpoints. The first is
   `` git diff $(git merge-base origin/<BASE> HEAD)..HEAD ``; each later one starts where the last
   snapshot stood: `` git diff $(cat <WS>/state/REVIEW-C<n-1>.headsha)..HEAD ``.

   **What to render now:** every ticket prompt, every review finder, and `FIX-FINAL`. There is no
   checkpoint fixer. Render `TEST`
   only if the user opted in - and **when you do, also render `prompt-FIX-TEST.txt` from
   `review-fix-prompt.md`** with `FIND_TAG=TEST`, keeping its FIX-TEST-ONLY section and deleting
   the FINAL-ONLY one. The tester routes an in-scope failure to `FIX-TEST`, and `launch.sh`
   refuses a tag with no prompt file, so without this the repair route dies at
   `launch: no prompt file`.

   **What to delete from each rendered file:** the FINAL-ONLY section from a checkpoint review's
   find prompt; the FIX-TEST-ONLY section from `FIX-FINAL`; the FINAL-ONLY section from
   `FIX-TEST`; the two unused modes from the `TEST` prompt.
7. **Wire the chain and queue the rest.** Two mechanisms, one per kind of tag:
   - **The chain** - `state/<TAG>.next`, one tag per file. `advance.sh` reads these; a session may
     overwrite its own before it writes its status. Serial: `T01.next` -> `T02` ... the last
     ticket's `.next` EMPTY. Both modes: `REVIEW-FINAL.next` -> `FIX-FINAL`, `FIX-FINAL.next` ->
     `TEST` or empty.
   - **The queue** - `touch state/<TAG>.queued`, plus its dependencies: `state/<TAG>.after` (hard:
     each must end DONE, or this tag is SKIPPED) and `state/<TAG>.waits` (soft: each must merely
     have ended). `schedule.sh`, run by the runner every sweep, starts a queued tag the moment its
     dependencies settle. Queue:
     - each checkpoint finder, `.waits` = the last ticket of its scope (every ticket of its scope
       in blitz), plus `touch state/REVIEW-C<n>.snapshot` so it reads a frozen worktree;
     - `REVIEW-FINAL`, `.waits` = the last ticket (every ticket in blitz) and every checkpoint
       finder;
     - in blitz, every ticket: `.after` = its "Blocked by" tags, plus `touch state/T<NN>.isolate`.
     A ticket tag named in `.after` is settled through its relays: `T03` is DONE when the
     `T03c<n>` it relayed to is.
8. **Write `PLAN.md`** from `plan-template.md` - the goal, out-of-scope, ticket order, the
   golden path the tester walks, and the protocol every session follows.
9. **Launch the first work** - serial: ticket 01 with `launch.sh`; blitz: `bash <WS>/schedule.sh
   <WS>`, which starts every ticket with no blockers up to the cap - then start the runner and arm
   the Monitor that listens to it, and go into the monitor loop:

       bash <WS>/runner.sh start <WS>          # must print `runner: running`
       Monitor: bash <WS>/runner.sh follow <WS>   (timeout_ms 1800000; re-arm on every expiry)

   The runner changes to `<WS>` itself, so the folder you call it from does not matter. Still,
   never `cd` into `inputs/` or any folder a peer may re-copy: your Bash cwd persists between
   calls, and a command you run there fails the moment the folder is deleted.

## Roles

| Role | Count | Writes code | Job |
|---|---|---|---|
| **Conductor** (you) | 1 at a time, hands itself on | never | set up, arm the runner, handle escalations, report. **Never interrupts a working session** |
| **Implementer** | 1+ per ticket; **serial**, or up to `MAX_PARALLEL` at once in blitz | yes | build ONE ticket, static checks green (no tests), commit, hand off - and watch its own window. In blitz: in its own worktree, and it lands itself with `land.sh` |
| **Review finder** | 1 per review, **async** | **never** | run the selected lanes over a snapshot, triage, write the findings manifest, post ONE PR comment. A checkpoint finder launches nothing; `REVIEW-FINAL` carries every still-true checkpoint finding forward and decides whether `FIX-FINAL` runs |
| **Review fixer** | `FIX-FINAL`, plus `FIX-TEST` if the tester routes one | yes (fixes only) | work the whole night's manifest at once, reply on external threads, check, push. Static checks plus a few targeted tests, never the suite |
| **Tester** | 0 or 1 | no | exercise the built thing, report PASS/FAIL per step, write `GOLDEN.verdict` |
| **CI watcher** | 0 or 1, **outside the chain** | yes (CI fixes only) | started by `ci-watch.sh` from the final stage; waits for the required checks at the pushed head, fixes and pushes what is red, inherited base-branch failures included (three passes at most), takes the PR out of draft on green, writes `ACCEPTANCE.verdict`. **Nothing waits for it** - not the runner, not TEST, not you |

### The full suite never runs locally

**No session runs the test suite - not per ticket, not at the end.** Implementers,
continuations, finders and checkpoint fixers run only the static checks before they commit:
`FORMAT_CHECK`, plus a typecheck or compile when the repo has one. `FIX-FINAL` and `FIX-TEST`
may add **a few targeted test files** for the code their own fixes changed, and nothing more.
The suite runs on the PR, in CI. `FIX-FINAL` pushes, hands CI to the watcher (`ci-watch.sh`)
without waiting, and the sprint goes on or ends; the watcher fixes whatever CI finds red,
whichever ticket caused it, using the failing test files by name.

A suite run per ticket is the same suite paid for once per session, and a local run at the end
holds the sprint (and the user) for a run CI does anyway, on the commit that actually ships.

## Coordination

| Thing | Convention |
|---|---|
| Workspace | `~/.claude/night-sprint/<slug>/` - `facts.env`, `PLAN.md`, `tickets/`, `prompt-<TAG>.txt`, `vars-<TAG>.env`, `state/`, `LOG.md` |
| Pinned facts | `facts.env`, plus one-value files the scripts read: `WORKTREE`, `SLUG`, `PERMISSION_MODE`, `BRANCH`, `VERIFY`, `CONTEXT_WINDOW`, `WARN_AT_USED`, `RELAY_AT_USED`, `CEILING_USED` |
| Tags | `T01`..`TNN`, async finders `REVIEW-C1`.., then `REVIEW-FINAL` + `FIX-FINAL`, then `TEST`, `FIX-TEST` if the tester finds an in-scope failure, plus continuations `<TAG>c2`, `<TAG>c3` |
| Successors | `state/<TAG>.next`, written at setup, rewritable by the session **before** its status |
| Queue | `state/<TAG>.queued` + `.after` (hard deps) + `.waits` (soft deps), started by `schedule.sh` from the runner. A dependency whose `.after` ends BLOCKED or SKIPPED gets its dependents `SKIPPED: blocker <X>`, recursively. Finders never count toward `MAX_PARALLEL` |
| Own worktrees | `state/<TAG>.isolate` (blitz ticket: `<WORKTREE>-<TAG>` on `<BRANCH>--<TAG>`) or `state/<TAG>.snapshot` (finder: `<WORKTREE>-<TAG>`, detached at the branch tip). `launch.sh` creates it and records `state/<TAG>.cwd`; a relay copies `.cwd` to its continuation. Left on disk after the sprint for inspection |
| Landing (blitz) | `bash <WS>/land.sh <WS> <TAG> merge` then `publish` (or `abort`), under `state/land.lock`. Only a ticket's own session lands it |
| Branch / worktree | ONE of each: `<type>/<slug>` off `origin/<default>`, in `.claude/worktrees/<slug>` |
| Launching | `bash <WS>/launch.sh <WS> <TAG>` - never a bare `claude --bg`. It runs in `WORKTREE`, or in `state/<TAG>.cwd` when a tag has one (a phase conductor runs in its own repo, and `revive.sh` resumes it there) |
| Advancing | `bash <WS>/advance.sh <WS> <TAG>` - **the only thing that decides what runs next** |
| Reviving | `bash <WS>/revive.sh <WS> <TAG> <cause>` - never re-launch a dead tag by hand |
| Handing off | the SESSION does it, from its own prompt, when its own gauge says so. There is no conductor-side command and there must not be one |
| One tag, one session | many sessions per tag over a night, never two at once. `launch.sh` claims atomically; a session is never interrupted so never forked; `revive.sh` refuses any session whose transcript is still growing |
| Stopping | only `revive.sh` (a dead or blocked session, before it revives it) and `close.sh` (a session whose tag is terminal and whose turn has ended) ever stop a session, both through `stop_session` in `agents.sh`; `close.sh` then takes it off the agent list with `remove_session` (`claude rm`). Never hand-roll a stop or a removal: `claude stop` and `claude rm` take the **short 8-char id**, never the full `sessionId`. `claude rm` keeps the shared worktree (a sprint session runs in it but did not create it) and the transcript, so a removed session still resumes with `claude --resume <sessionId>` |
| Context | `bash <WS>/context-used.sh <SESSION_ID\|--self> <CONTEXT_WINDOW>` - percent USED, counting up |
| Status | `state/<TAG>.status` = `DONE` / `BLOCKED: <reason>` / `RELAYED: <TAG>c2` / `SKIPPED: <why>`, written **last** |
| Summary | `state/<TAG>.summary` - ONE line, what it actually did, for the ledger |
| Findings | `state/<TAG>.findings.md` - the manifest. The fixer's input, and it is LOCAL |
| Acceptance | `state/ACCEPTANCE.verdict` (CI: `PENDING` from `ci-watch.sh`, then `PASS`/`FAIL`/`UNKNOWN` from the watcher's `accept.sh`) and `state/GOLDEN.verdict` (the tester) |
| CI watcher | `state/ci-watch/` (`session`, `status`, `summary`, `prompt.txt`) and its own worktree `<WORKTREE>-ci`. Deliberately NOT `state/<TAG>.*` or `claim-*`: `watch.sh` globs those, and the runner must never revive, count or wait for the watcher |
| Manual steps | `state/<TAG>.manual` - appended the moment a session hits something only a human can do |
| Setup verdict | `state/SETUP.verdict` = `NEEDED` or `NONE` |
| Follow-ups | `state/FOLLOWUPS.md` - one line per real-but-out-of-scope thing |
| Durable ledger | `state/EVENTS.log` - every launch, advance, revive and pause, timestamped |
| Human view | `night-watch` (ships in this plugin's `bin/`) draws every sprint's progress from `state/`, read-only. Name it in the kickoff summary so the user can watch the night. It walks the `.next` chain, so keep every tag on it |
| Watching | the runner runs detached (`bash <WS>/runner.sh start <WS>`, pid in `state/runner.pid`, output in `state/runner.log`). You listen with `Monitor` on `bash <WS>/runner.sh follow <WS>`. The harness caps every Monitor at 30 minutes, so re-arm it at each expiry. That kills only the follower, never the runner, and the next follower picks up at the line where the last one stopped |

## The templates and scripts

| File | Use |
|---|---|
| `references/bootstrap.sh` | build the workspace: copy the scripts, derive the facts, fail on anything missing |
| `references/plan-template.md` | the `PLAN.md` skeleton: facts, goal, ticket order, golden path, acceptance, protocol |
| `references/implementer-prompt.md` | one ticket, one session |
| `references/review-find-prompt.md` | the FIND step - selected lanes, triage, the manifest, the fix route |
| `references/review-fix-prompt.md` | the FIX step - work the manifest, external threads, the acceptance gate |
| `references/test-prompt.md` | the opt-in tester - pick ONE of its three modes and delete the rest |
| `references/continuation-prompt.md` | a relayed tag's successor - sessions fill this one themselves |
| `references/render.sh` | fill a template from `facts.env` + per-tag vars, and refuse a half-filled one |
| `references/launch.sh` | atomic claim + launch + session-id capture. Refuses while the sprint is paused |
| `references/advance.sh` | the single transition owner of the chain: read `.status` + `.next`, start the successor |
| `references/schedule.sh` | the queue: start every queued tag whose `.after` / `.waits` have settled, up to the writer cap, and skip what a blocked dependency made impossible. The runner calls it each sweep |
| `references/land.sh` | blitz only: a ticket lands its branch on the sprint branch - merge under a lock, fix the combined tree, fast-forward and push |
| `references/watch.sh` | the runner: does the routine, escalates the exceptions |
| `references/runner.sh` | keeps `watch.sh` detached (`start`, `status`) and is your Monitor's command (`follow`): prints each new runner line once, and restarts a runner that died mid-run |
| `references/revive.sh` | the reviver, for dead sessions only: resume, then restart, then abandon |
| `references/phase-chain.sh` | one detached runner over a chain of CONDUCTORS (night-marathon's research conductor, then each build): launches each phase when the one before writes `DONE`, revives a conductor that dies |
| `references/close.sh` | removes a finished session from the agent list (stop, then `claude rm`) once its tag is terminal, so only the conductor is left at the end |
| `references/classify-error.sh` | what actually ended a session: transient / quota / auth / none |
| `references/accept.sh` | are the required CI checks green **at the pushed sha**? Run by the CI watcher, in its own worktree |
| `references/ci-watch.sh` | hand CI to ONE detached watcher session outside the chain, and return at once. A no-op while one is alive; replaces a finished or dead one |
| `references/ci-watch-prompt.md` | the watcher's prompt: sync to the pushed head, `accept.sh`, read the failing log, fix, push, repeat; ready on green, BLOCKED after three passes |
| `references/agents.sh` | shared: ask the harness for background sessions, with the `--cwd` fallback |
| `references/context-used.sh` | the gauge: percent of a window already USED |
| `references/rationale.md` | **maintainer only, never loaded at runtime**: the incident behind every rule here |
| `tests/run.sh` | offline tests for the classifier, the transition owner, the renderer and the `set -u` guards |
| `tests/blitz.sh` | offline tests for the queue, the landing lock, the render blocks and the relay's worktree |

**There is deliberately no script for the context rungs.** A session hands its own ticket on.

## Review cadence, and the lanes a diff earns

**Cadence:**
- **4 tickets or fewer, one subsystem** -> `REVIEW-FINAL` only.
- **5+ tickets, or the sprint crosses subsystems** (server + client, a schema change) -> a
  checkpoint at each natural seam, roughly every 3-4 tickets, plus the final one. Put one right
  after the ticket that lands a schema or interface everything else builds on.
- **Always at least one.** A sprint never ends without `REVIEW-FINAL`.

**Every review is async, and only the final one is waited for.** A checkpoint finder is queued,
not chained: the runner starts it when the last ticket of its scope ends, in a snapshot worktree
frozen at that commit, while the next ticket is already building. It writes its manifest, posts
one PR comment, and launches nothing. `REVIEW-FINAL` waits for every ticket and every checkpoint
finder, re-checks each checkpoint finding against HEAD, carries the ones still true into its own
manifest (`ORIGIN: REVIEW-C<n> F<k>`), and adds its own. `FIX-FINAL` fixes the lot in one pass.

**The cost, chosen on purpose.** A BLOCKER found at checkpoint 1 is not fixed until the end, so
tickets 4 to 9 may build on it and `FIX-FINAL` reworks them too. That is accepted: one fix pass
over the finished feature is cheaper than stopping the night for every review, and a finding
re-checked against the finished code is often already moot.

**Lanes: correctness always, the rest only when the diff gives them something to find.**

| Lane | Add it when the diff |
|---|---|
| correctness / code quality | ALWAYS |
| security | touches authn or authz, parses untrusted input, handles a secret, crosses a network boundary, builds a query or path from user data, changes CORS or origin checks |
| architecture | changes a contract, schema, public interface, deployment topology or cross-service call |
| observability | adds or changes logging, spans, metrics, alerts or an error-handling path |
| reuse / extraction | adds general-purpose logic that belongs in a shared package, or reimplements what one already exports |
| simplification | is the FINAL review, or is large enough that its shape is in question |
| prompt-reviewer (separate) | changes a prompt, skill, agent definition or template |

**Running all six every time is the expensive habit this replaced** - one night, 44 specialist
invocations across seven reviews, and review plus fixes at 59% of the sprint's tokens. Ask each
lane for demonstrable regressions and unmet acceptance criteria; elective hygiene is a follow-up.
High-risk changes stay eligible for the broad set - say so when you pick it.

**FIND and FIX are separate steps.** The finder never edits a file, runs the verify command or
commits. The fixer never runs a review of any kind. One window cannot do both: it pays for the
review twice and dies mid-triage, losing the triage.

### What runs after REVIEW-FINAL

| Route | When | How |
|---|---|---|
| **SKIP** | no finding in the whole night's manifest AND no open bot / CI / human comment | write `SKIPPED` to `state/FIX-FINAL.status`, point `.next` past it, hand CI to the watcher |
| **FIX-FINAL** | anything at all to fix | `launch.sh FIX-FINAL` - always a fresh session, because its prompt carries the acceptance gate |

There is no checkpoint fixer and no handback: the session that wrote the code has moved on to
its next ticket by the time its review lands, which is the whole point. (`handback.sh` resumed it
for small checkpoint fix sets; it went when checkpoint fixes did.)

**The manifest is local and stays local.** `state/<TAG>.findings.md` carries
`ID / AT / SEVERITY / LANE / WHERE / ISSUE / EVIDENCE / ACTION` per finding (`AT` is the commit
the finder read, because by the time anyone acts on it more has landed), and REVIEW-FINAL's is
what the fixer reads. The PR gets **one** comment per review, with inline anchors only for
BLOCKER and HIGH where the exact line is the point. External bot, CI and human threads are
different: each gets a reply, because somebody outside the sprint is waiting on it.

## Blitz mode - the dependency graph, and landing

`speed: blitz` trades tokens and quota for wall-clock. Use it when the user asked for it; never
infer it.

- **The graph.** Every ticket is queued with its real blockers in `.after`. `schedule.sh` starts
  each one whose blockers are DONE, oldest first, while fewer than `MAX_PARALLEL` writers run.
  A BLOCKED or abandoned ticket skips exactly its dependents; everything else goes on, so the
  conductor no longer skips them by hand.
- **One tree per ticket.** `launch.sh` cuts `<BRANCH>--<TAG>` from the sprint branch as it stands
  at launch, in `<WORKTREE>-<TAG>`, so a ticket starts with every blocker already merged. No two
  sessions ever share a tree - that is still the DUP rule, kept by giving each its own.
- **Landing.** A ticket is done when the COMBINED tree passes. `land.sh merge` takes
  `state/land.lock` and merges the sprint branch into the ticket branch; the ticket's own session
  resolves conflicts (it knows its side) and re-runs the static checks; `land.sh publish`
  fast-forwards the sprint branch and pushes. The lock makes the fast-forward always possible and
  serializes pushes. A lock whose owner ended without releasing it, or older than 90 minutes, is
  taken over and logged.
- **The shared worktree is quiet until the end.** No session writes `<WORKTREE>` while tickets
  run; `land.sh` only fast-forwards it. `REVIEW-FINAL` reads it, and `FIX-FINAL`, `TEST` and
  `FIX-TEST` work in it, after every ticket has landed, exactly as in a serial sprint.
- **What it does not buy.** Three writers spend the rolling session limit three times as fast; a
  night bound by budget waits reaches the wait sooner rather than finishing sooner. Name that in
  the morning report when it happened.

## Monitor loop - what the runner escalates, and what you do

Arm one `Monitor` on `runner.sh follow` (timeout 30 minutes, the harness's cap) and re-arm it
every time it expires. The runner it listens to is detached and keeps going between Monitors.
The runner handles launches, advances, revivals, quota
waits and closing finished sessions itself, and logs all of them to `state/EVENTS.log`. **It speaks only for these:**

| Event | Do |
|---|---|
| `BLOCKED <tag> <reason>` | It hit something real - do **not** revive. Record it, skip every ticket that lists it as a blocker, continue with the rest. In blitz `schedule.sh` already skips its dependents (`SKIPPED: blocker <tag>`) and the others keep running. |
| `DUP <tag> <id> <id> ...` | **Two agents in one worktree.** Drop everything and fix this first (below). Nothing else the runner says about `<tag>` can be trusted while it holds. |
| `AUTH <tag>` / `AUTH-PAUSE <...>` | The CLI is logged out or its token expired. No retry can fix it and the sprint is **stopped** - the runner idles rather than spending revives against it. The tag keeps **no** terminal status, because nothing about the work is wrong. Report it and give the exact two-step recovery: `claude /login` in a real terminal, then `bash <WS>/revive.sh <WS> <tag> auth-retry`, which clears the hold and resumes the conversation. |
| `BUDGET <tag> <class> retry-at <hh:mm>` | Out of capacity. **There is nothing to run** - the runner is waiting and will resume by itself. Log it; the morning report must explain the gap. |
| `BUDGET-EXHAUSTED <tag>` | Capacity never came back. Report what landed and what did not. |
| `HELD <tag>` | A successor was not launched because the sprint is paused. It launches when the pause clears. Nothing to do. |
| `REVIVE-REFUSED <tag>` | The reviver would not touch it - usually because it is still working. Read `state/EVENTS.log` and decide. |
| `NEEDS-PR` | Open the **draft** PR. Early CI and early bot review are why it opens after the first ticket rather than at the end. |
| `STRANDED <tags>` | A successor is wired (or a tag claimed) but no session and no status appeared for five sweeps. Something failed to launch it: check `state/<tag>.launch.log` and `EVENTS.log`, then launch it with `launch.sh` (remove a stale `state/claim-<tag>` first only if no session exists). |
| `UNCLOSED <tags>` | The runner's last pass could not remove these finished sessions from the agent list. The work is not affected. Name them in the morning report so the user can `claude rm <id>` them. |
| `SWEEP 0 tags= all-sessions-terminal` | The runner **exited** and has removed every finished session - nothing but you is on the agent list. Your follower exits with it. Tags left? Launch the next, `runner.sh start`, and **re-arm the follower**. Sprint complete? Write the morning report. Never leave the sprint with no running runner and work outstanding. |
| `RUNNER-RESTARTED` | The runner had died mid-run (killed, a restart of the machine) and the follower started it again. Nothing to do. Name it in the morning report. |
| `RUNNER-DOWN` | The runner died three times in 30 minutes. Nothing is advancing or reviving the sprint. Read `state/runner.log`, fix the cause, then `runner.sh start` and re-arm the follower. |
| `AGENTS-UNREADABLE` | `claude agents` failed three sweeps in a row, so the runner cannot see any session and revives nothing. Run `claude agents --json --all` from `/` by hand. If that works, the runner's cwd is the problem (`lsof -a -d cwd -p $(cat <WS>/state/runner.pid)`): kill it and `runner.sh start <WS>` again. If it fails too, the CLI is the problem - report it. |
| `SWEEP <n> tags=...` | A heartbeat, and only after a full hour with nothing to say. Nothing to do. |

Everything else - `DONE`, `RELAYED`, `SKIPPED`, `DIED`, `STALLED`, `STUCK`, `OVERDUE` - the
runner handles and logs. You do not see them, and you do not need to: `state/EVENTS.log` plus
`state/*.status` and `state/*.summary` are what the ledger is built from at the end.

**`--observe` turns the acting off** and prints every verdict, which is the old behaviour. Useful
for debugging a sprint by hand; never what a night run wants.

**The conductor holds itself to the same two rungs.** You are the longest-lived session with the
most events to absorb, so your death costs the most. Measure, do not estimate:

    bash <WS>/context-used.sh --self <CONTEXT_WINDOW>

Run it **at every event you receive**. At **`WARN_AT_USED`% used**, narrow yourself: no reading
the PR diff to understand a finding, no opening a ticket file out of curiosity, no investigating
a failure an implementer owns. Log the event, take the scripted action, move on.

At **`RELAY_AT_USED`% used, relay yourself** - do not wait, and do not see one more ticket
through:

1. Flush live state to `LOG.md`: every ledger row, which tags are open under which session ids,
   what you were about to do.
2. `/next-prompt` a fresh conductor whose prompt points at the workspace and says: read
   `PLAN.md` + `LOG.md` + `state/`, check `runner.sh status`, arm its Monitor on
   `runner.sh follow`, resume the monitor loop, hold itself to the same two rungs.
3. Record the relay as its own ledger row, stop your own Monitor, then stop. Do **not** stop the
   running sessions or the runner - the new conductor adopts them.

`facts.env` + `PLAN.md` + `LOG.md` + `state/` are written so a cold conductor can pick the sprint
up without your context. Relay as many times as the night needs.

## Context - two rungs, and a ticket may take more than one session

A context window is smaller than some tickets. A session that pushes on until it is full does
not stop cleanly: it thrashes, compacts away the reasoning that mattered, and at worst dies
mid-edit having written none of it down.

So the sprint hands off **early**, while the session still has most of its window to explain
itself. `T03` becomes `T03 -> T03c2 -> T03c3`: **one ticket, several sessions, still strictly one
at a time.** This is the normal way a ticket gets built. A sprint would rather run three fresh
sessions on a ticket than one exhausted one.

| Rung | Reading | The session does | You do |
|---|---|---|---|
| **Narrow** | `WARN_AT_USED`, 20 | Starts nothing new: no new subsystem, no refactor past the ticket, no wide reading. Drives what it is on to a committed state | nothing |
| **Hand off** | `RELAY_AT_USED`, 30 | Consolidates, writes a filled continuation prompt, launches its own successor | nothing |

**Both rungs belong to the session and only to the session.** You have no command for either and
there must not be one. The whole mechanism lives in the prompt: every template carries the gauge,
both rungs, the checkpoints at which to measure, and the handoff. **That is what to invest in when
a sprint handles its window badly** - not a script that reaches in from outside.

**Two guards keep the early handoff from becoming waste.** A session **one command from green
finishes** instead of splitting. A session that has **not changed a single file does not hand
off** - its successor would start where it did, minus the reading, which is how a ticket loops all
night without being built. Past `CEILING_USED` that second guard expires: hand off anyway, and say
plainly that the ticket was bigger than the plan thought.

**`RELAYED` is not `DONE`.** `DONE` releases the next ticket; a relayed ticket is still being
built. `advance.sh` knows the difference - it launches the continuation tag, never the next
ticket - which is why nothing else may make that decision.

**The gauge counts UP:** 0 is fresh, 100 is full, exactly as `/context` reports it. Every
threshold in the sprint reads the same way.

## Nothing interrupts a working session

**There is no way to send a message into a running background session.** This is the single rule
that shapes everything above. The workaround it used to have - `claude stop` plus
`claude --bg --resume` - **forked** the session whenever the stop failed, putting two agents in
one worktree with the watcher following only one. That mechanism was removed, not fixed.

What replaced it is the prompt. Each session measures itself with `context-used.sh --self`,
narrows at `WARN_AT_USED`, and at `RELAY_AT_USED` writes its own continuation prompt and launches
its own successor. One rule for every role, including the conductor.

**So when a session is working, the answer is always "nothing".** A session looks slow: let it
run. The only two things you may act on are a tag that has not started (`launch.sh`, via
`advance.sh`) and a session that is already gone (`revive.sh`, which refuses anything whose
transcript is still growing). If you find yourself wanting to tell a working session something,
the fix is upstream: put it in the template so the next sprint's sessions already know it.

## One tag, one session

A tag may burn through many sessions in a night - handed on, revived - but **never two at once**.
Three things hold the invariant, one per way in: `launch.sh` claims a tag with an atomic `mkdir`;
nothing interrupts a working session, so nothing can fork one; `revive.sh` refuses any session
whose process is alive with a transcript that grew recently, and stops what is left by **short
id** before resuming. **An agent list that cannot be read is UNKNOWN, never empty**: nothing is
called dead, stopped, closed or revived on it. A resume that finds the old session still running
(the harness says "started a copy") stops the copy and keeps the original, and a resume that
started but did not resolve never falls through to a restart.

**When `DUP <tag> <id> <id> ...` fires**, the invariant broke anyway. Fix it before anything
else:

1. **Find the live one.** Compare `~/.claude/projects/*/<sessionId>.jsonl` - the freshest mtime
   with the most lines is the session actually doing the ticket. It is usually **not** the one
   `state/<tag>.session` points at.
2. **Stop every other one** by short id, and verify with `claude agents --json` that one remains.
3. **Repoint** `state/<tag>.session` at the survivor, or the runner reads a corpse all night.
4. **Audit the overlap.** Diff the transcripts over the window both were live and list the files
   both touched. Append that list to the next review prompt as a mandatory extra audit.

   Then, and **this is the one time you may interrupt a working session**, hand the survivor that
   list and tell it to **re-read those files from disk** before trusting its own memory. The rule
   exists to stop you steering a session whose view of the world is sound; this one's is provably
   wrong, because another agent overwrote its files while it was not looking. Stop it by short
   id, confirm the process is gone, resume it with the list, and repoint `state/<tag>.session`
   at the id the resume produced.
5. **Log it** and carry it into the morning report. A night where two agents shared a worktree is
   a night whose diff needs a closer read than usual.

## Who watches the conductor - the phase chain

A sprint's own runner watches its tickets, not its conductor. When another skill chains
conductors - `night-marathon` runs a research conductor, then one build conductor per PR - the
conductors and the hops between them get a runner of their own: `phase-chain.sh` sets up a
workspace whose tags are PHASES (a `PHASE_CHAIN` marker, a `state/<PHASE>.cwd` each, `.next`
wiring) and starts ONE `watch.sh` over it, detached through `runner.sh` like every runner. Pass
the run's `CONTEXT_WINDOW` to `phase-chain.sh init`, or the runner measures every conductor
against 200k. A conductor writes `DONE` to its phase status as its last action and the runner
launches the next phase. A conductor that dies is classified and resumed in its own cwd, and the
session file is repointed.

In a phase chain, a conductor that ended its own turn with no error is **waiting, not dead** -
for the user's picks, its `Monitor`, or its relay - and is left alone. No conductor is ever
closed. Two rules keep that from hiding a stuck one:

- **A wait needs something to end it.** If the turn has been closed for 35 minutes or more, and
  the session runs no tool command (no Monitor, no background Bash), it is `UNARMED`: nothing will
  ever wake it, so the runner resumes it and tells it to re-arm. The one wait on a person is the
  review gate. A conductor marks it with `state/<PHASE>.waiting-on-user` before it ends its turn,
  and deletes the file when the answer arrives.
- **A conductor's ladder is per incident.** Only the rungs of the last 60 minutes count, so a
  build that lives all night is not abandoned for two dropped connections hours apart. When the
  ladder does run out, the abandon rung writes the status and leaves a live conductor running.

If you are a phase conductor, your prompt names your session and status files; never launch the
next phase with `claude --bg`.

## Reviving - classify first, then resume before you restart

Most night-time deaths are not the session's fault. The API drops the call, stalls mid-stream, or
returns 529 or 500, and the process is gone. **The conversation survives on disk** - everything
it read, every decision, the edit it was halfway through. A resume costs one prompt and picks up
mid-thought. Resume is not a fallback, it is the first move.

**But not every death wants a retry, and that is the first thing `revive.sh` settles.**
`classify-error.sh` reads the transcript and names the class:

| Class | What it means | What happens |
|---|---|---|
| `transient` | dropped connection, stalled stream, 529, 500, DNS, timeout | the ladder below |
| `quota-session <epoch>` | the rolling session limit, **with the reset time it names** | park the tag, write `state/PAUSED`, wait exactly that long, resume |
| `quota-spend` | the org monthly spend cap. No reset time - a human must raise it | park, back off 20 / 40 / 60 minutes, let the next resume be the probe, give up after 8 waits |
| `auth` | logged out, expired token, subscription disabled | park the sprint and **write no terminal status** - a human runs `/login`, then `revive.sh <WS> <tag> auth-retry` |
| `none` | no terminal error, or it carried on afterwards | nothing to revive |

**While paused, nothing new launches.** `launch.sh` and `advance.sh` both refuse, because every
fresh session against a cap that is already refusing requests spends one more refused request.
For quota the runner clears the pause and resumes the parked tags by itself. For **auth** it
cannot: it idles until a human logs in and runs `revive.sh <WS> <tag> auth-retry`. That cause is
how a caller says "I have dealt with the reason this stopped" - the transcript still ends on the
same error, so classifying it again would park the tag for ever.

**Faster polling cannot resolve a spending cap.** Naming the failure can. Two reviews once
stopped on org spend-limit errors, recovery treated them as ordinary stalls, and 3h32m went
missing - about a third of that run - while the log called it a permission stall.

The ladder, for failures a retry can fix, cheapest rung first:

| Rung | What it does | Budget per tag |
|---|---|---|
| `resume` | `claude --bg --resume` on the same conversation, told to carry on and **not** start over | 2 for `transient`, 1 otherwise |
| `restart` | fresh session on the original prompt, plus a RESUME block naming which commits already landed | 1 |
| `abandon` | writes `BLOCKED: ABANDONED ...` so the sprint moves on | - |

**Two things make hand-reviving wrong**, and are why the script exists. A resumed session gets a
**new session id** and does **not** inherit its display name, so a stale id in
`state/<tag>.session` is a live session nobody is watching. And each `(tag, verdict)` is emitted
once, so without clearing that tag's rows from the seen-file, a revived session that dies again is
never reported at all.

When the ladder runs out the tag is ABANDONED: record it, skip its dependents, carry on. A sprint
that delivers 7 of 9 tickets and says so plainly beats one that loops on ticket 3 all night. Log
**every rung** as its own ledger row. `revive.sh` writes only rungs to `state/<tag>.revivals`. A
refusal ("still working") goes to `EVENTS.log` and costs nothing.

## Acceptance - what "delivered" means

**Three different facts, three different files.** A sprint once reported all 21 stages complete
over a red PR - and every stage was telling the truth about itself.

| File | Written by | Means |
|---|---|---|
| `state/<TAG>.status` | each session | that session finished, was blocked, or handed on |
| `state/ACCEPTANCE.verdict` | `ci-watch.sh` (`PENDING`), then `accept.sh` run by the CI watcher | the required CI checks **at the pushed head sha**: `PENDING` / `PASS` / `FAIL` / `UNKNOWN` |
| `state/GOLDEN.verdict` | the `TEST` session | the golden path actually walked: `PASS` / `FAIL` / `UNKNOWN` |

`DONE` has never meant "the branch is acceptable". **The headline verdict comes from the last
two**, and a sprint whose stages all said DONE while `ACCEPTANCE.verdict` says FAIL did not
deliver - the report says so in its first line.

### Nobody waits on CI

The sprint does not wait for CI, and neither does the user. The last session that pushes code -
`FIX-FINAL`, or `REVIEW-FINAL` when it routes SKIP, or `FIX-TEST` after its repair - runs
`ci-watch.sh` and then advances as usual: to `TEST`, or to the end of the chain. `ci-watch.sh`
starts ONE detached CI watcher session **outside the chain**, in its own worktree
(`<WORKTREE>-ci`), and returns at once. The watcher waits for the required checks, reads a failing
log, fixes, pushes (never with force), and repeats - three repair passes at most - then takes the
PR out of draft on green, or leaves it in draft with one PR comment naming the red lanes. It writes
`state/ACCEPTANCE.verdict` and `state/ci-watch/status`.

So **`PENDING` is a normal verdict at report time**, not a failure: the report says CI was handed
to watcher `<id>` and stops there. It never polls, sleeps or re-arms anything to wait for the
result. A second `ci-watch.sh` call while a watcher is alive is a no-op (it always re-reads the PR
head), so a `FIX-TEST` push is checked by the same watcher, or by a fresh one if the first already
finished. Because the watcher may push to the shared branch while `FIX-TEST` runs, `FIX-TEST` may
`git pull --rebase` its own unpushed commits - the one exception to "never rebase".

`accept.sh` compares the watcher's HEAD to the pushed head first: a green check on a commit nobody
pushed proves nothing. **Local green is not CI green** - a formatter failure was twice read as a
warning-only lint rule - which is why `FORMAT_CHECK` is a pinned fact, and why a session that finds
a gate CI runs which `VERIFY` misses should say so.

## The manual steps

A sprint can land every ticket green and still leave the user with nothing they can run: the code
is merged, the API key is not pasted, the terraform unit is not applied, the flag is off. Those
steps are a human's by definition, and an unattended agent should not be doing them at 4am - but a
sprint that ends without naming them ships a feature nobody can turn on.

**Collect as you go.** Every session appends to `state/<TAG>.manual` the moment it hits something
it cannot do:

    STEP:     <one line: what a human must do>
    WHY:      <what breaks without it - the concrete failure, not "for configuration">
    WHERE:    <the URL, dashboard path or command, as concretely as it is known>
    VALUE:    <ENV_VAR_NAME, or "none" for a pure action>
    LANDS:    <.env | github secret | terraform var | a service | nowhere>
    SECRET:   <yes|no>
    BLOCKING: <yes = the feature does not work at all without it | no>

**Per-session, not reconstructed at the end**: the diff shows a new `process.env.FOO`, but not
that FOO's key lives behind a dashboard toggle T04 spent an hour finding at 02:00. That knowledge
exists in one session's window and dies with it.

### What counts as a manual step - both tests, every time

**TEST 1 - REQUIRED.** The shipped feature does not work until this happens. Not "would be
convenient": broken or unreachable in a real environment until it is done.

**TEST 2 - HUMAN-ONLY.** No agent could have done it: a credential no agent holds, a console no
agent can reach, a human approval, or a production mutation policy puts on a person.

| Passes both - a manual step | Fails test 1 - a report line | Fails test 2 - an agent's job |
|---|---|---|
| A secret, credential or token to paste or rotate | A `.env.local` a developer fills to run the app on their laptop | Adding a var to `.env.example` |
| A deploy, provision, terraform / terragrunt apply | Drift that predates the branch and the branch did not make matter | Writing or fixing a migration file |
| A migration against a real database | A judgement call the user may want to reverse | Wiring a config key the code should read itself |
| A third-party app or OAuth client to register | Anything already set - check live state first | Updating a README or runbook |
| A dashboard setting, DNS record, access rule or flag to flip | Merging the PR and deploying - always the user's, always named | Adding the workflow step that runs the migration |
| A resource that must exist and no code creates it | A follow-up improvement, however good | Any code change at all |

Test 1 keeps the list short: a pure front-end refactor of an already deployed app needs nothing,
and saying so in one line is the correct deliverable. Test 2's failures are worse because they
look useful: **a step asking the user to do something an agent could have done reads as a
requirement when it is really a chore handed over.** The session that
finds one either does it - it has a worktree, a branch and permissions - or files one line in
`state/FOLLOWUPS.md`.

### Nothing to set up is a finding

`REVIEW-FINAL` applies both tests to every `state/*.manual` block and writes
`state/SETUP.verdict` - `NEEDED` or `NONE`. It sweeps the diff there because it already has the
whole diff loaded, which is what makes a `NONE` verdict trustworthy rather than merely unrecorded.
A `TEST` session, if one runs, settles the verdict last.

On `NONE` the morning report states "nothing to set up" as a **finding**, naming what was swept
to reach it.

No real secret value is ever written into a prompt file, `LOG.md`, or the PR body.

## Session ledger and the morning report

The user wakes to one message and needs to reconstruct a night they slept through, so the report
is **an account of who did what**, not just a status.

`state/EVENTS.log` already holds every launch, advance, revive and pause, timestamped, written by
the runner as it happened. Build the ledger from it plus `state/<TAG>.session`, `.status` and
`.summary`, and append rows to `LOG.md` as events arrive rather than reconstructing at the end.
One row per session **including every revived attempt, every context relay, and every conductor
relay**:

| Tag | Session id | Name | Role | Verdict | What it did |
|---|---|---|---|---|---|
| T01 | `a1b2c3d4` | ns-<slug>-T01 | implementer | DONE | one line from `.summary` |
| T03 | `e5f6...` | ns-<slug>-T03 | implementer | DIED transient | how far it got before the API dropped it |
| T03 | `9a8b...` | ns-<slug>-T03-r2 | implementer (resumed) | DONE | what it finished after the resume |
| T05 | `c3d4...` | ns-<slug>-T05 | implementer | RELAYED to T05c2 at 31% used | what it landed before handing on |
| REVIEW-C1 | `...` | ns-<slug>-REVIEW-C1 | review finder (async, beside T04) | DONE | lanes run, n findings posted, n deferred, n rejected |
| REVIEW-C2 | `...` | ns-<slug>-REVIEW-C2 | review finder | BUDGET-BLOCKED 1h59m | the wait, and what it finished afterwards |
| REVIEW-FINAL | `...` | ns-<slug>-REVIEW-FINAL | review finder | DONE | n carried forward, n resolved by later work, n new |
| T06 | - | - | not launched (blitz) | SKIPPED | blocker T04 BLOCKED |

A ticket that took three sessions and two relays is exactly what the user wants to see. Read it
carefully though: **relays are the normal shape, not a signal.** A ticket that relayed twice is
ordinary; one whose relay came from `CEILING_USED` - a session that burned 60% of a window
without producing anything - says the breakdown was wrong. Say which kind each was. **Name every
budget wait with its duration**: that is usually the largest single line item in the night's
wall-clock, and it is not a failure of the work.

The final message must contain, in this order:

1. **The verdict in one line** - what the user actually has this morning, taken from
   `state/ACCEPTANCE.verdict` and `state/GOLDEN.verdict`, **not** from "every stage said DONE".
   Read them as they stand when you report; `PENDING` means "CI handed to watcher `<id>`" - say
   that, and do not wait for it to change.
2. **The PR** - URL, draft or ready, and the CI line: the watcher's session id and
   `state/ci-watch/status` if it has finished (`claude attach <id>` to follow it).
3. **Ticket outcomes** - every ticket as landed / blocked / abandoned, with the reason for
   anything not landed. Never omit a dropped ticket.
4. **The session ledger** - the full table above.
5. **Review + test results** - findings fixed vs rejected vs deferred; the tester's per-step
   PASS/FAIL; which review lanes ran and which were skipped.
6. **Time lost to things that were not the work** - budget waits, auth stalls, revivals.
7. **Follow-ups** - `state/FOLLOWUPS.md`, verbatim, ready to become tickets. An empty file is a
   fine answer; say so.
8. **What needs a human** - decisions and blockers waiting on them.
9. **Turn it on** - every `state/*.manual` step that passes both tests, in dependency order.
   This is the part the user acts on first, so it must need no thinking.

   **If `state/SETUP.verdict` reads `NONE`, this whole item is one line**: "Nothing to set
   up", plus what was swept to reach it. Then name the two things that are always the user's:
   **merge the PR, and deploy**. State it positively - "no setup needed" is a finding, not an
   empty section.
   - **The commands**, each paste-ready into a **fresh** terminal: an absolute `cd`, the
     toolchain line, then the command. Nothing left to work out.
   - **Every value a step needs**, as a table: `Value | Where to get it | Secret? | Where it
     lands`. "Where to get it" is the path a human walks, or the exact read command. A row that
     just names a hostname sends the user hunting.
   - **The gates**: which step waits on something to merge, deploy or approve.
   - **How to know it worked** - the check that proves the feature is live.

## The PR

Open **one draft PR** as soon as `T01` lands - the runner raises `NEEDS-PR` for it. Early CI and
early bot review give the checkpoint reviewers something real to address. Every later session
pushes to the same branch, so the PR grows all night. The CI watcher flips it out of draft once
`accept.sh` says PASS - never before, and no sprint session does it. Never a second PR.

**Never merge and never deploy** - those are the user's, always. If a required check has no
ticket to point at, open the PR anyway and report the red check. Never fabricate a ticket id and
never bypass hooks with `--no-verify`.

## Red Flags - STOP

| Rationalization | Reality |
|---|---|
| "Tickets 3 and 4 are independent, I'll run both." | In a serial sprint, serial is the contract - it is what removes conflicts and integration. Concurrency is blitz mode, and only the invocation turns it on. |
| "This is a big sprint, I'll switch it to blitz." | Blitz spends more tokens and quota per hour; that trade is the user's. Run what they invoked. |
| "The checkpoint found a BLOCKER - I'll launch a fixer now." | Reviews are async and fixes happen once, in `FIX-FINAL`. REVIEW-FINAL re-checks it against the finished code and carries it forward. |
| "Two blitz tickets touch the same file, the merge will sort it out." | It will, at the price of a conflict at landing. When the overlap is heavy, make one ticket block the other at kickoff. |
| "The blitz ticket is green on its own, mark it DONE." | DONE comes after `land.sh publish` says LANDED - the combined tree is what ships. |
| "I'll just implement this small ticket myself." | The conductor writes no product code. Your context is the scarcest resource of the night. |
| "No plan yet, I'll figure out tickets as I go." | Cut a spec and a ticket breakdown first, headless, and name the tickets in the kickoff summary. A sprint with no breakdown builds the wrong thing 9 times. |
| "I'll just check this one setting with the user before I start." | The sprint asks nothing once invoked. Take it from the invocation or the default, log it under `Decided without asking`, and go. A question at kickoff is a sprint that has not started when the user comes back. |
| "Run all six review lanes, it is more thorough." | It is five reviewers reading the same code to report nothing. Correctness always; the rest only where the diff gives them something to find. |
| "The reviewer found a one-line fix, it can just make it." | Then it is not a finder, and the next fat review dies mid-triage exactly the way the split was built to stop. |
| "The fixer should re-run the review to check nothing was missed." | That refills its window with specialist reports and puts it back in the failure mode the split removed. The manifest is the input. Reject an item in a line if it is wrong. |
| "Post each finding as its own inline comment so nothing is missed." | One consolidated comment, inline only for BLOCKER and HIGH. The fixer reads the LOCAL manifest; a round trip through GitHub to fetch back your own notes is not a review artefact. |
| "Every review needs its own fixer session." | One fixer, at the end, for the whole night. Seven fresh fixers once cost 103M tokens, a quarter of a sprint. |
| "It stalled - retry harder and poll faster." | Classify it first. A spending cap cannot be solved by a faster watchdog, and a ladder spent against one loses hours while reporting a permission problem. |
| "T05 died on an API error, I'll relaunch the ticket." | Resume it - `revive.sh` does. The conversation is on disk; a fresh session re-reads the codebase and repeats every decision the dead one made. |
| "I'll resume it by hand, it's one `claude --bg --resume`." | Resume mints a **new session id** and drops the name. By hand, `state/<tag>.session` points at a corpse while a real session runs unwatched. |
| "My phase is done - I'll launch the next conductor with `claude --bg` and stop." | Nothing watches it then. One died 2.5 minutes in and the night sat dead for six hours. Write `DONE` to your phase status; the phase runner launches and watches the next one. |
| "I'll just run the tests for this ticket before I commit." | Static checks only. The suite runs on the PR in CI, never locally; `FIX-FINAL` and `FIX-TEST` may run a few targeted files, and the CI watcher fixes what is red. |
| "I'll run the whole suite once at the end, to be safe." | That is CI's job, on the pushed commit. A local full run holds the sprint for an answer CI gives anyway, and the watcher already owns red tests. |
| "The checks are red but the ticket is basically done." | Green or `BLOCKED: <reason>`. There is no third state. |
| "Every stage said DONE, so the sprint is delivered." | `DONE` means a session finished. Acceptance is `ACCEPTANCE.verdict` and `GOLDEN.verdict`. 21 green stages once shipped a red PR. |
| "`VERIFY` passes, so CI will pass." | It did not, twice, on formatting read as a warning-only lint rule. Run `FORMAT_CHECK`; the CI watcher checks the pushed sha with `accept.sh`. |
| "I'll just wait for CI so the report can say green." | Nobody waits on CI. `ci-watch.sh` hands it to a watcher outside the chain; the report says `PENDING`, names the watcher, and ends. A session that polls checks is spending the night on a job that already has an owner. |
| "T05 relayed, so T05 is finished - launch T06." | `RELAYED` is not `DONE`. The ticket is still being built under `T05c2`. `advance.sh` knows; nothing else gets to decide. |
| "I'll launch the next tag myself off this DONE event." | `advance.sh` is the only transition owner. Two things deciding off two files is what once launched a fixer before its finder had decided there was anything to fix. |
| "I'm at `RELAY_AT_USED` but I'll see this event through first." | Relay now. A conductor that dies mid-night strands every session it was watching. |
| "30% used is barely anything, the session is fine." | The threshold is not a health check, it is a handoff point chosen so the handoff is GOOD. A session with 70% of its window left writes a successor prompt worth reading; one at 90% writes a shrug. |
| "A session is past its line and has not handed off - I'll do it for it." | You cannot. There is no way to message a running session, and the scripts that faked it forked sessions into duplicates. It is a log line, not a lever. |
| "The window is 1M, close enough to leave `CONTEXT_WINDOW` at the default." | Then every session relays after its first big read and the night goes on handoffs. It cannot be inferred from a transcript. |
| "`acceptEdits` is the safe default for an unattended run." | It is the mode that stalls: it still prompts on shell commands, and a background session cannot answer. Use `auto`. |
| "They named `bypassPermissions`; I'll ask them to accept the disclaimer." | Asking is off the table. If `T01` stalls on the disclaimer, switch to `auto`, relaunch, and log it. |
| "I'll write the prompts by hand, it's more precise." | 22 prompts and 29,266 words once came out of one kickoff, mostly retyped facts. `render.sh` fills them from `facts.env` and fails on an unfilled slot. You author the judgement only. |
| "I'll put the key's value in the PR body so it's easy to find." | Never. Not the PR, not `LOG.md`, not a prompt file. |

## Anti-Patterns

- **Bare `claude --bg`** during a sprint - bypasses the claim and can put two agents in one
  worktree. Always `launch.sh`, always `revive.sh`, always `advance.sh` for the chain,
  `schedule.sh` for the queue, and `ci-watch.sh` for the CI watcher (it runs in its own worktree,
  outside the chain).
- **Restarting a ticket that only needed a resume**, or retrying one that needed a human.
- **Emitting routine events to the conductor** - a `DONE` whose only possible answer is a
  scripted `launch.sh` call is a script's job. If you find yourself adding one, add it to
  `EVENTS.log` instead.
- **Prompts authored lazily** - writing the review or test prompt only when you get there.
  Nobody is awake to fix a broken prompt.
- **An unfilled slot** in a rendered prompt - a session that wakes at 3am not knowing what to
  build or how to check it. `render.sh` fails on these; do not work around it.
- **A silent night** - the report must name every ticket as landed, blocked, or abandoned.
- **Reviving a `BLOCKED` session** - it hit something real.
- **A continuation prompt that says "carry on from where I left off"** - the successor starts
  with an empty window and cannot read its predecessor's conversation.
- **Relaying a session that is one command from green** - finish the ticket.
- **A review session that both finds and fixes**, or a fixer that re-runs the review.
- **Reaching into a working session at all** - to nudge it, relay it, or correct its ticket.
  What a session needs to know belongs in its prompt, before it starts.
- **Busy-watching** - do not poll by hand in a loop; arm the runner and react to escalations.
- **A step with an invented click path** - an honest "I could not verify the exact path" costs
  the user ten seconds; a wrong path costs them ten minutes and their trust in every other step.
