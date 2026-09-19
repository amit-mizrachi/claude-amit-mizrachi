---
name: night-sprint
description: Delivers a whole feature overnight through autonomous sessions run strictly one after another, all on ONE branch landing as ONE pull request. A conductor session writes no code - it sets the sprint up, then a deterministic runner launches each ticket, advances the chain, revives what dies and waits out spending limits, escalating only what needs judgement. Each implementer watches its own context window and hands its ticket to a fresh session before it fills. Gets or builds a ticket breakdown first (via a spec and a ticket-splitting skill), decides whether to review once at the end or at checkpoints, runs each review as a FIND step plus a FIX step with only the review lanes that diff actually earns, optionally runs a test session that boots the stack or runs evals, makes the required CI checks at the pushed sha decide whether the sprint delivered, and ends by building an interactive setup wizard only when the feature genuinely needs a secret pasted, infra applied or a dashboard visited. Use when the user says "night sprint", "sprint this feature", "build this overnight", "run this while I sleep", "ticket after ticket", or wants a feature taken end to end unattended in a single PR.
argument-hint: "<feature | spec path | ticket dir | issue URL> [test: none|dev-stack|evals|<command>]"
---

# Night Sprint

## Overview

One feature, delivered overnight by a **chain** of sessions: ticket 01 lands, hands off to
ticket 02, and so on. **Exactly one session touches code at a time**, all in **one worktree on
one branch**, so the sprint ends as **one PR** with no integration step.

You are the **conductor**. You never write product code. You set the sprint up, launch the first
ticket, arm the runner, and then handle only what a script cannot decide.

**`watch.sh` is a runner, not just a watcher.** It advances the chain, revives dead sessions and
waits out spending limits by itself, logging everything to `state/EVENTS.log`. It escalates a
short list of exceptions to you. Silence from it means the sprint is running.

**This is the sequential sibling of `orchestrating-parallel-delivery`.** That skill splits work
across concurrent sessions to save wall-clock. This one deliberately does not: it is night time,
nobody is waiting, and serial execution buys correctness - no frozen contracts, no disjoint-file
rules, no merge conflicts, no tracker. If you catch yourself fanning out implementers, you are
in the wrong skill.

`references/rationale.md` holds the incident history behind every rule here. Read it when you
are changing the skill, not when you are running a sprint.

## Prerequisites - check these before kickoff, not at 3am

Only `next-prompt` ships in this plugin. The rest are named by ROLE; substitute whatever you
use, and write the real names into `PLAN.md` at kickoff so the sessions invoke the right thing.

| Role | What it does | Without it |
|---|---|---|
| a **code-review** skill | the review lanes the FIND step runs | nothing reviews the diff |
| an **address-review** skill | replies on external bot / human PR threads | external comments go unanswered |
| **`next-prompt`** (ships here) | the conductor handing itself on | the sprint dies when the conductor fills up |
| a **spec** skill | turning a feature into a spec at kickoff | bring your own spec |
| a **ticket-splitting** skill | cutting that spec into tickets | bring your own breakdown |
| a **wizard** skill | the closing `WIZARD` session's setup script | degrades: manual steps become prose |

A prompt naming an uninstalled skill is a session that stops at 3am with nobody awake to fix
it, and that is the cheapest failure to prevent. The **review step is the one hard dependency**:
a sprint without it still builds the feature and opens the PR, but nothing reviews the diff.
Decide that deliberately rather than discovering it in the morning.

## Kickoff (conductor, when the skill fires)

1. **Ask the two things you cannot infer - FIRST.** One `AskUserQuestion`, before you read a
   ticket or run a verify command. Kickoff takes a while and the user drifts away during it.
   - **Permission mode**: **`auto` is the default and what to use unless the user says
     otherwise.** Record it in `PERMISSION_MODE`. `acceptEdits` still prompts on shell commands
     and a background session cannot answer a prompt, so it stalls in `blocked` all night.
     `bypassPermissions` needs a one-time interactive disclaimer you cannot accept for the user;
     if they want it, hand them the interactive command **now**, while they are at the keyboard.
   - **Test session?** If the invocation said (`test: none|dev-stack|evals|<cmd>`), use it. Else
     ask: none, boot the stack via your repo's dev-environment skill and walk the golden path,
     run evals, or a custom command. If they pick the stack, get the skill name and boot command
     now and write both into `PLAN.md`.
