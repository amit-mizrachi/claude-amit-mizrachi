---
name: improve-benny
description: Turns one bad answer from Benny (the Machina CS triage agent in Slack) into a lasting fix. From a Slack thread link or a pasted case it builds a verified gold answer with an Opus investigator subagent, finds why Benny could not give it (access, credential, config, skill knowledge, reply style, judgement, budget), saves the case to a regression corpus of ids-only cases, applies the fixes to live Benny (prior copy, archive check, undo ledger), and replays that corpus to live Benny with an Opus judge grading each reply per rubric item. Use when the user says "improve benny", "/improve-benny", "benny answered wrong", "benny did not help here", "teach benny", "why couldn't benny answer this", "replay the benny corpus", "grade benny", "did benny get better", or pastes a CS thread where Benny's answer was wrong, hedged or incomplete.
argument-hint: "<slack-thread-link | pasted case> [--no-apply] [--corpus-only] [--run-dir <path>] [--ledger <path>]"
---

# improve-benny

## Overview

Benny is the Machina agent (`benny`) CS asks before a ticket reaches Dev of the Day. When he
answers badly, this skill finds the answer he should have given, proves every fact in it, names
each reason he could not reach it, and keeps the case as a permanent regression test.

You run in the user's session. **Invoking this skill is the user's permission for its subagent
roles**: the gold-answer investigator and the judge (two per replay), all on Opus
(`model: "opus"`). Use no other subagents.

## Hard rules

- **Never post in Slack.** Read threads only. No reply, reaction, draft or DM, ever.
- **Machina: reads only, unless the apply step runs.** Every Machina call goes into the run log
  as `read`, `turn` (a `send_chat_turn`: Benny answers, nothing in his config changes) or
  `write`. `--no-apply` and `--corpus-only` must end with zero writes, and the run log proves it.
- **Every write is read first, saved, and in the ledger** (`references/apply.md`). No prior copy,
  no write.
- **A replay never joins a human's conversation.** Call `send_chat_turn` WITHOUT `session`: the
  server mints a fresh `cnv_` id per call (it refuses a made-up id anyway). Never `try_agent_turn`
  (60 s cap, too short for Benny) and never a Slack door.
- **Ids only in the corpus.** Account, user, view-def, session ids. Never a person name - not
  the customer user, not the CSM, not the sharer. Strip names from quoted text.
- **The gold answer comes from sources, never from the thread.** Other bots' and humans'
  answers are claims for the investigator to test.
- **Database reads stay safe**: scoped to the case's account; never a credential column
  (password, token, secret, api key, hash); never `SELECT *` on people or user tables.
- **Code is read at `origin/main`** of a freshly fetched clone (`git show origin/main:<path>`),
  never a stale checkout, and cited at its sha.

## Modes

| Invocation | Does |
|---|---|
| `<thread link or pasted case> --no-apply` | steps 1-6 and the report: gold answer, gap report, corpus case. Zero Machina writes |
| `<thread link or pasted case>` | the same, then apply the fixes live (A1-A3), then replay and grade that one case (R1-R4) |
| `--corpus-only` | step 0, then R1-R4 for every corpus case: a graded table, one verdict line per case. Zero Machina writes |

A thread link is `https://<workspace>.slack.com/archives/<channel>/p<ts without the dot>`;
the parent ts is `<first 10 digits>.<rest>`. A pasted case is any text with the question,
Benny's answer and what was wrong; ask for the account id if it is missing.

## Steps

### 0. Run directory and run log

Use `--run-dir` if given, else `~/improve-benny/runs/<utc compact>-<case id>/` (not under
`~/.claude`: Claude Code guards writes there). Never commit a run directory. Start
`<RUN>/run-log.md` with the mode, then append one line per Machina call:
`<utc> | <tool> | <target> | read|turn|write | <one-line result>`.

### 1. Read the case

