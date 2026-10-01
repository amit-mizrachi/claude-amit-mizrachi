# <RESEARCH_TITLE> - research sprint plan

> <USER> approved the brief and is not answering now. Every session decides for itself, cites
> its evidence, commits, hands off. No session asks a question. No session writes to a connector.

## Facts

| | |
|---|---|
| Question | <QUESTION> |
| Decision it informs | <DECISION> |
| Audience | <AUDIENCE> |
| Allowed sources | <SOURCES> - READ ONLY |
| Worktree | `<WORKTREE>` - a local git repo on `<BRANCH>`, no remote, shared by every session |
| Workspace | `<WS>` |
| Verify | `<VERIFY>` - every findings file has its sections and every claim is cited |
| Deliverable | one published artifact, written by `SYNTH` from the findings files |

## 1. Goal

<two or three sentences from spec.md: what the reader will know when this is done>

## 2. Out of scope

<from spec.md, verbatim>

## 3. Tickets (in dependency order - this IS the execution order)

Frozen copies live in `<WS>/tickets/`. Each ticket answers one question into
`findings/<NN>-<slug>.md`.

| Tag | Ticket | Question | Next |
|---|---|---|---|
| T01 | `01-<slug>.md` | <...> | T02 |
| T<NN> | `<NN>-<slug>.md` | <...> | REVIEW-FINAL |
| REVIEW-FINAL | - | re-open the sources, find unsupported claims, contradictions, unanswered questions. Edits nothing | FIX-FINAL |
| FIX-FINAL | - | correct the findings files from the manifest | SYNTH |
| SYNTH | - | build, publish and check the artifact; write `state/ACCEPTANCE.verdict` | - |

## 4. Protocol (identical for every session)

1. Work in `<WORKTREE>` on `<BRANCH>`. Never create a branch or worktree. Never push.
2. `<VERIFY>` must PASS before a commit.
3. The final commit body carries `SIGNAL: <TAG>-DONE` or `SIGNAL: <TAG>-BLOCKED: <reason>`.
4. Write `state/<TAG>.summary` (one line), then `state/<TAG>.next` (your successor, or empty),
   then `state/<TAG>.status` (`DONE` / `BLOCKED: <reason>` / `RELAYED: <TAG>c2`) LAST. Then
   `bash <WS>/advance.sh <WS> <TAG>` exactly once.
5. Connectors are READ ONLY. Never send, post, draft, edit, comment or react. A question only a
   person can answer goes under `## Gaps`.
6. Never invent a source, a URL, a quote or a number.

## 5. CONTEXT RELAY - you manage your own window, and a ticket may take more than one session

Measure with `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>`. The number counts UP.

| Rung | Reading | The session |
|---|---|---|
| Narrow | `<WARN_AT_USED>`% used | starts nothing new: no new line of inquiry, no new source family |
| Hand off | `<RELAY_AT_USED>`% used | consolidates and hands its tag on, per the steps below |

Two exceptions: one step from done, finish. No findings file written yet, do not hand off -
until `<CEILING_USED>`% used, when you hand off anyway and say the question was bigger than
planned.

At `<RELAY_AT_USED>`% used, the session:

1. commits what it has, with `SIGNAL: <TAG>-RELAYED` in the body;
2. fills `<WS>/research-continuation-prompt.md` into `<WS>/prompt-<TAG>c2.txt` - what is
   answered, what is not, the sources already checked, the open leads, the dead ends;
3. writes `state/<TAG>.summary`, then `state/<TAG>.next` = `<TAG>c2`, then
   `state/<TAG>.status` = `RELAYED: <TAG>c2` - never `DONE`;
4. runs `bash <WS>/advance.sh <WS> <TAG>`, and stops.

A review or SYNTH session relays the same way, carrying its manifest or its draft page.

## 6. Acceptance

`DONE` means one session finished. The sprint delivered only if `state/ACCEPTANCE.verdict`
starts with `PASS` - written by `SYNTH` from `research-check.sh --final` - and
`state/ARTIFACT.url` holds a published URL rather than `LOCAL-ONLY`.
