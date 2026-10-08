---
name: improve-benny
description: Turns one bad answer from Benny (the Machina CS triage agent in Slack) into a lasting fix. From a Slack thread link or a pasted case it builds a verified gold answer with an Opus investigator subagent, finds why Benny could not give it (access, credential, config, skill knowledge, reply style, judgement, budget), and saves the case to a regression corpus of ids-only cases. Use when the user says "improve benny", "/improve-benny", "benny answered wrong", "benny did not help here", "teach benny", "why couldn't benny answer this", or pastes a CS thread where Benny's answer was wrong, hedged or incomplete.
argument-hint: "<slack-thread-link | pasted case> [--no-apply] [--corpus-only] [--run-dir <path>]"
---

# improve-benny

## Overview

Benny is the Machina agent (`benny`) CS asks before a ticket reaches Dev of the Day. When he
answers badly, this skill finds the answer he should have given, proves every fact in it, names
each reason he could not reach it, and keeps the case as a permanent regression test.

You run in the user's session. **Invoking this skill is the user's permission for its subagent
roles**: the gold-answer investigator (and, once built, the judge), both on Opus
(`model: "opus"`). Use no other subagents.

## Hard rules

- **Never post in Slack.** Read threads only. No reply, reaction, draft or DM, ever.
- **Machina: reads only, unless the apply step runs.** Every Machina call goes into the run log
  as `read` or `write`. `--no-apply` must end with zero writes, and the run log proves it.
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
| `<thread link or pasted case>` | the same, then apply, replay and grade. **Not in this version**: run as `--no-apply` and say so |
| `--corpus-only` | replay every corpus case and grade it. **Not in this version**: say so and stop |

A thread link is `https://<workspace>.slack.com/archives/<channel>/p<ts without the dot>`;
the parent ts is `<first 10 digits>.<rest>`. A pasted case is any text with the question,
Benny's answer and what was wrong; ask for the account id if it is missing.

## Steps

### 0. Run directory and run log

Use `--run-dir` if given, else `~/improve-benny/runs/<utc compact>-<case id>/` (not under
`~/.claude`: Claude Code guards writes there). Never commit a run directory. Start
`<RUN>/run-log.md` with the mode, then append one line per Machina call:
`<utc> | <tool> | <target> | read|write | <one-line result>`.

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
you finish; none may remain. Run `bash <skill dir>/tests/check.sh`.

### 7. Report

Tell the user, in this order: the gold verdict and label (and any disagreement with the
brief), the gaps by class with the ones that need a human, the corpus path, and the Machina
calls of the run as `<n> reads, <n> writes`.

## Red flags - stop

| Thought | Do instead |
|---|---|
| "The other bot already found it, I'll use its answer as gold" | The investigator tests it. Its claims go in section 6 |
| "I'll reply in the thread so the CSM sees the fix" | Never post in Slack |
| "One quick spec fix while I'm reading it" | Not in `--no-apply`. Write it as a proposed fix |
| "The customer's first name makes the case clearer" | Ids only. The corpus is permanent |
| "`SELECT *` from Users is faster" | List the columns. Never a credential column |
| "This pointer is close enough" | It resolves or the fact leaves the table |
