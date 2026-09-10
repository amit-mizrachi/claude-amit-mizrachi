---
name: night-sprint
description: Delivers a whole feature overnight through autonomous sessions run strictly one after another - a conductor session that writes no code but launches each ticket, revives stuck or dead sessions, nudges a session that is filling up and relays it into a fresh one, and fires the reviews, plus at least one implementer session per ticket, all on ONE branch landing as ONE pull request. Gets or builds a ticket breakdown first (via to-spec and to-tickets), decides whether to review once at the end or at checkpoints, runs every review as a pair of sessions (one finds and posts inline PR comments, one implements them), optionally runs a test session that boots the stack or runs evals, and, only when the feature needs a secret pasted, infra applied or a dashboard visited, ends by building an interactive setup wizard for those steps, committed into the same PR - skipping that session entirely when nothing needs setting up. Use when the user says "night sprint", "sprint this feature", "build this overnight", "run this while I sleep", "ticket after ticket", or wants a feature taken end to end unattended in a single PR.
argument-hint: <feature | spec path | ticket dir | issue URL> [test: none|dev-stack|evals|<command>]
---

# Night Sprint

## Overview

One feature, delivered overnight by a **chain** of sessions: ticket 01 lands, hands off to
ticket 02, and so on. **Exactly one session touches code at a time**, all of them in **one
worktree on one branch**, so the sprint ends as **one PR** with no integration step at all.

You are the **conductor**. You never write a line of product code. You set the sprint up,
launch the first ticket, then watch: revive what dies, fire the reviews at the points you
chose, launch the optional test session and the closing wizard session, and write the morning
report.

The sprint ends with the PR - and, **when the feature needs one**, a **setup wizard** in it: an
interactive script that walks the user through the secrets, applies and dashboard clicks the
night could not do for them. A feature that is merged but unconfigured is not delivered. A
feature that needs no configuration is delivered by the PR alone, and the sprint says so in one
line rather than writing a script that does nothing.

**This is the sequential sibling of `orchestrating-parallel-delivery`.** That skill splits
work across concurrent sessions to save wall-clock. This one deliberately does not - it is
night time, nobody is waiting, and serial execution buys correctness: no frozen contracts, no
disjoint-file rules, no merge conflicts, no tracker. If you catch yourself fanning out
implementers, you are in the wrong skill.

## Kickoff (conductor, when the skill fires)

1. **Ask the two things you cannot infer - FIRST, before anything else.** One
   `AskUserQuestion`, before you read a ticket or run a verify command. Kickoff takes a while
   and the user drifts away during it; ask while they are still at the keyboard.
   - **Permission mode** for unattended sessions: **`auto` is the default and what you should
     use unless the user says otherwise.** Record it in `PERMISSION_MODE`.
   - **Test session?** If the invocation already said (`test: none|dev-stack|evals|<cmd>`),
     use it and do not ask. Otherwise ask: none · boot the stack locally via
     `shapes-dev-environment` and walk the golden path · run evals · a custom command.

   **Why `auto` and not the other two.** The valid modes are `acceptEdits`, `auto`,
   `bypassPermissions`, `manual`, `dontAsk` and `plan`, and only one of them suits an
   unattended night:

   - `acceptEdits` auto-accepts file edits but **still prompts on shell commands**, and a
     background session cannot answer a prompt - it sits in `blocked` until you revive it. In a
     sprint that runs `pnpm`, `git push`, `gh` and `wrangler` all night, that is a stall every
     few minutes.
   - `bypassPermissions` needs a **one-time interactive disclaimer that you cannot accept on
     the user's behalf**; `launch.sh` fails with exactly that message until it has been
     accepted. The `!` prefix will not do it either - that path runs `--print`, so there is no
     TTY for the disclaimer. It needs a real terminal, and by launch time the user is asleep.
   - `auto` needs no disclaimer and never stalls: a risky action is **denied by a classifier
     and the session keeps going**, adapting or routing around it, which is the behaviour you
     want from an agent nobody is watching. The cost is that an occasional legitimate action
     gets refused, and the session says so in its summary rather than hanging.

   If the user does want `bypassPermissions`, hand them the interactive `claude` skip-permissions
   command **at this step**, while they are still at the keyboard - never at launch time.
2. **Get the tickets.** The sprint needs a plan already cut into tickets in dependency order.
   - Tickets exist (a `.scratch/<slug>/issues/` dir, tracker issues, a plan with numbered
     slices)? Read them all.
   - No tickets? Run **`/to-spec`** on the feature, then **`/to-tickets`** on that spec, and
     take the user through their approval gates now, while they are still here. Never start a
     sprint against a plan the user has not seen.
   - Copy the final tickets into the workspace as `tickets/<NN>-<slug>.md` so the sprint has
     a frozen local copy even if the tracker changes overnight.
3. **Ground the run.** Repo absolute path, base branch (`origin/<default>`), toolchain/env
   setup, and the **one full verify command** every session must pass (e.g.
   `pnpm nx run-many -t typecheck test lint`). Confirm the verify command actually runs
   before you launch anything - a wrong one poisons every ticket in the chain.
   Pin the context facts here. **`CONTEXT_WINDOW`** - the sprint model's window in tokens,
   `200000` normally and `1000000` on a 1M model. It cannot be inferred later (a 1M model records
   the same name in the transcript as the 200k one), and getting it wrong makes every rung fire at
   the wrong moment. Then the three thresholds, **all of them percent USED**, counting up from a
   fresh 0 exactly as `/context` reports it: **`WARN_AT_USED`** (`20`) - nudge the session to
   start nothing new. **`RELAY_AT_USED`** (`30`) - hand its tag to a fresh session.
   **`CEILING_USED`** (`60`) - the point past which a relay fires even with nothing to hand over.
   Defaults unless the user says otherwise.