2. **Get the tickets.** The sprint needs a plan already cut into tickets in dependency order.
   Tickets exist (a `.scratch/<slug>/issues/` dir, tracker issues, a plan with numbered slices)?
   Read them all. None? Run the spec skill on the feature, then the ticket-splitting skill, and
   take the user through their approval gates now. **Never start a sprint against a plan the user
   has not seen.** Copy the final tickets into `tickets/<NN>-<slug>.md` so the sprint has a
   frozen local copy even if the tracker changes overnight.
3. **Ground the run, into `facts.env`.** One `KEY=VALUE` per line, and this file is what the
   renderer fills every prompt from:

       REPO, REPO_PATH, REPO_SLUG, SLUG, USER, WS, WORKTREE, BRANCH, BASE, TOOLCHAIN,
       VERIFY, FORMAT_CHECK, CONVENTIONS, TOTAL,
       CONTEXT_WINDOW, WARN_AT_USED, RELAY_AT_USED, CEILING_USED

   **Confirm `VERIFY` actually runs before you launch anything** - a wrong one poisons every
   ticket in the chain. **`FORMAT_CHECK` is the formatter or lint gate CI runs that `VERIFY`
   does not**; find it now, because local green that is not CI green is how a sprint reports 21
   finished stages over a red PR.

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
   a reviver, a runner and a handback that all fail on their first line at 3am.
6. **Render the prompts rather than writing them.**

       bash <WS>/render.sh <WS> <WS>/implementer-prompt.md <WS>/prompt-T01.txt <WS>/vars-T01.env

   The renderer fills every slot from `facts.env` and **fails if one is left unfilled**, so the
   per-tag vars file has to be complete. You author only the judgement in it; this is the full
   set, by role, and nothing outside it is a slot:

   | Role | `vars-<TAG>.env` must set |
   |---|---|
   | implementer `T<NN>` | `TAG`, `NN`, `TICKET_TITLE`, `GOTCHAS`, `NEXT_TAG`, `CONVENTIONS`, `TOTAL` |
   | review finder | `TAG`, `CHECKPOINT`, `SCOPE`, `REVIEW_LANES`, `FIX_TAG`, `IMPL_TAG`, `NEXT_AFTER_FIX` |
   | review fixer | `TAG`, `CHECKPOINT`, `FIND_TAG`, `NEXT_TAG` |
   | `TEST` | `TOTAL`, `FIND_FINAL_TAG` |
   | `FIX-TEST` | `TAG=FIX-TEST`, `CHECKPOINT`, `FIND_TAG=TEST`, `NEXT_TAG` (leave empty - it decides its own) |
   | `WIZARD` | `SCRIPT_PATH` |
   | continuation (filled by the relaying session, not you) | `CONT_TAG`, `PREV_TAG`, `NN`, `TICKET_TITLE`, `NEXT_TAG` |

   **There is no `PR` slot, deliberately.** The draft PR does not exist at kickoff - it opens
   after `T01` lands - so a prompt that baked the number in could never render. The review
   prompts discover it themselves with `gh pr view --json number -q .number`.

   **What to render now:** every ticket prompt, every review pair, and `WIZARD`. Render `TEST`
   only if the user opted in - and **when you do, also render `prompt-FIX-TEST.txt` from
   `review-fix-prompt.md`** with `FIND_TAG=TEST`, keeping its FIX-TEST-ONLY section and deleting
   the FINAL-ONLY one. The tester routes an in-scope failure to `FIX-TEST`, and `launch.sh`
   refuses a tag with no prompt file, so without this the repair route dies at
   `launch: no prompt file`.

   **What to delete from each rendered file:** the FINAL-ONLY section from a checkpoint review's
   find and fix prompts; the FIX-TEST-ONLY section from every fixer except `FIX-TEST`; the two
   unused modes from the `TEST` prompt.
7. **Wire the chain.** Write each tag's successor to `state/<TAG>.next`, one tag per file
   (`T01.next` -> `T02`, the last one empty). `advance.sh` reads these; a session may overwrite
   its own before it writes its status.
8. **Write `PLAN.md`** from `plan-template.md` - the goal, out-of-scope, ticket order, the
   golden path the tester walks, and the protocol every session follows.
