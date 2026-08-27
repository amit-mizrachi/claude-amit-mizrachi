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
| Review cadence | `<final only | checkpoints after T<NN>, T<NN>, plus final>` - and why |
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
| REVIEW-C1 | - | checkpoint review of T01-T03 | T03 | T04 |
| ... | | | | |
| T<NN> | `<NN>-<slug>.md` | <...> | T<NN-1> | REVIEW-FINAL |
| REVIEW-FINAL | - | quad review + address review of the whole PR | T<NN> | TEST or end |
| TEST | - | <the chosen test mode> | REVIEW-FINAL | end |

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

## 6. The conductor

Writes no product code. Arms `watch.sh` under a persistent Monitor and reacts: launches the
next tag when one is missed, revives STUCK / DIED / STALLED sessions with
`bash <WS>/revive.sh <WS> <TAG> <cause>` (which resumes the dead conversation before it ever
restarts a ticket, then ABANDONS), fires the reviews, opens the draft PR after T01, launches
TEST, and writes the morning report with the full session ledger. Relays to a fresh conductor at 35% remaining
context. Never merges and never deploys - those are <USER>'s.