4. **Decide the review cadence yourself** (see Review cadence) and state the decision.
5. **Build the workspace and the branch** (see Coordination), including the shared worktree,
   `PLAN.md`, and **every** prompt file - ticket prompts, a FIND and a FIX prompt for each review
   checkpoint plus the final pair, test prompt, and the
   `WIZARD` prompt that closes the sprint. Write them all now: at 3am there is nobody to
   author a missing prompt. Write each tag's successor
   to `state/<TAG>.next` in the same pass (one tag per file, `T01.next` -> `T02`, the last one
   empty) - a relayed session reads it to learn what its continuation must launch.
6. **Launch ticket 01** with `launch.sh`, then arm the watcher and go into the monitor loop.

## Roles

| Role | Count | Writes code | Job |
|---|---|---|---|
| **Conductor** (you) | 1 at a time, relayed as the night runs on | never | set up, launch, watch, revive, nudge, relay, fire reviews, report |
| **Implementer** | 1+ per ticket, **serial** | yes | build ONE ticket green, commit, hand off to the next - or relay the ticket on when its window fills |
| **Review finder** | 1+ per checkpoint + 1+ final | **never** | `quad-review-squad` over the diff, triage, post findings as inline PR comments |
| **Review fixer** | 1 per finder | yes (fixes only) | `address-review`: implement or reject each finding and bot comment, verify, push |
| **Tester** | 0 or 1 | no | exercise the built thing, report PASS/FAIL per step |
| **Wizard author** | **0 or 1**, last | yes (one script) | runs only when the sprint left real setup behind: collect every manual step, author the wizard, land it in the same PR |

## Coordination

| Thing | Convention |
|---|---|
| Workspace | `~/.claude/night-sprint/<slug>/` - `PLAN.md`, `tickets/`, `prompt-<TAG>.txt`, `state/`, `LOG.md` |
| Pinned facts | one value per file: `WORKTREE`, `SLUG`, `PERMISSION_MODE`, `BRANCH`, `VERIFY`, `CONTEXT_WINDOW`, `WARN_AT_USED`, `RELAY_AT_USED`, `CEILING_USED` |
| Tags | `T01`..`TNN`, then a PAIR per review - `REVIEW-C1` + `FIX-C1` .. `REVIEW-CN` + `FIX-CN`, `REVIEW-FINAL` + `FIX-FINAL` - then `TEST`, `WIZARD`, plus continuations `<TAG>c2`, `<TAG>c3` |
| Successors | `state/<TAG>.next` holds the tag that follows it, written at setup, read by a relay |
| Branch | ONE: `<type>/<slug>` off `origin/<default>` |
| Worktree | ONE, shared by every session: `.claude/worktrees/<slug>` |
| Launching | **always** `bash <WS>/launch.sh <WS> <TAG>` - never a bare `claude --bg` |
| Reviving | **always** `bash <WS>/revive.sh <WS> <TAG> <cause>` - never re-launch a dead tag by hand |
| Nudging | **always** `bash <WS>/remind.sh <WS> <TAG> <used>` - one per tag, ever |
| Relaying | **always** `bash <WS>/relay.sh <WS> <TAG> <used>` - never tell a filling session to hand off by hand |
| Context | `bash <WS>/context-used.sh <SESSION_ID\|--self> <CONTEXT_WINDOW>` - percent of window USED, counting up |
| Follow-ups | any session appends one line to `state/FOLLOWUPS.md` for real work that is out of scope - the morning report turns them into tickets |
| Status | each session writes `state/<TAG>.status` = `DONE`, `BLOCKED: <reason>` or `RELAYED: <TAG>c2` as its last act |
| Summary | each session also writes `state/<TAG>.summary` - ONE line, what it actually did, for the ledger |
| Manual steps | any session appends to `state/<TAG>.manual` the moment it hits something only a human can do - the `WIZARD` session turns the lot into one script |
| Setup verdict | `state/SETUP.verdict` = `NEEDED` or `NONE`, written by the last session before the wizard gate - it decides whether `WIZARD` runs at all |
| Signal | each session's final commit body also carries `SIGNAL: <TAG>-DONE` / `-BLOCKED: <reason>` |
| Watching | `bash <WS>/watch.sh <WS>` under the `Monitor` tool, `persistent: true` |

## The templates - read these before writing anything

| File | Use |
|---|---|
| `references/plan-template.md` | the `PLAN.md` skeleton: facts, goal, ticket order, golden path, protocol |
| `references/implementer-prompt.md` | one ticket, one session - fill one per ticket |
| `references/review-find-prompt.md` | the review FINDER - quad squad, triage, inline PR comments, no code |
| `references/review-fix-prompt.md` | the review FIXER - address-review over what the finder posted |
| `references/test-prompt.md` | the opt-in tester - pick ONE of its three modes and delete the rest |
| `references/wizard-prompt.md` | the closing `WIZARD` session - collects the manual steps and authors the setup script |
| `references/continuation-prompt.md` | a relayed ticket's successor - the sessions fill this one themselves |
| `references/launch.sh` | atomic claim + launch + session-id capture + the branch tip at start |
| `references/watch.sh` | the watcher: emits DONE / BLOCKED / RELAYED / WARN / FAT / STUCK / DIED / STALLED events |
| `references/revive.sh` | the reviver: resume the dead conversation, then restart, then abandon |
| `references/remind.sh` | the nudge: tell a filling session to start nothing new, and let it carry on |
| `references/relay.sh` | the relay: tell a session at the handoff line to consolidate and hand off |
| `references/context-used.sh` | the gauge: percent of a session's context window already USED |

Copy all six scripts and `continuation-prompt.md` into the workspace at setup (`cp` + `chmod +x`)
and use those copies, so editing the skill never changes a sprint already running. Fill every
`<PLACEHOLDER>` in the prompts - an unfilled placeholder is a session that wakes up at 3am not
knowing what to build. `continuation-prompt.md` is the one exception: it stays a template, and
each relaying session fills its own copy for its successor.

`launch.sh` claims a tag with an atomic `mkdir` before starting it. The previous ticket's
session and you will sometimes both reach for the next ticket at the same moment; the claim
means one of you wins and the other is a no-op. **That claim is the only thing keeping two
agents out of one worktree - never bypass it.**

## Review cadence (you decide, then say so)

