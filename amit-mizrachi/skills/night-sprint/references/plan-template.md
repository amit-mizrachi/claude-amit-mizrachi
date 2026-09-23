# <FEATURE TITLE> - night sprint plan

> Sequential autonomous build: one ticket per session, one after another, ONE branch, ONE PR.
> <USER> is asleep. Every session decides for itself, verifies, commits, hands off. No session
> asks a question, and no two sessions run at the same time. ASCII only, no em/en dashes.
> Written by the conductor at kickoff; a cold conductor can resume the sprint from this file
> plus LOG.md plus state/.

## Facts

| | |
|---|---|
| Repo | `<REPO_PATH>` (`<REPO_SLUG>`) |
| Base | `origin/<default>` at `<sha>` |
| Branch | `<type>/<slug>` - the ONLY branch |
| Worktree | `<WORKTREE>` - the ONLY worktree, shared by every session |
| Workspace | `<WS>` |
| Toolchain | `<env setup, e.g. source ~/.nvm/nvm.sh && nvm use 22>` |
| Verify | `<VERIFY>` - the one full check every session must pass, confirmed runnable at kickoff |
| Format / CI parity | `<FORMAT_CHECK>` - the formatter or lint gate CI runs that `Verify` does not. Local green is not CI green, and that gap has turned a green report into a red PR |
| Permission mode | `<auto - the default; only something else if the user asked for it>` |
| Context window | `<200000 | 1000000>` - the sprint model's window, pinned because it cannot be read off a transcript |
| Warn at | `<20>`% of the window USED - the session is nudged to start nothing new |
| Relay at | `<30>`% of the window USED - the session hands its tag to a fresh one |
| Ceiling | `<60>`% used - the relay is held until a session has produced work, but never past this |
| Review cadence | `<final only | checkpoints after T<NN>, T<NN>, plus final>` - and why. Each review is a FIND step and a FIX step |
| Review lanes | `<correctness, plus the lanes this feature's risk actually earns>` - correctness always; security / architecture / observability / reuse / simplification only where the diff gives them something to find. Never all six by default |
| Test session | `<none | dev-stack | evals | custom: <cmd>>` - chosen by the user |
| How to boot the stack | `<the dev-environment skill name and/or the exact boot command>` - only for `dev-stack`; the TEST session reads it from here |

## 1. Goal

<What the user gets when this sprint lands, in their words. The concrete thing they should be
able to do in the morning that they cannot do tonight. Plus any decision made at kickoff that
the tickets assume - so no session re-litigates it at 3am.>

## 2. Out of scope

<What this sprint deliberately does not do. Prevents a session at 4am from expanding the work
because a ticket looked incomplete on its own.>

## 3. Tickets (in dependency order - this IS the execution order)

Frozen copies live in `<WS>/tickets/`. Blockers are already satisfied by position: ticket NN
may assume every ticket before it has landed on the branch.

| Tag | Ticket | Delivers | Blocked by | Then |
|---|---|---|---|---|
| T01 | `01-<slug>.md` | <end-to-end behaviour this makes work> | none | T02 |
| T02 | `02-<slug>.md` | <...> | T01 | T03 |
| T03 | `03-<slug>.md` | <...> | T02 | REVIEW-C1 |
| REVIEW-C1 | - | checkpoint review of T01-T03 with the selected lanes: findings into `state/REVIEW-C1.findings.md` plus one consolidated PR comment. Writes no code | T03 | FIX-C1 |
| FIX-C1 | - | works REVIEW-C1's manifest, replies on external threads, verifies, pushes. May be REVIEW-C1's implementer resumed via `handback.sh` | REVIEW-C1 | T04 |
| ... | | | | |
| T<NN> | `<NN>-<slug>.md` | <...> | T<NN-1> | REVIEW-FINAL |
| REVIEW-FINAL | - | the selected lanes over the whole PR, the ticket-by-ticket acceptance re-read, and the setup sweep. Writes no code | T<NN> | FIX-FINAL |
| FIX-FINAL | - | works the manifest and every external comment, runs `accept.sh`, and `gh pr ready` only on PASS | REVIEW-FINAL | TEST, or end if no test session |
| TEST | - | <the chosen test mode>; writes `state/GOLDEN.verdict` | FIX-FINAL | FIX-TEST if an in-scope step failed, else end |
| FIX-TEST | - | one bounded repair pass over `state/TEST.findings.md`, then re-runs the affected golden-path steps. Only rendered when a test session was chosen | TEST | end |

## 4. Acceptance - the golden path the tester walks

<The numbered end-to-end steps that prove the feature works, authored HERE at kickoff, not
invented at 4am by the tester. Each step is something observable: a screen, a response, a
row, an eval score.>

1. <step>
2. <step>
3. <step>

## 5. Protocol (identical for every session)

