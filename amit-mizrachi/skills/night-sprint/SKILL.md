---
name: night-sprint
description: Delivers a whole feature overnight through autonomous sessions run strictly one after another - a conductor session that writes no code but launches each ticket, revives stuck or dead sessions, and fires the reviews, plus one implementer session per ticket, all on ONE branch landing as ONE pull request. Gets or builds a ticket breakdown first (via to-spec and to-tickets), decides whether to review once at the end or at checkpoints, and optionally ends with a test session that boots the stack or runs evals. Use when the user says "night sprint", "sprint this feature", "build this overnight", "run this while I sleep", "ticket after ticket", or wants a feature taken end to end unattended in a single PR.
argument-hint: '<feature | spec path | ticket dir | issue URL> [test: none|dev-stack|evals|<command>]'
---

# Night Sprint

## Overview

One feature, delivered overnight by a **chain** of sessions: ticket 01 lands, hands off to
ticket 02, and so on. **Exactly one session touches code at a time**, all of them in **one
worktree on one branch**, so the sprint ends as **one PR** with no integration step at all.

You are the **conductor**. You never write a line of product code. You set the sprint up,
launch the first ticket, then watch: revive what dies, fire the reviews at the points you
chose, launch the optional test session, and write the morning report.

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
4. **Decide the review cadence yourself** (see Review cadence) and state the decision.
5. **Build the workspace and the branch** (see Coordination), including the shared worktree,
   `PLAN.md`, and **every** prompt file - ticket prompts, review prompts, test prompt. Write
   them all now: at 3am there is nobody to author a missing prompt.
6. **Launch ticket 01** with `launch.sh`, then arm the watcher and go into the monitor loop.

## Roles

| Role | Count | Writes code | Job |
|---|---|---|---|
| **Conductor** (you) | 1 | never | set up, launch, watch, revive, fire reviews, report |
| **Implementer** | 1 per ticket, **serial** | yes | build ONE ticket green, commit, hand off to the next |
| **Reviewer** | 1 per checkpoint + 1 final | yes (fixes only) | `quad-review-squad` then `address-review` |
| **Tester** | 0 or 1 | no | exercise the built thing, report PASS/FAIL per step |

## Coordination

| Thing | Convention |
|---|---|
| Workspace | `~/.claude/night-sprint/<slug>/` - `PLAN.md`, `tickets/`, `prompt-<TAG>.txt`, `state/`, `LOG.md` |
| Pinned facts | one value per file: `WORKTREE`, `SLUG`, `PERMISSION_MODE`, `BRANCH`, `VERIFY` |
| Tags | `T01`..`TNN`, `REVIEW-C1`..`REVIEW-CN`, `REVIEW-FINAL`, `TEST` |
| Branch | ONE: `<type>/<slug>` off `origin/<default>` |
| Worktree | ONE, shared by every session: `.claude/worktrees/<slug>` |
| Launching | **always** `bash <WS>/launch.sh <WS> <TAG>` - never a bare `claude --bg` |
| Status | each session writes `state/<TAG>.status` = `DONE` or `BLOCKED: <reason>` as its last act |
| Summary | each session also writes `state/<TAG>.summary` - ONE line, what it actually did, for the ledger |
| Signal | each session's final commit body also carries `SIGNAL: <TAG>-DONE` / `-BLOCKED: <reason>` |
| Watching | `bash <WS>/watch.sh <WS>` under the `Monitor` tool, `persistent: true` |

## The templates - read these before writing anything

| File | Use |
|---|---|
| `references/plan-template.md` | the `PLAN.md` skeleton: facts, goal, ticket order, golden path, protocol |
| `references/implementer-prompt.md` | one ticket, one session - fill one per ticket |
| `references/review-prompt.md` | checkpoint and final reviewer (the FINAL-only block is marked) |
| `references/test-prompt.md` | the opt-in tester - pick ONE of its three modes and delete the rest |
| `references/launch.sh` | atomic claim + launch + session-id capture |
| `references/watch.sh` | the watcher: emits DONE / BLOCKED / STUCK / DIED / STALLED events |