- **4 tickets or fewer, one subsystem** -> `REVIEW-FINAL` only.
- **5+ tickets, or the sprint crosses subsystems** (server + client, or a schema change) ->
  a checkpoint review at each natural seam, roughly every 3-4 tickets, plus the final one.
  Put a checkpoint right after the ticket that lands a schema or interface everything else
  builds on - that is the mistake that gets expensive when it is found at ticket 11.
- **Always at least one**: a sprint never ends without `REVIEW-FINAL`.
- A review is a **session in the chain, not a parallel job** - it holds the worktree, so the
  next ticket does not launch until the review pair reports its status.

**Every review is TWO sessions, never one.** `REVIEW-C1` finds; `FIX-C1` fixes.

| | `REVIEW-<N>` (finder) | `FIX-<N>` (fixer) |
|---|---|---|
| Runs | `quad-review-squad` over the accumulated diff | `address-review` over the PR's comment threads |
| Writes code | **never** - not one file, not the verify command, no commit | yes, fixes only |
| Output | findings triaged and posted as **inline PR comments**, plus `state/<TAG>.findings.md` | fixes committed and pushed, every thread replied to |
| Then | launches its fixer | launches the next ticket |

**Why the split, and why it is not optional.** Consolidating five specialist reports is the most
expensive single act in a night sprint: it pulls five reviews plus the whole diff into one
window. A session that did that and then fixed code spent its window twice over, and the reviews
were the sessions that hit the handoff line most often - mid-triage, which loses the triage
itself, the most valuable thing the session had produced. Splitting turns the expensive read into
a durable artefact on the PR. The findings then cost the fixer almost nothing to load, and the
fixer starts with a clean window for the only part that needs one.

The corollary is a rule the fixer's prompt states outright: **the fixer never re-runs the squad.**
Not to double-check, not on "just the files I touched". That is the one move that undoes the split.

If the finder posts nothing AND the PR has no open bot or CI comments, it skips the fixer - it
writes `SKIPPED: nothing to address` to `state/<FIX_TAG>.status` and launches what the fixer
would have launched.

## Monitor loop

Arm one persistent `Monitor` on `watch.sh` and react to each event. Keep every reaction
short - you have to survive until morning, so log to `LOG.md` and keep your context lean.

| Event | Do |
|---|---|
| `DONE <TNN>` | If the next tag is unclaimed, `launch.sh` it (the implementer normally already did - the claim makes a double call harmless). At a checkpoint boundary, launch the review FINDER instead. After `T01`, open the **draft** PR. |
| `DONE REVIEW-<N>` | The finder posted its findings; it does not fix them. Launch `FIX-<N>` if unclaimed. Never read the findings into your own context - they are on the PR, and the fixer is the one who needs them. |
| `DONE FIX-FINAL` | Launch `TEST` if the user opted in. Otherwise apply **the wizard gate** below. |
| `DONE TEST` | Apply **the wizard gate** below. |
| **the wizard gate** | Read `state/SETUP.verdict`. `NEEDED` -> launch `WIZARD`. `NONE`, or no verdict file and no `state/*.manual` block that passes the counts-as test -> **do not launch it**: write `SKIPPED: no manual setup` to `state/WIZARD.status`, a one-line reason to `state/WIZARD.summary`, and go straight to the morning report. |
| `DONE WIZARD` | Read `HANDOFF.md`, then write the morning report. This is the end of the sprint. |
| `WARN <TAG> used-<N>pct` | Rung one. `remind.sh <WS> <TAG> <N>` - it tells the session to start nothing new and lets it carry on. Do **not** relay it and do **not** treat this as a problem. Fires once per tag. |
| `FAT <TAG> used-<N>pct` | Rung two, the handoff line. `relay.sh <WS> <TAG> <N>` - it consolidates and hands the tag to `<TAG>c2`. See Context. |
| `RELAYED <TAG> <CONT>` | The ticket is **still in flight**, not finished. If `<CONT>` is unclaimed, `launch.sh` it. Log the ledger row. Do **not** advance to the next ticket, and do not fire a review. |
| `DIED <TAG> api-error` | The API dropped it, the conversation is intact. `revive.sh <WS> <TAG> api-error` - **resume, do not restart**. This is the common one; see Reviving. |
| `DIED <TAG> ended-without-signal` | `revive.sh <WS> <TAG> ended-without-signal`. It resumes first too; if that rung is spent it restarts with a RESUME note naming what already landed. |
| `STUCK <TAG> permission-prompt` | `revive.sh <WS> <TAG> permission-prompt`. If already on the permissive mode it is a *question*, not a permission - the continue prompt tells it to decide for itself and proceed. |
| `STALLED <TAG> api-error` | Same as `DIED ... api-error` - it hit the error and never came back. Resume it. |
| `STALLED <TAG> idle-<N>m` | Check `claude logs <id>` first. Genuinely idle -> `revive.sh <WS> <TAG> idle`. Mid-build or mid-install -> leave it, allow one more stall window, then treat as DIED. |
| `BLOCKED <TAG> <reason>` | Do **not** revive - it reported a real blocker. Record it, skip every ticket that lists it as a blocker, continue with the rest. |
| `SWEEP <n>` | Heartbeat, roughly every 10 polls. Nothing to do. |
| `SWEEP 0 ... all-sessions-terminal` | The watcher has **exited** - nothing is running. If tags remain, launch the next one and **re-arm the watcher**; if the sprint is complete, write the morning report. Never leave the sprint with no armed watcher and work outstanding. |

**The conductor holds itself to the same two rungs.** The sprint outlives any one conductor, and
you are the session with the longest life and the most events to absorb, so you are the one whose
death costs the most. Measure yourself; do not estimate:

    bash <WS>/context-used.sh --self <CONTEXT_WINDOW>

Run it **at every watcher event**, not on a hunch - the events are the only clock you have, and a
single fat review summary can take you from comfortable to past the line in one step.

At **`WARN_AT_USED`% used (20 by default)**, apply your own nudge: stop doing anything beyond
watching. No reading the PR diff "to understand a finding", no opening a ticket file out of
curiosity, no investigating a failure an implementer already owns. Log the event, take the
scripted action, move on.

