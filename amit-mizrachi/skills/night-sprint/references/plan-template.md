# <FEATURE TITLE> - night sprint plan

> Sequential autonomous build: one ticket per session, one after another, ONE branch, ONE PR.
> <USER> is asleep. Every session decides for itself, verifies, commits, hands off. No session
> asks a question, and no two sessions run at the same time. ASCII only, no em/en dashes.
> Written by the conductor at kickoff; a cold conductor can resume the sprint from this file
> plus LOG.md plus state/.

## Facts

| | |
|---|---|
| Repo | `<ABSOLUTE REPO PATH>` (`<owner/repo>`) |
| Base | `origin/<default>` at `<sha>` |
| Branch | `<type>/<slug>` - the ONLY branch |
| Worktree | `<ABSOLUTE WORKTREE PATH>` - the ONLY worktree, shared by every session |
| Workspace | `<WS>` |
| Toolchain | `<env setup, e.g. source ~/.nvm/nvm.sh && nvm use 22>` |
| Verify | `<the one full check every session must pass>` - confirmed runnable at kickoff |
| Permission mode | `<auto - the default; only something else if the user asked for it>` |
| Context window | `<200000 | 1000000>` - the sprint model's window, pinned because it cannot be read off a transcript |
| Warn at | `<20>`% of the window USED - the session is nudged to start nothing new |
| Relay at | `<30>`% of the window USED - the session hands its tag to a fresh one |
| Ceiling | `<60>`% used - the relay is held until a session has produced work, but never past this |
| Review cadence | `<final only | checkpoints after T<NN>, T<NN>, plus final>` - and why. Each review is TWO sessions: find, then fix |
| Test session | `<none | dev-stack | evals | custom: <cmd>>` - chosen by the user |

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
| REVIEW-C1 | - | checkpoint review of T01-T03: quad squad, findings posted as inline PR comments. Writes no code | T03 | FIX-C1 |
| FIX-C1 | - | implements REVIEW-C1's findings via `address-review`, verifies, pushes | REVIEW-C1 | T04 |
| ... | | | | |
| T<NN> | `<NN>-<slug>.md` | <...> | T<NN-1> | REVIEW-FINAL |
| REVIEW-FINAL | - | quad squad over the whole PR + the setup sweep. Writes no code | T<NN> | FIX-FINAL |
| FIX-FINAL | - | addresses every finding and bot comment, then `gh pr ready` | REVIEW-FINAL | TEST, or WIZARD if no test session |
| TEST | - | <the chosen test mode> | FIX-FINAL | WIZARD |
| WIZARD | - | the setup wizard for every manual step, committed into the same PR | TEST | end |

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
5. If DONE and a next tag exists: `bash <WS>/launch.sh <WS> <NEXT_TAG>` exactly once. The
   script claims the tag atomically; if the conductor got there first it is a harmless no-op.
6. If BLOCKED: push what you have, write the status, and stop. Do not launch anything - the
   conductor decides what happens next.
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
turn into a ticket. A wizard stage that asks <USER> to do an agent's chore is the worst thing
this sprint can produce.

Known from kickoff, before a single session runs:

- <anything the conductor already knows will need the user - a key, an apply, a flag>

## 5b. The wizard - the last session of the sprint, and it may not run

`REVIEW-FINAL` sweeps the branch diff for setup (new env reads, new `secrets.*` in workflows,
new infra units, new migrations, new third-party integrations), checks what is already
configured, applies both tests above, and writes `state/SETUP.verdict` - `NEEDED` or `NONE`. It
does that sweep because it already has the whole diff loaded for the review, so it is nearly
free there. If a test session runs, it settles the verdict last, because it is the only session
that tries to run the thing.

`NONE` means **no `WIZARD` session at all**: `state/WIZARD.status` gets `SKIPPED: no manual
setup` and the morning report states "nothing to set up" as a finding, naming what was swept.

`NEEDED` launches `WIZARD`, which re-applies both tests itself, then authors ONE re-runnable
interactive script. It is committed to `<BRANCH>` and lands in the SAME PR, never a second one.