Copy both scripts into the workspace at setup (`cp` + `chmod +x`) and use those copies, so
editing the skill never changes a sprint already running. Fill every `<PLACEHOLDER>` in the
prompts - an unfilled placeholder is a session that wakes up at 3am not knowing what to build.

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
- A review is **quad-review-squad** on the accumulated branch diff, then **address-review**
  for any PR comments the bot or CI has left. The reviewer fixes what it accepts and pushes.
- A review is a **session in the chain, not a parallel job** - it holds the worktree, so the
  next ticket does not launch until the review reports its status.

## Monitor loop

Arm one persistent `Monitor` on `watch.sh` and react to each event. Keep every reaction
short - you have to survive until morning, so log to `LOG.md` and keep your context lean.

| Event | Do |
|---|---|
| `DONE <TNN>` | If the next tag is unclaimed, `launch.sh` it (the implementer normally already did - the claim makes a double call harmless). At a checkpoint boundary, launch the reviewer instead. After `T01`, open the **draft** PR. |
| `DONE REVIEW-FINAL` | Launch `TEST` if the user opted in; else go to the morning report. |
| `DONE TEST` | Morning report. |
| `STUCK <TAG> permission-prompt` | `claude stop <id>`, revive (below). If already on the permissive mode, it is a *question*, not a permission - revive with "decide it yourself and proceed" appended. |
| `DIED <TAG> ended-without-signal` | Read `claude logs <id>` and `git log` on the branch to see how far it actually got, then revive with a RESUME note naming what already landed. |
| `STALLED <TAG> idle-<N>m` | Check `claude logs <id>`. Genuinely idle -> stop and revive. Mid-build/mid-install -> leave it, allow one more stall window, then treat as DIED. |
| `BLOCKED <TAG> <reason>` | Do **not** revive - it reported a real blocker. Record it, skip every ticket that lists it as a blocker, continue with the rest. |
| `SWEEP <n>` | Heartbeat, roughly every 10 polls. Nothing to do. |
| `SWEEP 0 ... all-sessions-terminal` | The watcher has **exited** - nothing is running. If tags remain, launch the next one and **re-arm the watcher**; if the sprint is complete, write the morning report. Never leave the sprint with no armed watcher and work outstanding. |

**Revive** = `claude stop <id>`; `rm -rf state/claim-<TAG> state/<TAG>.session`; bump
`state/<TAG>.attempts`; re-launch. **Two attempts per tag, then stop trying**: mark it
ABANDONED in `LOG.md`, skip its dependents, carry on with the rest of the sprint. A sprint
that delivers 7 of 9 tickets and says so plainly beats one that loops on ticket 3 all night.

**Conductor relay - hard rule at 35%.** The sprint outlives any one conductor. **The moment
your remaining context reaches 35%, relay** - do not wait until you are nearly out, and do not
try to squeeze in one more ticket:

1. Flush the live state to `LOG.md` (see Session ledger) so nothing lives only in your head.
2. `/next-prompt` a fresh conductor whose prompt points at the workspace and says: read
   `PLAN.md` + `LOG.md` + `state/`, re-arm the watcher on `watch.sh`, resume the monitor loop,
   and relay again at 35% yourself.
3. Record the relay in `LOG.md` as its own ledger row, then stop. Do **not** stop the watcher's
   implementer sessions - they keep running and the new conductor adopts them.

`PLAN.md` + `LOG.md` + `state/` are written precisely so a cold conductor can pick the sprint
up without your context. Relay as many times as the night needs.

## Session ledger and the morning report

The user wakes up to one message and needs to reconstruct a night they slept through, so the
report is **an account of who did what**, not just a status.

Keep a running ledger table in `LOG.md` and append a row the moment a session reaches a
terminal state - never reconstruct it at the end from memory. One row per session **including
every revived attempt and every conductor relay**, built from `state/<TAG>.session`,
`.status`, and `.summary`:

| Tag | Session id | Name | Role | Verdict | What it did |
|---|---|---|---|---|---|
| T01 | `a1b2c3d4` | ns-<slug>-T01 | implementer | DONE | one line from `.summary` |
| T03 | `e5f6...` | ns-<slug>-T03 | implementer (attempt 1) | DIED, revived | how far it got before it died |
| REVIEW-C1 | `...` | ns-<slug>-REVIEW-C1 | reviewer | DONE | findings accepted vs rejected |

The final message must contain, in this order:

1. **The verdict in one line** - what the user actually has this morning.
2. **The PR** - URL, draft or ready, CI state.
3. **Ticket outcomes** - every ticket as landed / blocked / abandoned, with the reason for
   anything that is not landed. Never omit a dropped ticket.
4. **The session ledger** - the full table above. This is the part the user asked for: how
   many sessions the sprint burned and what each one contributed.
5. **Review + test results** - findings addressed vs deferred; the tester's per-step PASS/FAIL.
6. **What needs a human** - the decisions, blockers, and follow-ups waiting on them.

## The PR

Open **one draft PR** as soon as `T01` lands - not at the end. Early CI and early bot review
give the checkpoint reviewers something real to address. Every later session pushes to the
same branch, so the PR grows all night. At the very end, flip it out of draft and report it.

**Never merge and never deploy** - those are the user's, always. If a required check
(e.g. a Monday-item check) has no ticket to point at, open the PR anyway and report the red
check. Never fabricate a ticket id and never bypass hooks with `--no-verify`.

## Red Flags - STOP

| Rationalization | Reality |
|---|---|
| "Tickets 3 and 4 are independent, I'll run both." | No. Serial is the contract - it is what removes conflicts and integration. Concurrency is `orchestrating-parallel-delivery`. |
| "I'll just implement this small ticket myself." | The conductor writes no product code. Your context is the scarcest resource of the night; spend it watching. |
| "No plan yet, I'll figure out tickets as I go." | Run `/to-spec` + `/to-tickets` and get approval first. An unapproved sprint builds the wrong thing 9 times. |
| "Ticket 5 is stuck; I'll keep retrying until it works." | Two attempts, then ABANDONED and move on. Report the gap. |
| "Each ticket can open its own PR." | One branch, one PR. That is the deliverable. |
| "The tests are red but the ticket is basically done." | Green or `BLOCKED: <reason>`. There is no third state. |
| "I'll review everything at the end, it's simpler." | For 5+ tickets a late review means unwinding a night of work. Checkpoint at the seams. |
| "It says DONE, so it works." | `DONE` means the session claims green. The tester and the final review are what earn it (charter #10). |
| "I'm down to 30% context but I'll see this ticket through first." | Relay at 35%, no exceptions. A conductor that dies mid-ticket strands every session it was watching. |
| "`acceptEdits` is the safe default for an unattended run." | It is the mode that stalls. It still prompts on shell commands, and a background session cannot answer a prompt - it sits in `blocked` until you revive it. Use `auto`. |
| "They picked `bypassPermissions`; I'll sort the disclaimer out when I launch." | By then they are asleep. `--bg` refuses until the one-time disclaimer is accepted in a real terminal, and neither you nor the `!` prefix can accept it for them. Ask at step 1, while they are still at the keyboard. |
| "I'll write the session ledger at the end from the log." | Append each row as it happens. Sessions you revived or relayed away are exactly the ones you will forget. |

## Anti-Patterns

- **Bare `claude --bg`** during a sprint - bypasses the claim and can put two agents in one
  worktree. Always `launch.sh`.
- **Prompts authored lazily** - writing the review or test prompt only when you get there.
  Nobody is awake to fix a broken prompt; write them all at kickoff.
- **A silent night** - the morning report must name every ticket as landed, blocked, or
  abandoned. Never let a dropped ticket go unmentioned.
- **Reviving a `BLOCKED` session** - it hit something real. Relaunching just burns tokens
  into the same wall.
- **Busy-watching** - do not poll by hand in a loop; arm the watcher and react to events.