At **`RELAY_AT_USED`% used (30 by default), relay yourself** - do not wait, and do not try to see
one more ticket through:

1. Flush the live state to `LOG.md` (see Session ledger) so nothing lives only in your head:
   every ledger row, which tags are open and under which session ids, what you were about to do.
2. `/next-prompt` a fresh conductor whose prompt points at the workspace and says: read
   `PLAN.md` + `LOG.md` + `state/`, re-arm the watcher on `watch.sh`, resume the monitor loop,
   and hold itself to the same two rungs, measured the same way.
3. Record the relay in `LOG.md` as its own ledger row, then stop. Do **not** stop the watcher's
   implementer sessions - they keep running and the new conductor adopts them.

`PLAN.md` + `LOG.md` + `state/` are written precisely so a cold conductor can pick the sprint
up without your context. Relay as many times as the night needs.

## Context - two rungs, and a ticket may take more than one session

A context window is smaller than some tickets. A session that pushes on until it is full does
not stop cleanly: it thrashes, compacts away the reasoning that mattered, and at worst dies
mid-edit having written none of it down. Everything it worked out - why that approach failed,
which file is next, what the failing check actually says - is worth more than the tokens it
would take to limp to the end of the ticket.

So the sprint hands off **early**, while the session still has most of its window to explain
itself. `T03` becomes `T03 -> T03c2 -> T03c3`: **one ticket, several sessions, still strictly one
at a time.** This is not a failure mode and it is not the reviver - nothing died and nothing is
wrong. It is the normal way a ticket gets built, and a sprint would rather run three fresh
sessions on a ticket than one exhausted one.

**The gauge counts UP.** `bash <WS>/context-used.sh <SESSION_ID|--self> <CONTEXT_WINDOW>` prints
percent USED: 0 is a fresh session, 100 is a full one, exactly as `/context` reports it. Every
threshold in the sprint is expressed the same way, so they are small numbers that grow.

| Rung | Reading | The session does | You do, on the event |
|---|---|---|---|
| **Nudge** | `WARN_AT_USED`, 20 by default | Starts nothing new: no new subsystem, no refactor past the ticket, no fresh fan-out, no wide reading. Drives what it is on to a committed state | `remind.sh <WS> <TAG> <N>` |
| **Handoff** | `RELAY_AT_USED`, 30 by default | Consolidates, writes a filled continuation prompt, hands the tag on | `relay.sh <WS> <TAG> <N>` |

**Why a nudge rung exists at all.** The expensive mistake is not running out of window, it is
running out *halfway through something*. A session that opens a new front at 22% used arrives at
the handoff line holding work nobody can pick up, and the successor inherits a half-finished
thing plus a description of it. Told at 20% to start nothing new, that same session arrives at
30% holding a completed unit, and the handoff is a paragraph instead of an archaeology report.
The nudge does not end anything and it is not a warning that something is wrong - `remind.sh`
resumes the session with one short instruction and it carries straight on.

**Two things watch the same number**, and either can act:

- **The session itself.** Every prompt tells it to measure after any large read, long build, or
  subagent fan-out, and gives it both rungs.
- **You.** `watch.sh` gauges every open tag each poll and emits `WARN` then `FAT`. Each fires
  once per tag, guarded by `state/<TAG>.warned` and `state/<TAG>.relayed`, which is why a jump
  straight past both rungs in one poll produces only the `FAT`.

**The relay has a floor, and the floor is in the watcher.** A relay is worth doing only once the
session has something to hand over. At 30% used the handoff line sits close to a session's
startup cost - `PLAN.md`, the ticket, `LOG.md`, `git log`, the two or three files whose pattern
it must mirror - especially on a 200k window. Relayed at that point, a session hands its successor
nothing but a list of files it read, and the successor reads them again. Do that twice and the
ticket never gets built. So `watch.sh` holds `FAT` back until the worktree shows a commit that
was not there when the tag launched (recorded by `launch.sh` in `state/<TAG>.headsha`) or an
uncommitted change - and releases it regardless past `CEILING_USED` (60), because a session that
full with nothing to show means the ticket is bigger than the plan thought, which is itself
something the morning report should say.

Either way the session does the same five things: commit and push what it has (WIP with
`SIGNAL: <TAG>-RELAYED` in the body if it is not green - never stash, never revert), fill
`continuation-prompt.md` into `prompt-<TAG>c2.txt`, write `state/<TAG>.summary`, write
`state/<TAG>.status` = `RELAYED: <TAG>c2`, then `launch.sh <TAG>c2`.

**`RELAYED` is not `DONE`.** `DONE` releases the next ticket; the relayed ticket is still being
built. Treat `RELAYED <TAG> <CONT>` as "this tag's work continues under `<CONT>`" and nothing
more - do not launch the next ticket and do not fire a review until the continuation reports
`DONE`.

Two more things keep this from firing wrongly, and both are worth knowing:

- **`CONTEXT_WINDOW` must be right.** The gauge divides by it, and a transcript records the
  same model name for a 200k model and its 1M variant - it cannot be inferred. Pin it at
  kickoff. Set it to 200000 on a 1M run and every session relays after its first big read.
- **A session one command from green finishes instead of relaying.** Both the prompt and
  `relay.sh` say so up front. A split that saves nothing costs the sprint a whole session of
  re-reading.

**The gauge was renamed on purpose.** It used to be `context-left.sh` and counted DOWN - percent
still free - so these same two rungs read 80 and 70. That polarity is easy to get backwards and
expensive when you do: a sprint configured the wrong way round either relays every session at
birth or never relays one at all. Nothing in the sprint speaks "free" any more, and a stale
caller reaching for `context-left.sh` now fails loudly instead of silently inverting.

If `relay.sh` cannot restart the conversation it says so and gives up **without** marking the
tag. That is deliberate: a fat session is not a broken one, the harness will auto-compact it,
and letting it run on beats abandoning work. Log the failed relay and carry on.

## Reviving - resume the conversation before you restart the ticket