Slack link: read the whole thread, bot replies included. Restate in the run dir: the opening
question, every Benny reply (verdict, label, what he said he could not check), and what the
humans said was wrong. Collect every id. Pick the case id (`references/corpus-format.md`); if
`corpus/<case id>/` exists, this run updates that case.

### 2. Read Benny live

Do the reads in `references/gap-report.md` ("Read Benny live first") and save each under
`<RUN>/benny-live/`. Then find his turn in Logfire (project `shapes-internal`, service `agent`,
conversation id = the thread ts): which skills he activated, which tools he called, which
errored and with what error class, how many steps he used.

### 3. Gold answer

Fill `references/investigator-prompt.md` and launch it (Agent tool, `model: "opus"`). Give it
the case, the ids, Benny's registered tools and what is missing, and any verified answer the
user already has as a brief to verify, never to copy. Wait for it.

Then check its work before you trust it:
- All seven sections exist, and the reply in section 2 has the shape the prompt asks for.
- Open at least two pointers yourself (a code line with `git show`, a query re-run) and confirm
  they say what the fact says. A pointer that does not resolve is a defect: fix it or drop the
  fact.
- Section 7 disagrees with the brief: keep the evidence, and say so in the report. Do not
  overrule the investigator without a source.

### 4. Gap report

Write `<RUN>/gap-report.md` per `references/gap-report.md`: every gold fact whose Benny-tool
column is `none` or a tool that failed; every rule the skills lack; every reply-style
difference; every unbacked claim Benny made (judgement); steps spent vs `maxToolSteps`.

### 5. Rubric

Turn section 5 of the gold answer into `rubric.txt` (format in `references/corpus-format.md`).
Every wrong claim from the thread that a reader might repeat becomes a `forbidden` item. If a
gap blocks the full answer today (for example no `run_sql`), set the case `bar: pre-sql` and add
the pre-SQL items: the honest label and the escalation tag naming the missing source.

### 6. Save the corpus case

Write `corpus/<case id>/` with the four files in `references/corpus-format.md`
(`verdicts.jsonl` empty for a new case). Grep the folder for every name in the thread before
you finish; none may remain. The corpus is in a public repo, so also: no customer-authored text
(view titles, file names, workflow or field names), no ids of people outside the case, no
pronouns for a user id. Run `bash <skill dir>/tests/check.sh`.

### 7. Report

Tell the user, in this order: the gold verdict and label (and any disagreement with the
brief), the gaps by class with the ones that need a human, the corpus path, and the Machina
calls of the run as `<n> reads, <n> turns, <n> writes`. Without `--no-apply`, go on to A1.

## Apply

Follow `references/apply.md`. In short:

- **A1. Prior copies.** Read every target (spec field, skill body) and save it under
  `<RUN>/benny-live/`. Keep every live rule you do not mean to change.
- **A2. Write** through the Machina MCP only: new skills first (`write_skill_body` `create` with
  `attach_to`), then bodies (`update`), then spec fields (`write_agent_spec` `set-field`).
- **A3. Check and ledger.** After a spec write or attach, `list_spec_archives` must show a new
  key. Log each write in the run log and the ledger (`<RUN>/live-writes.md` or `--ledger`), with
  its prior copy or archive key. Copy new skill bodies and changed instructions to
  `corpus/_benny-sources/`.

Then replay on a fresh session (R1).

## Replay and grade

### R1. Preflight

`check_agent_channels benny` must say `chatTestable: true`; if not, stop and report it.
`list_spec_archives benny`: the newest key is the `spec_archive` of every replay in this run (the
live spec is the one written after it).

### R2. Replay each case

Cases are the folders of `corpus/` that do not start with `_`. For each, one call:
`send_chat_turn` with `agent: "benny"`, `message` = the case's `## Replay message` section
verbatim, no `session`, `timeout_seconds: 300`. Log it as a `turn`.

| Outcome | Do |
|---|---|
| `replied` | go on |
| `awaiting-human` | answer it once with `decision: "deny"`, `note: "replay, no human here"` (same `session`), and grade the reply that follows |
| `timeout`, `withheld`, an error | re-send once; still no reply: the case is `not graded: <outcome>` in the report, and no verdict line |