9. **Launch ticket 01** with `launch.sh`, then arm the runner and go into the monitor loop.

## Roles

| Role | Count | Writes code | Job |
|---|---|---|---|
| **Conductor** (you) | 1 at a time, hands itself on | never | set up, arm the runner, handle escalations, report. **Never interrupts a working session** |
| **Implementer** | 1+ per ticket, **serial** | yes | build ONE ticket green, commit, hand off - and watch its own window |
| **Review finder** | 1 per review | **never** | run the selected lanes, triage, write the findings manifest, post ONE PR comment, choose the fix route |
| **Review fixer** | 0 or 1 per finder | yes (fixes only) | work the manifest, reply on external threads, verify, push |
| **Tester** | 0 or 1 | no | exercise the built thing, report PASS/FAIL per step, write `GOLDEN.verdict` |
| **Wizard author** | **0 or 1**, last | yes (one script) | only when real setup is left: author the wizard, land it in the same PR |

## Coordination

| Thing | Convention |
|---|---|
| Workspace | `~/.claude/night-sprint/<slug>/` - `facts.env`, `PLAN.md`, `tickets/`, `prompt-<TAG>.txt`, `vars-<TAG>.env`, `state/`, `LOG.md` |
| Pinned facts | `facts.env`, plus one-value files the scripts read: `WORKTREE`, `SLUG`, `PERMISSION_MODE`, `BRANCH`, `VERIFY`, `CONTEXT_WINDOW`, `WARN_AT_USED`, `RELAY_AT_USED`, `CEILING_USED` |
| Tags | `T01`..`TNN`, a pair per review (`REVIEW-C1` + `FIX-C1` .. `REVIEW-FINAL` + `FIX-FINAL`), then `TEST`, `FIX-TEST` if the tester finds an in-scope failure, `WIZARD`, plus continuations `<TAG>c2`, `<TAG>c3` |
| Successors | `state/<TAG>.next`, written at setup, rewritable by the session **before** its status |
| Branch / worktree | ONE of each: `<type>/<slug>` off `origin/<default>`, in `.claude/worktrees/<slug>` |
| Launching | `bash <WS>/launch.sh <WS> <TAG>` - never a bare `claude --bg` |
| Advancing | `bash <WS>/advance.sh <WS> <TAG>` - **the only thing that decides what runs next** |
| Reviving | `bash <WS>/revive.sh <WS> <TAG> <cause>` - never re-launch a dead tag by hand |
| Handing a small fix set back | `bash <WS>/handback.sh <WS> <FIX_TAG> <IMPL_TAG> <manifest>` |
| Handing off | the SESSION does it, from its own prompt, when its own gauge says so. There is no conductor-side command and there must not be one |
| One tag, one session | many sessions per tag over a night, never two at once. `launch.sh` claims atomically; a session is never interrupted so never forked; `revive.sh` refuses any session whose transcript is still growing |
| Stopping | only `revive.sh` ever stops a session, and only a dead or blocked one. Never hand-roll a stop: `claude stop` takes the **short 8-char id**, never the full `sessionId` |
| Context | `bash <WS>/context-used.sh <SESSION_ID\|--self> <CONTEXT_WINDOW>` - percent USED, counting up |
| Status | `state/<TAG>.status` = `DONE` / `BLOCKED: <reason>` / `RELAYED: <TAG>c2` / `SKIPPED: <why>`, written **last** |
| Summary | `state/<TAG>.summary` - ONE line, what it actually did, for the ledger |
| Findings | `state/<TAG>.findings.md` - the manifest. The fixer's input, and it is LOCAL |
| Acceptance | `state/ACCEPTANCE.verdict` (CI, from `accept.sh`) and `state/GOLDEN.verdict` (the tester) |
| Manual steps | `state/<TAG>.manual` - appended the moment a session hits something only a human can do |
| Setup verdict | `state/SETUP.verdict` = `NEEDED` or `NONE` - decides whether `WIZARD` runs at all |
| Follow-ups | `state/FOLLOWUPS.md` - one line per real-but-out-of-scope thing |
| Durable ledger | `state/EVENTS.log` - every launch, advance, revive and pause, timestamped |
| Watching | `bash <WS>/watch.sh <WS>` under the `Monitor` tool, `persistent: true` |