Most night-time deaths are not the session's fault. The API drops the call mid-response, stalls
mid-stream, or returns 529 or 500, and the process is simply gone. **The conversation survives
on disk** - everything it read, every decision it made, the edit it was halfway through. A
resume costs one prompt and picks up mid-thought. Restarting the ticket from the top throws all
of that away and re-does hours of reading. Resume is not a fallback, it is the first move.

**Always `bash <WS>/revive.sh <WS> <TAG> <cause>`.** Never re-launch a dead tag by hand. The
script walks a ladder, cheapest rung first, and prints which rung it took:

| Rung | What it does | Budget per tag |
|---|---|---|
| `resume` | `claude --bg --resume` on the same conversation, told to carry on and **not** start over | 2 for `api-error`, 1 otherwise |
| `restart` | fresh session on the original ticket prompt, plus a RESUME block telling it which commits already landed so it does not redo them | 1 |
| `abandon` | writes `BLOCKED: ABANDONED ...` so the watcher reports it and the sprint moves on | - |

`<cause>` is the watcher's second field - `api-error`, `ended-without-signal`, `idle`,
`permission-prompt`. It sets the resume budget and the wording of the continue prompt, nothing
else. An API error gets two resumes because it is transient infrastructure and the work in that
conversation is worth a second go.

**Two things make hand-reviving wrong**, and are exactly why the script exists:

- A resumed session gets a **new session id** and does **not** inherit its display name. The
  watcher tracks the id in `state/<TAG>.session`, so a stale id there is a live session nobody
  is watching - the sprint goes quiet until morning.
- The watcher emits each `(tag, verdict)` **once**. Without clearing that tag's rows from its
  seen-file, a revived session that dies again is never reported at all.

When the ladder runs out, the tag is ABANDONED: record it in `LOG.md`, skip its dependents,
carry on with the rest of the sprint. A sprint that delivers 7 of 9 tickets and says so plainly
beats one that loops on ticket 3 all night. Log **every rung** as its own ledger row - a ticket
that took three sessions to land is something the user needs to see in the morning.

## The manual steps, and the wizard that closes the sprint

A night sprint can land every ticket green and still leave the user with nothing they can run.
The code is merged; the API key is not pasted, the terraform unit is not applied, the OAuth app
is not registered, the flag is off. Those steps are not the sprint's failure - they are a
human's by definition, and an unattended agent should not be doing them at 4am anyway. But a
sprint that ends without naming them ships a feature nobody can turn on.

So when a sprint leaves any of that behind, its last session is `WIZARD`, and it builds the
thing that turns the feature on: **one interactive bash script, committed into the same PR**,
that walks the user through each manual step in order, opens each URL, says what to click,
captures what they copy back, writes it where it belongs, and confirms before anything
irreversible.

**And it contains nothing else.** Every stage is an action the user performs - a value pasted, a
command run, a thing clicked. No preflight or tool-check stages, no stage that reads live state
and prints it, no stage that verifies the result afterwards. All of that is work an agent can do,
and the `WIZARD` session does it at authoring time: it reads what is already configured and
simply writes no stage for it. A three-stage wizard that applies a unit, sets a secret and runs a
migration is the target shape; the nine-stage version that also checks `gh` is logged in and
prints a summary at the end is nine screens of the user's morning spent on an agent's chores.
Re-runnability comes free from the library, not from a status stage: `ask` and `ask_secret` offer
the existing value and keep it on Enter, and `write_env` upserts.

**When a sprint leaves none of it behind, that session does not run.** Plenty of features are
pure code on infrastructure that already exists, and for those the PR is the whole delivery. The
two sections below are the difference: what actually counts, and how the sprint skips.

**Where it sits in the chain.** `REVIEW-FINAL` -> `FIX-FINAL` -> `TEST` (if the user opted in) ->
`WIZARD` -> morning report. It goes **after** the tester deliberately: the tester is the session
most likely to discover a missing secret, because it is the only one that tries to run the thing,
and "the stack would not boot without `X`" is exactly a wizard stage.

**Collect as you go, not at the end.** Every session is told to append a block to
`state/<TAG>.manual` the moment it hits something it cannot do:

    STEP:     <one line: what a human must do>
    WHY:      <what breaks without it - the concrete failure, not "for configuration">
    WHERE:    <the URL, dashboard path or command, as concretely as it is known>
    VALUE:    <ENV_VAR_NAME, or "none" for a pure action>
    LANDS:    <.env | github secret | terraform var | a service | nowhere>
    SECRET:   <yes|no>
    BLOCKING: <yes = the feature does not work at all without it | no>

Those seven fields are exactly what the `wizard` skill needs to author a stage, which is why
they are the fields. **The reason it is per-session and not reconstructed at the end**: the diff
shows a new `process.env.FOO`, but it does not show that FOO's key lives behind a dashboard
toggle that T04 spent an hour finding at 02:00. That knowledge exists in one session's window
and nowhere else, and it is gone the moment that session ends.

**But the `WIZARD` session never trusts the `.manual` files alone.** Sessions forget, and a step
nobody recorded is a step the user meets at 09:00 when the feature does not work. It sweeps the
whole branch diff itself for new env reads, new `secrets.*` references in workflows, new infra
units, new migrations, new third-party integrations - and then checks what is **already** set
before writing a stage for it. Reading live state rather than a document is also what makes the
script re-runnable, which matters because the user will hit a gate, go and merge something, and
come back to it.

### What actually counts as a manual step - both tests, every time

**TEST 1 - REQUIRED. The shipped feature does not work until this happens.** Not "would be
convenient": the feature is broken or unreachable in a real environment until it is done.

**TEST 2 - HUMAN-ONLY. No agent could have done it.** It needs a credential no agent holds, a
console or dashboard no agent can reach, a human approval, or it is a production mutation that
policy puts on a person.

A block needs **both**. The two failure columns are different problems with different fixes:

| Passes both - a stage | Fails test 1 - a report line | Fails test 2 - an agent's job |
|---|---|---|
| A secret, credential or token to paste or rotate | A `.env.local` a developer fills to run the app on their own laptop | Adding a var to `.env.example` |
| A deploy, a provision, a terraform / terragrunt apply | Config drift that predates the branch and that the branch did not make matter | Writing or fixing a migration file |
| A migration to run against a real database | A judgement call the user may want to reverse | Wiring a config key the code should read itself |
| A third-party app or OAuth client to register | Anything already set - check live state first | Updating a README or a runbook |
| A dashboard or console setting, DNS record, access rule or feature flag to flip | Merging the PR and deploying - always the user's, always named in the report, never a stage | Adding the workflow step that runs the migration |
| A resource that must exist and no code creates it - bucket, queue, namespace, index | A follow-up improvement, however good | Any code change at all |

Test 1's failures are how sprints end up with a **ceremonial** wizard: a session finds something a
human *could* do, writes a block, and the last session dutifully turns it into a script. A pure
front-end refactor of an already-deployed app needs nothing, and saying so in one line is the
correct deliverable.

Test 2's failures are worse, because they look useful. **A stage asking the user to do something
an agent could have done reads as a requirement when it is really a chore that got handed over.**
The session that finds one either does it - it has a worktree, a branch and permissions - or
writes one line to `state/FOLLOWUPS.md` for the morning report to turn into a ticket. Ten seconds
of the user's reading, instead of a morning of their doing.

### The wizard is skipped when there is nothing to set up

`WIZARD` is the only session in the chain that may not run at all. `REVIEW-FINAL` applies both
tests above to every `state/*.manual` block and writes the verdict to `state/SETUP.verdict`, one
word. If a `TEST` session runs, it settles the verdict last, because it is the only session that
tries to run the thing:

    NEEDED      at least one block passes BOTH tests
    NONE        none do

`NEEDED` launches `WIZARD` as normal. `NONE` **skips the session entirely** - no script, no
handoff document, no commit. The conductor writes `SKIPPED: no manual setup` to
`state/WIZARD.status` with a one-line reason in `state/WIZARD.summary`, and goes straight to the
morning report, which states "nothing to set up" as a **finding** and names what was swept to
reach it. An empty ceremonial wizard is one more thing to read at 07:00 to find out it does
nothing, and a session spent writing one is a session spent for nothing.

`REVIEW-FINAL` still sweeps the diff either way - it has the whole diff loaded for the review
already, so the sweep is nearly free there and it is what makes a `NONE` verdict trustworthy
rather than merely unrecorded.

**What the wizard will not do.** Permissions and access-control changes are described, never
executed - charter #9 puts those on a human reviewing a diff. Everything else may be a
confirmed, mutating step, because the user is awake and driving the script: a `confirm` that
prints the command first is them doing it, not an agent doing it unattended. And no real secret
value is ever written into the script, a prompt file, `LOG.md`, or the PR body.

`references/wizard-prompt.md` carries the whole procedure. It builds on the `wizard` skill and
its `template.sh`, whose library above the STAGES marker is never hand-edited.

## Session ledger and the morning report

The user wakes up to one message and needs to reconstruct a night they slept through, so the
report is **an account of who did what**, not just a status.

Keep a running ledger table in `LOG.md` and append a row the moment a session reaches a
terminal state - never reconstruct it at the end from memory. One row per session **including
every revived attempt, every context relay, and every conductor relay**, built from
`state/<TAG>.session`, `.status`, and `.summary`:

| Tag | Session id | Name | Role | Verdict | What it did |
|---|---|---|---|---|---|
| T01 | `a1b2c3d4` | ns-<slug>-T01 | implementer | DONE | one line from `.summary` |
| T03 | `e5f6...` | ns-<slug>-T03 | implementer | DIED api-error | how far it got before the API dropped it |
| T03 | `9a8b...` | ns-<slug>-T03-r2 | implementer (resumed) | DONE | what it finished after the resume |
| T05 | `c3d4...` | ns-<slug>-T05 | implementer | RELAYED to T05c2 at 31% used | what it landed before it handed on |
| T05c2 | `7e8f...` | ns-<slug>-T05c2 | implementer (continued) | DONE | what it finished on the fresh window |
| REVIEW-C1 | `...` | ns-<slug>-REVIEW-C1 | review finder | DONE | n findings posted, n deferred, n rejected |
| FIX-C1 | `...` | ns-<slug>-FIX-C1 | review fixer | DONE | n fixed, n skipped and why |
| FIX-C2 | - | - | not launched | SKIPPED | nothing to address - no findings, no open PR comments |
| WIZARD | `...` | ns-<slug>-WIZARD | wizard author | DONE | what the setup wizard configures, in one line |
| WIZARD | - | - | not launched | SKIPPED | no manual setup - what was swept, and why nothing came up |

A ticket that took three sessions and two relays is exactly what the user wants to see. Read it
carefully, though: **relays are now the normal shape, not a signal.** A ticket that relayed twice
is ordinary; a ticket whose relays came from `CEILING_USED` - a session that burned 60% of a
window without producing anything - is the one that says the breakdown was wrong. Say which kind
each was, because that distinction is the whole diagnostic value of the column.

The final message must contain, in this order:

1. **The verdict in one line** - what the user actually has this morning.
2. **The PR** - URL, draft or ready, CI state.
3. **Ticket outcomes** - every ticket as landed / blocked / abandoned, with the reason for
   anything that is not landed. Never omit a dropped ticket.
4. **The session ledger** - the full table above. This is the part the user asked for: how
   many sessions the sprint burned and what each one contributed.
5. **Review + test results** - findings addressed vs deferred; the tester's per-step PASS/FAIL.
6. **Follow-ups** - `state/FOLLOWUPS.md`, verbatim, as a list ready to become tickets. This is
   where everything real-but-out-of-scope landed, including anything a session decided was an
   agent's job rather than a wizard stage. An empty file is a fine answer; say so.