**The script contains only commands <USER> must run: an apply, a paste, a click.** No preflight
or tool-check stages, no stage that reads and prints live state, no stage that verifies the
result afterwards - the `WIZARD` session does all of that itself at authoring time and simply
writes no stage for anything already done or anything an agent could do. A three-stage wizard
that applies a unit, sets a secret and runs a migration is the target shape. Re-runnability comes
free from the library: `ask`/`ask_secret` offer the existing value and keep it on Enter, and
`write_env` upserts.

Script path: `<WORKTREE>/scripts/<slug>-setup.sh` (or wherever this repo keeps operator scripts)
Built from: the `wizard` skill and its `template.sh` - the library above the STAGES marker is
never hand-edited.

If nothing manual comes up, `WIZARD` writes no script and says so in one line. Permissions and
access-control changes are described by the wizard, never executed by it.

## 6. Context - two rungs, and a ticket may take more than one session

A context window is smaller than some tickets, and a session that pushes on until it is full does
not stop cleanly. So no session runs itself to the end of its window: it hands its tag to a fresh
one early, while it still has most of a window left to explain itself. `T03` becomes
`T03 -> T03c2 -> T03c3`: one ticket, several sessions, still strictly one at a time. That is the
intended shape of this sprint, not a sign a ticket went wrong.

Every session measures itself with `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` after any
large read, long build, or subagent fan-out. **The number counts UP** - 0 is a fresh session, 100
is a full one, exactly as `/context` reports it. The conductor watches the same number for every
open tag through `watch.sh`.

| Rung | Reading | The session does | The conductor does |
|---|---|---|---|
| Nudge | `<WARN_AT_USED>`% used | Starts nothing new. Finishes what it is on, stops widening its reading, opens no new front | `bash <WS>/remind.sh <WS> <TAG> <used>` on a `WARN` event |
| Handoff | `<RELAY_AT_USED>`% used | Consolidates and hands its tag on, per the steps below | `bash <WS>/relay.sh <WS> <TAG> <used>` on a `FAT` event |

Two guards keep the early handoff from becoming waste. A session **one command from green
finishes instead of relaying**. And a session that **has not changed a single file does not
relay at all** - its successor would start exactly where it did, minus the reading, which is how
a ticket loops all night without being built. `watch.sh` holds the `FAT` event back until the
worktree shows work, and releases it regardless past `<CEILING_USED>`% used, because a session
that full with nothing to show is a ticket that was too big.

At `<RELAY_AT_USED>`% used, the session:

1. commits and pushes what it has - WIP with `SIGNAL: <TAG>-RELAYED` in the body if not green;
   never stashes and never reverts;
2. fills `<WS>/continuation-prompt.md` into `<WS>/prompt-<TAG>c2.txt` - what landed, criteria
   met and not met, real verify output, files changed and next, every decision and dead end,
   and the `NEXT_TAG` to launch when the ticket is finally green;
3. writes `state/<TAG>.summary`, then `state/<TAG>.status` = `RELAYED: <TAG>c2` - **`RELAYED`,
   never `DONE`**: the ticket is still in flight and `DONE` would release the next ticket;
4. `bash <WS>/launch.sh <WS> <TAG>c2`, and launches nothing else.

A session that is one command from green finishes instead of relaying.

## 7. The conductor

Writes no product code. Arms `watch.sh` under a persistent Monitor and reacts: launches the
next tag when one is missed, revives STUCK / DIED / STALLED sessions with
`bash <WS>/revive.sh <WS> <TAG> <cause>` (which resumes the dead conversation before it ever
restarts a ticket, then ABANDONS), nudges filling sessions with
`bash <WS>/remind.sh <WS> <TAG> <used>`, relays them with `bash <WS>/relay.sh <WS> <TAG> <used>`,
fires each review pair, opens the draft PR after T01, launches TEST and then WIZARD, and writes
the morning report with the full session ledger, the follow-ups from `<WS>/state/FOLLOWUPS.md`,
and the paste-ready wizard command from `<WS>/HANDOFF.md`.

It holds itself to the same two rungs as everyone else, measured with
`bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` at EVERY watcher event: at
`<WARN_AT_USED>`% used it stops taking on anything beyond watching, and at `<RELAY_AT_USED>`%
used it flushes `LOG.md` and `/next-prompt`s a fresh conductor. It is the longest-lived session
of the night and the one whose death is most expensive, so it relays first and argues later.
Never merges and never deploys - those are <USER>'s.