1. Work in `<WORKTREE>` on `<BRANCH>`. Never create a branch or worktree. Never rebase,
   force-push, or merge.
2. Implement only your own tag's scope. Verify with the verify command; never `--no-verify`.
3. Final commit body carries `SIGNAL: <TAG>-DONE` or `SIGNAL: <TAG>-BLOCKED: <reason>`. Push.
4. Write `state/<TAG>.summary` (one line, what you did), then `state/<TAG>.status`
   (`DONE` / `BLOCKED: <reason>`) LAST - the status is what releases the next session.
5. Write `state/<TAG>.next` - your successor's tag, or empty - BEFORE the status file. Then
   `bash <WS>/advance.sh <WS> <TAG>` exactly once. That script is the ONLY thing that decides
   what runs next: it reads the pair, claims the tag atomically, and is a harmless no-op if
   the watcher got there first. Two different things deciding the next tag off two different
   files is what once launched a fixer before its finder had decided there was anything to fix.
6. If BLOCKED: push what you have, write the status, and still run `advance.sh` - it will
   correctly launch nothing and record the blocker. The conductor decides what happens next.
7. The moment you hit something only a human can do - a key to paste, a unit to apply, an app
   to register, a flag to switch - append a `STEP / WHY / WHERE / VALUE / LANDS / SECRET /
   BLOCKING` block to `state/<TAG>.manual`. Do not attempt it. See section 8.

## 5a. Manual steps - what the night cannot do for the user

Some of this feature is not code: a secret gets pasted, a terraform unit gets applied, a
third-party app gets registered. Those are <USER>'s by definition and no unattended session
attempts them. But a sprint that lands green and leaves them unnamed ships something nobody can
turn on, so every session records what it meets, as it meets it, in `state/<TAG>.manual`:

    STEP:     <one line: what a human must do>
    WHY:      <what breaks without it - the concrete failure>
    WHERE:    <the URL, dashboard path or command, as concretely as it is known>
    VALUE:    <ENV_VAR_NAME, or "none" for a pure action>
    LANDS:    <.env | github secret | terraform var | a service | nowhere>
    SECRET:   <yes|no>
    BLOCKING: <yes = the feature does not work at all without it | no>

Be concrete about WHERE, and never invent a menu path nobody walked. Never write a real secret
value into that file, a commit, a summary, or the PR.

**A block must pass BOTH tests.** (1) REQUIRED: the shipped feature does not work until this
happens. (2) HUMAN-ONLY: no agent could have done it - it needs a credential no agent holds, a
console no agent can reach, a human approval, or it is a production mutation policy puts on a
person. A key the deployed feature needs passes both. A `.env.local` somebody fills to run the
app on their laptop fails the first, as does drift already broken on the base ref and a judgement
call <USER> may want to reverse. Anything an agent could simply have done - adding a var to
`.env.example`, wiring a config key, updating a runbook - fails the second: the session that
found it either does it, or writes one line to `state/FOLLOWUPS.md` for the morning report to
turn into a ticket.

Known from kickoff, before a single session runs:

- <anything the conductor already knows will need the user - a key, an apply, a flag>

## 5b. The setup verdict

`REVIEW-FINAL` sweeps the branch diff for setup (new env reads, new `secrets.*` in workflows,
new infra units, new migrations, new third-party integrations), checks what is already
configured, applies both tests above, and writes `state/SETUP.verdict` - `NEEDED` or `NONE`. It
does that sweep because it already has the whole diff loaded for the review, so it is nearly
free there. If a test session runs, it settles the verdict last, because it is the only session
that tries to run the thing.

`NONE` means the morning report states "nothing to set up" as a finding, naming what was swept.

## 6. CONTEXT RELAY - you manage your own window, and a ticket may take more than one session

A context window is smaller than some tickets, and a session that pushes on until it is full does
not stop cleanly. So no session runs itself to the end of its window: it hands its tag to a fresh
one early, while it still has most of a window left to explain itself. `T03` becomes
`T03 -> T03c2 -> T03c3`: one ticket, several sessions, still strictly one at a time. That is the
intended shape of this sprint, not a sign a ticket went wrong.

**Every session manages its own window, and nothing else can.** The sprint cannot send a message
into a running session - there is no interrupt, no reminder, no script that hands a ticket on from
outside. A session that does not measure itself runs until the harness auto-compacts it and loses
the reasoning that mattered. So the handoff is the session's own job, and the same job for every
role including the conductor.

Measure with `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>`. **The number counts UP** - 0 is a
fresh session, 100 is a full one, exactly as `/context` reports it. Measure after each commit,
after any fan-out returns, after any noisy build or search, before opening a group of unread files,
before starting the next acceptance criterion, and whenever you cannot remember the last check.