### R3. The replay record

The turn result names the tools but often says `no-result` for every outcome. Read the truth from
Logfire (project `shapes-internal`), with the turn's `sessionId` as the conversation id:

```sql
-- the turn: trace, spec version, tools offered vs dormant (window: the minute of the replay)
SELECT trace_id, attributes->>'shapes.agent.spec_version', attributes->>'agent.tools.available',
       attributes->>'agent.tools.gap_count', attributes->>'agent.turn.step_cap_hit'
FROM records WHERE span_name = 'invoke_agent benny'
  AND attributes->>'gen_ai.conversation.id' = '<sessionId>'
-- each tool: name, argument and result head
SELECT span_name, otel_status_code, is_exception, left(attributes->>'gen_ai.tool.call.arguments', 200),
       left(attributes->>'gen_ai.tool.call.result', 300)
FROM records WHERE trace_id = '<trace>' AND span_name LIKE 'execute_tool%' ORDER BY start_timestamp
```

A tool's outcome is `error` when its status is `ERROR`, it is an exception, or its result head
is a failure ("Logfire authentication failed", a 401/403, "not found", a refusal); keep that first
line as `error`. Otherwise `ok`. Write `<RUN>/<case id>/replay.json` (format in
`references/corpus-format.md`). When `agent.tools.gap_count` is not 0, say in the record's `note`
which registered tools were dormant: a reply that lacks a source Benny could not reach in this
door is a replay-fidelity gap, not a skill gap.

### R4. Judge, twice, and record

1. `python3 <skill dir>/scripts/grade.py prompt <case dir> <RUN>/<case id>/replay.json > <RUN>/<case id>/judge-input.md`
2. In ONE message, two Agent calls (`model: "opus"`), each: "Read `<RUN>/<case id>/judge-input.md`
   and do exactly what it says. Read no other file and call no other tool. Your final message is
   the single JSON object it asks for." Save the answers as `judge-1.json` and `judge-2.json`. A
   judge that answers anything but that JSON is re-run once.
3. `python3 <skill dir>/scripts/grade.py record <case dir> <RUN>/<case id>/replay.json <RUN>/<case id>/judge-1.json <RUN>/<case id>/judge-2.json --run <run dir name>`
   prints the graded table and appends the verdict line. An item passes only when both judges
   pass it; a `split` item is a rubric item to sharpen, never a coin to flip again.
4. `bash <skill dir>/tests/check.sh`.

Report per case: PASS or FAIL at its bar, the failed items with their one-line reasons, judge
agreement, the tools that errored or were dormant; then the run's Machina calls as
`<n> reads, <n> turns, <n> writes`.

## Red flags - stop

| Thought | Do instead |
|---|---|
| "The other bot already found it, I'll use its answer as gold" | The investigator tests it. Its claims go in section 6 |
| "I'll reply in the thread so the CSM sees the fix" | Never post in Slack |
| "One quick spec fix while I'm reading it" | Not in `--no-apply`. Write it as a proposed fix |
| "I'll skip the prior copy, the spec is archived anyway" | Skill bodies need the copy, and the ledger needs a pointer for every write |
| "The replay still shows the old reply, I'll write again" | The spec is cached up to 60 s and a live session keeps its spec. Replay on a fresh session |
| "The customer's first name makes the case clearer" | Ids only. The corpus is permanent |
| "`SELECT *` from Users is faster" | List the columns. Never a credential column |
| "This pointer is close enough" | It resolves or the fact leaves the table |
| "I'll reuse the thread's session so Benny has the context" | Fresh session per replay. The case's replay message carries the context |
| "The judges split; one more run will settle it" | Record it as `fail` + `split`, and sharpen the item text |
| "This case fails because the rubric is too strict, I'll drop the item" | The rubric changes only with new evidence. Never to make a case pass |