## The templates and scripts

| File | Use |
|---|---|
| `references/bootstrap.sh` | build the workspace: copy the scripts, derive the facts, fail on anything missing |
| `references/plan-template.md` | the `PLAN.md` skeleton: facts, goal, ticket order, golden path, acceptance, protocol |
| `references/implementer-prompt.md` | one ticket, one session |
| `references/review-find-prompt.md` | the FIND step - selected lanes, triage, the manifest, the fix route |
| `references/review-fix-prompt.md` | the FIX step - work the manifest, external threads, the acceptance gate |
| `references/test-prompt.md` | the opt-in tester - pick ONE of its three modes and delete the rest |
| `references/wizard-prompt.md` | the closing `WIZARD` session |
| `references/continuation-prompt.md` | a relayed tag's successor - sessions fill this one themselves |
| `references/render.sh` | fill a template from `facts.env` + per-tag vars, and refuse a half-filled one |
| `references/launch.sh` | atomic claim + launch + session-id capture. Refuses while the sprint is paused |
| `references/advance.sh` | the single transition owner: read `.status` + `.next`, start the successor |
| `references/watch.sh` | the runner: does the routine, escalates the exceptions |
| `references/revive.sh` | the reviver, for dead sessions only: resume, then restart, then abandon |
| `references/classify-error.sh` | what actually ended a session: transient / quota / auth / none |
| `references/handback.sh` | resume the implementer for a small fix set instead of paying for a fresh window |
| `references/accept.sh` | are the required CI checks green **at the pushed sha**? |
| `references/agents.sh` | shared: ask the harness for background sessions, with the `--cwd` fallback |
| `references/context-used.sh` | the gauge: percent of a window already USED |
| `references/rationale.md` | **maintainer only, never loaded at runtime**: the incident behind every rule here |
| `tests/run.sh` | offline tests for the classifier, the transition owner, the renderer and the `set -u` guards |

**There is deliberately no script for the context rungs.** A session hands its own ticket on.

## Review cadence, and the lanes a diff earns

**Cadence:**
- **4 tickets or fewer, one subsystem** -> `REVIEW-FINAL` only.
- **5+ tickets, or the sprint crosses subsystems** (server + client, a schema change) -> a
  checkpoint at each natural seam, roughly every 3-4 tickets, plus the final one. Put one right
  after the ticket that lands a schema or interface everything else builds on.
- **Always at least one.** A sprint never ends without `REVIEW-FINAL`.
- A review is **a session in the chain, not a parallel job** - it holds the worktree.

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

### The fix route - the finder chooses one of three

| Route | When | How |
|---|---|---|
| **SKIP** | no findings AND no open bot / CI / human comment | write `SKIPPED` to `state/<FIX_TAG>.status`, point `.next` past it |
| **HAND BACK** | 5 findings or fewer, no BLOCKER, all inside files the implementer itself changed | `handback.sh` resumes that implementer with the manifest. It **refuses** if that window is past the relay line or the session is gone, and the fallback is a fresh fixer |
| **FRESH FIXER** | a BLOCKER, or findings spread past one ticket | `launch.sh <FIX_TAG>` |

Seven brand-new fixer sessions once cost 103M tokens, a quarter of a sprint, much of it
re-reading code the previous session had just written.

**The manifest is local and stays local.** `state/<TAG>.findings.md` carries
`ID / SEVERITY / LANE / WHERE / ISSUE / EVIDENCE / ACTION` per finding, and that file is what the
fixer reads. The PR gets **one** consolidated comment, with inline anchors only for BLOCKER and
HIGH where the exact line is the point. External bot, CI and human threads are different: each
gets a reply, because somebody outside the sprint is waiting on it.

## Monitor loop - what the runner escalates, and what you do

Arm one persistent `Monitor` on `watch.sh`. It handles launches, advances, revivals and quota
waits itself, and logs all of them to `state/EVENTS.log`. **It speaks only for these:**