7. **What needs a human** - the decisions and blockers waiting on them.
8. **Turn it on** - the setup wizard, straight from `HANDOFF.md`. This is the part the user
   acts on first, so it is the part that must need no thinking.

   **If `state/WIZARD.status` reads `SKIPPED`, there is no `HANDOFF.md` and this whole item is
   one line**: "Nothing to set up", plus what was swept to reach that (the `.manual` records, the
   branch diff for env reads and workflow secrets and infra units and migrations, and the live
   `gh secret list` / `.env.example` check). Then name the two things that are still the user's
   and are never wizard stages: **merge the PR, and deploy**. State it positively - "no setup
   needed" is a finding the user acted on, not a section you left empty. Skip the sub-points
   below; they describe a script that does not exist.
   - **The command**, paste-ready into a **fresh** terminal: an absolute `cd`, the toolchain
     line, then the script. One self-contained paste with nothing left to work out - not a
     relative path, not "from the repo root", not "after sourcing nvm".
   - **Every value it will ask for**, as a table: `Value | Where to get it | Secret? | Where it
     lands`. "Where to get it" is the path a human walks - "Monday -> Developer centre -> your
     app -> OAuth -> client secret" - or the exact read command if it comes out of a secret
     store. A row that just names a hostname sends the user hunting, which is the whole thing
     the wizard existed to stop.
   - **The gates**: where the script stops and waits on something the user must merge, deploy
     or approve first.
   - **What the wizard will not do**, and who owns each of those.
   - **How to know it worked** - the check that proves the feature is live afterwards.

   If the sprint needed no setup at all, say that in one line here rather than dropping the
   section. Silence reads as an omission.

## The PR

Open **one draft PR** as soon as `T01` lands - not at the end. Early CI and early bot review
give the checkpoint reviewers something real to address. Every later session pushes to the
same branch, so the PR grows all night. `FIX-FINAL` flips it out of draft once its fixes are
green - the finder never does, because its findings are the reason the PR is not ready yet; the `WIZARD`
session's setup script is one more commit on that same branch and lands in that same PR, with
a **Setup** section added to the description. Never a second PR for the wizard.

**Never merge and never deploy** - those are the user's, always. If a required check
(e.g. a Monday-item check) has no ticket to point at, open the PR anyway and report the red
check. Never fabricate a ticket id and never bypass hooks with `--no-verify`.

## Red Flags - STOP