| Rung | Reading | The session does |
|---|---|---|
| Narrow | `<WARN_AT_USED>`% used | Starts nothing new. Finishes what it is on, stops widening its reading, opens no new front |
| Hand off | `<RELAY_AT_USED>`% used | Consolidates and hands its tag to a fresh session, per the steps below |

Two guards keep the early handoff from becoming waste, and both are the session's to apply. A
session **one command from green finishes instead of handing off**. And a session that **has not
changed a single file does not hand off at all** - its successor would start exactly where it did,
minus the reading, which is how a ticket loops all night without being built. Past
`<CEILING_USED>`% used that second guard expires: hand off anyway and say in the continuation
prompt that the ticket was bigger than the plan thought.

The conductor does not drive any of this. `watch.sh` reads the same number only to raise
`OVERDUE` when a session is far past its own line and still has not handed off - a report for the
morning, not a lever. Nothing external interrupts a working session.

At `<RELAY_AT_USED>`% used, the session:

1. commits and pushes what it has - WIP with `SIGNAL: <TAG>-RELAYED` in the body if not green;
   never stashes and never reverts;
2. fills `<WS>/continuation-prompt.md` into `<WS>/prompt-<TAG>c2.txt` - what landed, criteria
   met and not met, real verify output, files changed and next, every decision and dead end,
   and the `NEXT_TAG` to launch when the ticket is finally green;
3. writes `state/<TAG>.summary`, then `state/<TAG>.next`, then `state/<TAG>.status` =
   `RELAYED: <TAG>c2` - **`RELAYED`, never `DONE`**: the ticket is still in flight and `DONE`
   would release the next ticket;
4. writes `state/<TAG>.next` = `<TAG>c2`, then runs `bash <WS>/advance.sh <WS> <TAG>`, and
   launches nothing else.

A session that is one command from green finishes instead of relaying.

## 7. Acceptance - what "delivered" means, and what it does not

Three different facts, three different files, because a sprint once reported all 21 stages
complete over a red PR. `DONE` in `state/<TAG>.status` means one session finished its work. It
has never meant the branch is acceptable.

| File | Written by | Means |
|---|---|---|
| `state/<TAG>.status` | each session | that session finished, was blocked, or handed on |
| `state/ACCEPTANCE.verdict` | `accept.sh`, run by FIX-FINAL | the required CI checks at the PUSHED head sha: `PASS` / `FAIL` / `UNKNOWN` |
| `state/GOLDEN.verdict` | the TEST session | the golden path above, actually walked: `PASS` / `FAIL` / `UNKNOWN` |

The morning report's headline verdict comes from the last two. A sprint whose every stage said
DONE and whose `ACCEPTANCE.verdict` says FAIL is a sprint that did not deliver, and the report
says so in its first line.

## 8. The conductor, and the runner that does the routine

The conductor writes no product code. It arms `watch.sh` under a persistent Monitor and then
handles only what a script cannot.

**`watch.sh` does the routine itself**: it advances the chain through `advance.sh` on every
terminal status, revives dead and stalled sessions through `revive.sh`, and pauses the whole
sprint when the account runs out of capacity, resuming when the limit resets. All of it lands
in `state/EVENTS.log`, timestamped, which is the ledger the morning report is built from.

**It escalates only these**, and each is a judgement:

| Event | The conductor's job |
|---|---|
| `BLOCKED <tag> <reason>` | record it, skip the tickets that depend on it, carry on with the rest |
| `DUP <tag> <ids>` | two agents in one worktree - drop everything and settle it first |
| `AUTH <tag>` / `AUTH-PAUSE` | the sprint is stopped until a human re-authenticates. Report the two-step recovery: `claude /login`, then `revive.sh <WS> <tag> auth-retry`. The tag keeps no terminal status - the work is fine, only the login is not |
| `BUDGET <tag> <class> retry-at <hh:mm>` | nothing to do, but the morning report must explain the gap |
| `BUDGET-EXHAUSTED <tag>` | capacity never returned; report what did and did not land |
| `NEEDS-PR` | open the draft PR - writing a PR body is not a script's job |
| `REVIVE-REFUSED <tag>` | read `state/EVENTS.log` and decide |
| `SWEEP 0 ... all-sessions-terminal` | the watcher exited. Work left? Re-arm it. Sprint over? Write the report |
| `SWEEP <n> tags=...` | a heartbeat, and only after a full hour of silence. Nothing to do |

**It never interrupts a session that is working.** There is no mechanism for it and the sprint
does not want one: a live session owns its own window and its own handoff. The conductor acts
only on sessions that are already gone and on tags that never started.

It holds itself to the same two rungs as everyone else, measured with
`bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` at every event it does receive: at
`<WARN_AT_USED>`% used it stops taking on anything beyond watching, and at `<RELAY_AT_USED>`%
used it flushes `LOG.md` and `/next-prompt`s a fresh conductor. Never merges and never
deploys - those are <USER>'s.