| Event | Do |
|---|---|
| `BLOCKED <tag> <reason>` | It hit something real - do **not** revive. Record it, skip every ticket that lists it as a blocker, continue with the rest. |
| `DUP <tag> <id> <id> ...` | **Two agents in one worktree.** Drop everything and fix this first (below). Nothing else the runner says about `<tag>` can be trusted while it holds. |
| `AUTH <tag>` / `AUTH-PAUSE <...>` | The CLI is logged out or its token expired. No retry can fix it and the sprint is **stopped** - the runner idles rather than spending revives against it. The tag keeps **no** terminal status, because nothing about the work is wrong. Report it and give the exact two-step recovery: `claude /login` in a real terminal, then `bash <WS>/revive.sh <WS> <tag> auth-retry`, which clears the hold and resumes the conversation. |
| `BUDGET <tag> <class> retry-at <hh:mm>` | Out of capacity. **There is nothing to run** - the runner is waiting and will resume by itself. Log it; the morning report must explain the gap. |
| `BUDGET-EXHAUSTED <tag>` | Capacity never came back. Report what landed and what did not. |
| `HELD <tag>` | A successor was not launched because the sprint is paused. It launches when the pause clears. Nothing to do. |
| `REVIVE-REFUSED <tag>` | The reviver would not touch it - usually because it is still working. Read `state/EVENTS.log` and decide. |
| `NEEDS-PR` | Open the **draft** PR. Early CI and early bot review are why it opens after the first ticket rather than at the end. |
| `SWEEP 0 tags= all-sessions-terminal` | The runner **exited** - nothing is running. Tags left? Launch the next and **re-arm it**. Sprint complete? Write the morning report. Never leave the sprint with no armed runner and work outstanding. |
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
   `PLAN.md` + `LOG.md` + `state/`, re-arm the runner on `watch.sh`, resume the monitor loop,
   hold itself to the same two rungs.
3. Record the relay as its own ledger row, then stop. Do **not** stop the running sessions - the
   new conductor adopts them.

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
whose transcript grew recently, and stops what is left by **short id** before resuming.

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
**every rung** as its own ledger row.

## Acceptance - what "delivered" means

**Three different facts, three different files.** A sprint once reported all 21 stages complete
over a red PR - and every stage was telling the truth about itself.

| File | Written by | Means |
|---|---|---|
| `state/<TAG>.status` | each session | that session finished, was blocked, or handed on |
| `state/ACCEPTANCE.verdict` | `accept.sh`, run by `FIX-FINAL` | the required CI checks **at the pushed head sha**: `PASS` / `FAIL` / `UNKNOWN` |
| `state/GOLDEN.verdict` | the `TEST` session | the golden path actually walked: `PASS` / `FAIL` / `UNKNOWN` |

`DONE` has never meant "the branch is acceptable". **The headline verdict comes from the last
two**, and a sprint whose stages all said DONE while `ACCEPTANCE.verdict` says FAIL did not
deliver - the report says so in its first line.

`accept.sh` compares local HEAD to the pushed head first: a green check on a commit nobody pushed
proves nothing. `FIX-FINAL` gets **one bounded repair pass** on a FAIL, then leaves the PR in
draft and reports the red lanes honestly. **Local green is not CI green** - a formatter failure
was twice read as a warning-only lint rule - which is why `FORMAT_CHECK` is a pinned fact, and why
a session that finds a gate CI runs which `VERIFY` misses should say so.

## The manual steps, and the wizard that closes the sprint

A sprint can land every ticket green and still leave the user with nothing they can run: the code
is merged, the API key is not pasted, the terraform unit is not applied, the flag is off. Those
steps are a human's by definition, and an unattended agent should not be doing them at 4am - but a
sprint that ends without naming them ships a feature nobody can turn on.

So when a sprint leaves any of that behind, its last session is `WIZARD`: **one interactive bash
script, committed into the same PR**, that walks the user through each step in order, opens each
URL, says what to click, captures what they copy back, writes it where it belongs, and confirms
before anything irreversible.

**And it contains nothing else.** Every stage is an action the user performs. No preflight or
tool-check stages, no stage that reads live state and prints it, no stage that verifies the result
afterwards: all of that is work an agent can do, and the `WIZARD` session does it at authoring
time, writing no stage for what is already done. A three-stage wizard that applies a unit, sets a
secret and runs a migration is the target shape. Re-runnability comes free from the library, not
from a status stage: `ask` and `ask_secret` offer the existing value and keep it on Enter, and
`write_env` upserts.