| Rationalization | Reality |
|---|---|
| "Tickets 3 and 4 are independent, I'll run both." | No. Serial is the contract - it is what removes conflicts and integration. Concurrency is `orchestrating-parallel-delivery`. |
| "I'll just implement this small ticket myself." | The conductor writes no product code. Your context is the scarcest resource of the night; spend it watching. |
| "No plan yet, I'll figure out tickets as I go." | Run `/to-spec` + `/to-tickets` and get approval first. An unapproved sprint builds the wrong thing 9 times. |
| "T05 died on an API error, I'll relaunch the ticket." | Resume it first - `revive.sh` does. The conversation is still on disk; a fresh session re-reads the codebase from scratch and repeats every decision the dead one already made. |
| "Ticket 5 is stuck; I'll keep retrying until it works." | The ladder is the limit: resume, restart, ABANDONED. Then move on and report the gap. |
| "I'll resume it by hand, it's one `claude --bg --resume`." | Resume mints a **new session id** and drops the name. Do it by hand and `state/<TAG>.session` points at a corpse while a real session runs unwatched - the sprint goes silent and nobody notices until morning. |
| "Each ticket can open its own PR." | One branch, one PR. That is the deliverable. |
| "The tests are red but the ticket is basically done." | Green or `BLOCKED: <reason>`. There is no third state. |
| "I'll review everything at the end, it's simpler." | For 5+ tickets a late review means unwinding a night of work. Checkpoint at the seams. |
| "It says DONE, so it works." | `DONE` means the session claims green. The tester and the final review are what earn it (charter #10). |
| "I'm at `RELAY_AT_USED` but I'll see this event through first." | Relay now, no exceptions. Measure with `context-used.sh --self`, do not estimate. A conductor that dies mid-night strands every session it was watching. |
| "30% used is barely anything, the session is fine - I'll let it run." | The threshold is not a health check, it is a handoff point chosen so the handoff is GOOD. A session with 70% of its window left writes a successor prompt worth reading; one at 90% writes a shrug. Relay it. |
| "The reviewer found a one-line fix, it can just make it." | Then it is not a finder any more, and the next fat review dies mid-triage exactly the way this split was built to stop. The finder posts; `FIX-<N>` fixes. No exceptions for small ones. |
| "The fixer should re-run the squad to check nothing was missed." | That refills its window with five specialist reports and puts it back in the failure mode the split removed. The findings on the PR are the input. Reject one in a line if it is wrong. |
| "I'll read the findings myself so I can summarise them in the report." | You are the conductor with the longest life in the sprint. The findings are on the PR and in `state/<TAG>.findings.md`; the fixer's one-line `.summary` is what the ledger needs. Reading five reports into your window is how a conductor relays at ticket 4. |
| "`WARN` fired - I should relay that session." | No. `WARN` is a nudge, `FAT` is the handoff. `remind.sh` tells it to start nothing new and it carries on working. Relaying on the first rung throws away a session that was doing fine. |
| "The session crossed 30% but has not committed anything - relay it anyway." | Its successor would start exactly where it did, minus the reading. The watcher holds `FAT` back for precisely this, up to `CEILING_USED`. Do not hand-relay around the floor. |
| "T05 is nearly out of context but it's almost done - let it push through." | Almost done is a guess; the gauge is a number. Unless it is one command from green, `relay.sh` it. A session that runs out mid-edit takes everything it learned with it. |
| "T05 relayed, so T05 is finished - launch T06." | `RELAYED` is not `DONE`. The ticket is still being built under `T05c2`. Launching T06 puts two agents in one worktree on top of half a ticket. |
| "The relay failed, so the ticket is dead - abandon it." | A fat session is not a broken one. `relay.sh` deliberately leaves the tag unmarked on failure; the harness auto-compacts and the session carries on. Log it and move on. |
| "The window is 1M, close enough to leave `CONTEXT_WINDOW` at the default." | Then every session relays after its first big read and the sprint burns the night on handoffs. Pin it at kickoff; it cannot be inferred from a transcript. |
| "`acceptEdits` is the safe default for an unattended run." | It is the mode that stalls. It still prompts on shell commands, and a background session cannot answer a prompt - it sits in `blocked` until you revive it. Use `auto`. |
| "They picked `bypassPermissions`; I'll sort the disclaimer out when I launch." | By then they are asleep. `--bg` refuses until the one-time disclaimer is accepted in a real terminal, and neither you nor the `!` prefix can accept it for them. Ask at step 1, while they are still at the keyboard. |
| "I'll write the session ledger at the end from the log." | Append each row as it happens. Sessions you revived or relayed away are exactly the ones you will forget. |
| "Every ticket is green, so the sprint is delivered." | Green code the user cannot turn on is not delivered. If a key must be pasted or a unit applied, `WIZARD` is the session that makes that runnable, and it is part of the sprint, not a follow-up. |
| "The `WIZARD` session can work the manual steps out from the diff at the end." | The diff shows a new `process.env.FOO`. It does not show that FOO's key is behind a dashboard toggle T04 spent an hour finding at 02:00. That lives in one session's window and dies with it - `state/<TAG>.manual`, written as it happens. |
| "T04 needs an API key, I'll just mention it in my summary." | A summary line is one row in a ledger nobody can act on. Write the `.manual` block with all seven fields; that is what becomes a wizard stage. |
| "Nothing manual came up, but I'll write a wizard for completeness." | Then the user reads a script at 07:00 to learn it does nothing. Say "no setup needed" in one line and write no file. Better still, the gate skips the whole session. |
| "The tester could not run it locally without filling in `.env.local`, so that is a wizard stage." | Only if the SHIPPED feature needs it. A laptop that cannot boot the app is a local-dev gap, and one that usually predates the branch - check whether it is on the base ref before you call it this sprint's. Put it in the morning report, not in a script. |
| "The sweep found nothing, but I'll run `WIZARD` anyway to be sure." | The sweep is `REVIEW-FINAL`'s and it already ran with the whole diff loaded. A second session re-deriving `NONE` costs a session and produces a file whose only content is that it has no content. |
| "I'll add a preflight stage so the wizard fails early if `gh` is not logged in." | That is a verification, and the wizard is only the commands the user must run. Name the tools it assumes in one line of `HANDOFF.md`. Every stage that is not an action is a screen of their morning spent on an agent's job. |
| "A stage at the end that checks it worked would be reassuring." | Reassuring and not theirs. "How to know it worked" is a line of prose in `HANDOFF.md`. A wizard is an apply, a paste and a click - nothing else. |
| "The `.env.example` entry is missing, that's a wizard stage." | You have a worktree, a branch and permissions. Do it, and commit it. A stage asking the user to do something an agent could have done in thirty seconds reads as a requirement and is really a chore handed over. |
| "The wizard can run the terraform apply / the deploy itself." | It can, behind a `confirm` that prints the command - the user is awake and driving it, so that is them deploying. Permissions and access-control changes are the exception: describe, never execute (charter #9). |
| "I'll put the key's value in the PR body so it's easy to find." | Never. Not the PR, not the script, not `LOG.md`, not a prompt file. The wizard asks for it with hidden input and sends it through stdin, so it is never even a process argument. |
| "The morning report can just say 'run scripts/setup.sh'." | From where, on which node version, after which `cd`? Give the one paste-ready command for a fresh terminal, plus where every value it asks for actually comes from. |

## Anti-Patterns

- **Bare `claude --bg`** during a sprint - bypasses the claim and can put two agents in one
  worktree. Always `launch.sh`, and always `revive.sh` to bring one back.
- **Restarting a ticket that only needed a resume** - the default reaction to a dead session is
  to resume its conversation, not to rebuild its context from zero.
- **Prompts authored lazily** - writing the review or test prompt only when you get there.
  Nobody is awake to fix a broken prompt; write them all at kickoff.
- **A silent night** - the morning report must name every ticket as landed, blocked, or
  abandoned. Never let a dropped ticket go unmentioned.
- **Reviving a `BLOCKED` session** - it hit something real. Relaunching just burns tokens
  into the same wall.
- **A continuation prompt that says "carry on from where I left off"** - the successor starts
  with an empty window and cannot read its predecessor's conversation. An unfilled handoff
  spends the fresh window rediscovering what the old one already knew, which is the entire cost
  the relay existed to avoid.
- **Relaying a session that is one command from green** - finish the ticket. The split buys
  nothing and costs a whole session of re-reading.
- **A review session that both finds and fixes** - that is the shape this skill moved away from.
  It spends one window on five specialist reports and then on editing code, and it is the session
  that used to hit the handoff line mid-triage, losing the triage.
- **A finder that posts its findings only as a file** - the PR is where the fixer, the bots and
  the user all already look, and an inline comment sits on the line it is about. The file is the
  backup for when the API rejects the anchors, not the deliverable.
- **Nudging a session twice** - `remind.sh` allows one per tag and that is deliberate. A session
  nagged repeatedly about its context spends more window reading nudges than they save.
- **A wizard stage that only reads, prints or checks** - delete it. If the sprint needs to know
  what is already configured, the `WIZARD` session reads it at authoring time and writes no stage
  for what is already done.
- **Busy-watching** - do not poll by hand in a loop; arm the watcher and react to events.
- **A wizard that runs itself end to end to "check it works"** - it opens browsers, blocks on
  human input, and its mutating stages act on live infrastructure. `bash -n`, `shellcheck`,
  and a static trace of every value from source to destination. Nothing else.
- **Hand-editing the wizard library** above the `STAGES` marker in `template.sh`. Every wizard
  the user ever runs behaves identically above that line, and that is the point of it.
- **A stage with an invented click path** - "Settings -> Integrations -> API" when nobody
  checked. An honest "find the API keys page, I could not verify the exact path" costs the
  user ten seconds; a wrong path costs them ten minutes and their trust in the other stages.
- **A wizard that is not re-runnable** - the user will hit a gate, go and merge something, and
  come back. Skip each stage on live state read at the start, never on a cache of what a
  previous run typed.