**Where it sits:** `REVIEW-FINAL` -> `FIX-FINAL` -> `TEST` (if opted in) -> `WIZARD` -> report.
After the tester deliberately: the tester is the only session that tries to run the thing, and
"the stack would not boot without `X`" is exactly a wizard stage.

**Collect as you go.** Every session appends to `state/<TAG>.manual` the moment it hits something
it cannot do:

    STEP:     <one line: what a human must do>
    WHY:      <what breaks without it - the concrete failure, not "for configuration">
    WHERE:    <the URL, dashboard path or command, as concretely as it is known>
    VALUE:    <ENV_VAR_NAME, or "none" for a pure action>
    LANDS:    <.env | github secret | terraform var | a service | nowhere>
    SECRET:   <yes|no>
    BLOCKING: <yes = the feature does not work at all without it | no>

Those seven fields are exactly what a wizard stage needs. **Per-session, not reconstructed at the
end**: the diff shows a new `process.env.FOO`, but not that FOO's key lives behind a dashboard
toggle T04 spent an hour finding at 02:00. That knowledge exists in one session's window and dies
with it.

### What counts as a manual step - both tests, every time

**TEST 1 - REQUIRED.** The shipped feature does not work until this happens. Not "would be
convenient": broken or unreachable in a real environment until it is done.

**TEST 2 - HUMAN-ONLY.** No agent could have done it: a credential no agent holds, a console no
agent can reach, a human approval, or a production mutation policy puts on a person.

| Passes both - a stage | Fails test 1 - a report line | Fails test 2 - an agent's job |
|---|---|---|
| A secret, credential or token to paste or rotate | A `.env.local` a developer fills to run the app on their laptop | Adding a var to `.env.example` |
| A deploy, provision, terraform / terragrunt apply | Drift that predates the branch and the branch did not make matter | Writing or fixing a migration file |
| A migration against a real database | A judgement call the user may want to reverse | Wiring a config key the code should read itself |
| A third-party app or OAuth client to register | Anything already set - check live state first | Updating a README or runbook |
| A dashboard setting, DNS record, access rule or flag to flip | Merging the PR and deploying - always the user's, always named, never a stage | Adding the workflow step that runs the migration |
| A resource that must exist and no code creates it | A follow-up improvement, however good | Any code change at all |

Test 1's failures produce a **ceremonial** wizard. A pure front-end refactor of an already
deployed app needs nothing, and saying so in one line is the correct deliverable. Test 2's
failures are worse because they look useful: **a stage asking the user to do something an agent
could have done reads as a requirement when it is really a chore handed over.** The session that
finds one either does it - it has a worktree, a branch and permissions - or files one line in
`state/FOLLOWUPS.md`.

### The wizard is skipped when there is nothing to set up

`REVIEW-FINAL` applies both tests to every `state/*.manual` block and writes
`state/SETUP.verdict` - `NEEDED` or `NONE`. It sweeps the diff there because it already has the
whole diff loaded, which is what makes a `NONE` verdict trustworthy rather than merely unrecorded.
A `TEST` session, if one runs, settles the verdict last.

`NONE` **skips the session entirely** - no script, no handoff document, no commit. `SKIPPED: no
manual setup` goes to `state/WIZARD.status` with a one-line reason, and the morning report states
"nothing to set up" as a **finding**, naming what was swept to reach it.

**What the wizard will not do.** Permissions and access-control changes are described, never
executed - charter #9 puts those on a human reviewing a diff. Everything else may be a confirmed
mutating step, because the user is awake and driving: a `confirm` that prints the command first is
them doing it. And no real secret value is ever written into the script, a prompt file, `LOG.md`,
or the PR body.

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
| REVIEW-C1 | `...` | ns-<slug>-REVIEW-C1 | review finder | DONE | lanes run, n findings posted, n deferred, n rejected |
| FIX-C1 | `...` | ns-<slug>-FIX-C1 | review fixer (handback) | DONE | n fixed, n rejected and why |
| REVIEW-04 | `...` | ns-<slug>-REVIEW-04 | review finder | BUDGET-BLOCKED 1h59m | the wait, and what it finished afterwards |
| FIX-C2 | - | - | not launched | SKIPPED | nothing to address |
| WIZARD | - | - | not launched | SKIPPED | no manual setup - what was swept, and why nothing came up |

A ticket that took three sessions and two relays is exactly what the user wants to see. Read it
carefully though: **relays are the normal shape, not a signal.** A ticket that relayed twice is
ordinary; one whose relay came from `CEILING_USED` - a session that burned 60% of a window
without producing anything - says the breakdown was wrong. Say which kind each was. **Name every
budget wait with its duration**: that is usually the largest single line item in the night's
wall-clock, and it is not a failure of the work.

The final message must contain, in this order:

1. **The verdict in one line** - what the user actually has this morning, taken from
   `state/ACCEPTANCE.verdict` and `state/GOLDEN.verdict`, **not** from "every stage said DONE".
2. **The PR** - URL, draft or ready, CI state per failing lane if any.
3. **Ticket outcomes** - every ticket as landed / blocked / abandoned, with the reason for
   anything not landed. Never omit a dropped ticket.
4. **The session ledger** - the full table above.
5. **Review + test results** - findings fixed vs rejected vs deferred; the tester's per-step
   PASS/FAIL; which review lanes ran and which were skipped.
6. **Time lost to things that were not the work** - budget waits, auth stalls, revivals.
7. **Follow-ups** - `state/FOLLOWUPS.md`, verbatim, ready to become tickets. An empty file is a
   fine answer; say so.
8. **What needs a human** - decisions and blockers waiting on them.
9. **Turn it on** - the setup wizard, straight from `HANDOFF.md`. This is the part the user acts
   on first, so it must need no thinking.

   **If `state/WIZARD.status` reads `SKIPPED`, this whole item is one line**: "Nothing to set
   up", plus what was swept to reach it. Then name the two things that are always the user's and
   never wizard stages: **merge the PR, and deploy**. State it positively - "no setup needed" is a
   finding, not an empty section.
   - **The command**, paste-ready into a **fresh** terminal: an absolute `cd`, the toolchain
     line, then the script. Nothing left to work out.
   - **Every value it will ask for**, as a table: `Value | Where to get it | Secret? | Where it
     lands`. "Where to get it" is the path a human walks, or the exact read command. A row that
     just names a hostname sends the user hunting, which is the whole thing the wizard prevents.
   - **The gates**: where the script stops and waits on something to merge, deploy or approve.
   - **What the wizard will not do**, and who owns each.
   - **How to know it worked** - the check that proves the feature is live.

## The PR

Open **one draft PR** as soon as `T01` lands - the runner raises `NEEDS-PR` for it. Early CI and
early bot review give the checkpoint reviewers something real to address. Every later session
pushes to the same branch, so the PR grows all night. `FIX-FINAL` flips it out of draft once
`accept.sh` says PASS - never before, and the finder never does it. The `WIZARD` script is one
more commit on the same branch in the same PR, with a **Setup** section added to the description.
Never a second PR.

**Never merge and never deploy** - those are the user's, always. If a required check has no
ticket to point at, open the PR anyway and report the red check. Never fabricate a ticket id and
never bypass hooks with `--no-verify`.

## Red Flags - STOP

| Rationalization | Reality |
|---|---|
| "Tickets 3 and 4 are independent, I'll run both." | Serial is the contract - it is what removes conflicts and integration. Concurrency is `orchestrating-parallel-delivery`. |
| "I'll just implement this small ticket myself." | The conductor writes no product code. Your context is the scarcest resource of the night. |
| "No plan yet, I'll figure out tickets as I go." | Get a spec and a ticket breakdown approved first. An unapproved sprint builds the wrong thing 9 times. |
| "Run all six review lanes, it is more thorough." | It is five reviewers reading the same code to report nothing. Correctness always; the rest only where the diff gives them something to find. |
| "The reviewer found a one-line fix, it can just make it." | Then it is not a finder, and the next fat review dies mid-triage exactly the way the split was built to stop. |
| "The fixer should re-run the review to check nothing was missed." | That refills its window with specialist reports and puts it back in the failure mode the split removed. The manifest is the input. Reject an item in a line if it is wrong. |
| "Post each finding as its own inline comment so nothing is missed." | One consolidated comment, inline only for BLOCKER and HIGH. The fixer reads the LOCAL manifest; a round trip through GitHub to fetch back your own notes is not a review artefact. |
| "Every review needs a fresh fixer session." | Not for five findings in files the implementer just wrote. `handback.sh` resumes it, and refuses when that is the wrong call. Seven fresh fixers once cost 103M tokens. |
| "It stalled - retry harder and poll faster." | Classify it first. A spending cap cannot be solved by a faster watchdog, and a ladder spent against one loses hours while reporting a permission problem. |
| "T05 died on an API error, I'll relaunch the ticket." | Resume it - `revive.sh` does. The conversation is on disk; a fresh session re-reads the codebase and repeats every decision the dead one made. |
| "I'll resume it by hand, it's one `claude --bg --resume`." | Resume mints a **new session id** and drops the name. By hand, `state/<tag>.session` points at a corpse while a real session runs unwatched. |
| "The tests are red but the ticket is basically done." | Green or `BLOCKED: <reason>`. There is no third state. |
| "Every stage said DONE, so the sprint is delivered." | `DONE` means a session finished. Acceptance is `ACCEPTANCE.verdict` and `GOLDEN.verdict`. 21 green stages once shipped a red PR. |
| "`VERIFY` passes, so CI will pass." | It did not, twice, on formatting read as a warning-only lint rule. Run `FORMAT_CHECK`, and check the pushed sha with `accept.sh`. |
| "T05 relayed, so T05 is finished - launch T06." | `RELAYED` is not `DONE`. The ticket is still being built under `T05c2`. `advance.sh` knows; nothing else gets to decide. |
| "I'll launch the next tag myself off this DONE event." | `advance.sh` is the only transition owner. Two things deciding off two files is what once launched a fixer before its finder had decided there was anything to fix. |
| "I'm at `RELAY_AT_USED` but I'll see this event through first." | Relay now. A conductor that dies mid-night strands every session it was watching. |
| "30% used is barely anything, the session is fine." | The threshold is not a health check, it is a handoff point chosen so the handoff is GOOD. A session with 70% of its window left writes a successor prompt worth reading; one at 90% writes a shrug. |
| "A session is past its line and has not handed off - I'll do it for it." | You cannot. There is no way to message a running session, and the scripts that faked it forked sessions into duplicates. It is a log line, not a lever. |
| "The window is 1M, close enough to leave `CONTEXT_WINDOW` at the default." | Then every session relays after its first big read and the night goes on handoffs. It cannot be inferred from a transcript. |
| "`acceptEdits` is the safe default for an unattended run." | It is the mode that stalls: it still prompts on shell commands, and a background session cannot answer. Use `auto`. |
| "They picked `bypassPermissions`; I'll sort the disclaimer out at launch." | By then they are asleep. It needs a real terminal. Ask at step 1. |
| "I'll write the prompts by hand, it's more precise." | 22 prompts and 29,266 words once came out of one kickoff, mostly retyped facts. `render.sh` fills them from `facts.env` and fails on an unfilled slot. You author the judgement only. |
| "Nothing manual came up, but I'll write a wizard for completeness." | Then the user reads a script at 07:00 to learn it does nothing. Say "no setup needed" in one line. |
| "The `.env.example` entry is missing, that's a wizard stage." | You have a worktree, a branch and permissions. Do it and commit it. A stage asking the user to do an agent's chore reads as a requirement. |
| "I'll put the key's value in the PR body so it's easy to find." | Never. Not the PR, not the script, not `LOG.md`, not a prompt file. |

## Anti-Patterns

- **Bare `claude --bg`** during a sprint - bypasses the claim and can put two agents in one
  worktree. Always `launch.sh`, always `revive.sh`, always `advance.sh` for the chain.
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
- **A wizard stage that only reads, prints or checks** - delete it.
- **Busy-watching** - do not poll by hand in a loop; arm the runner and react to escalations.
- **A wizard that runs itself end to end to "check it works"** - it opens browsers, blocks on
  human input, and its mutating stages act on live infrastructure. `bash -n`, `shellcheck`, and
  a static trace of every value from source to destination. Nothing else.
- **Hand-editing the wizard library** above the `STAGES` marker in `template.sh`.
- **A stage with an invented click path** - an honest "I could not verify the exact path" costs
  the user ten seconds; a wrong path costs them ten minutes and their trust in every other stage.
