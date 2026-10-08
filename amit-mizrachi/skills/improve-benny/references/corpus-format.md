# Corpus format

The corpus is the regression suite for Benny. Every case `/improve-benny` has worked on lives in
`<skill dir>/corpus/<case-id>/`, and every replay grades against it. `tests/check.sh` enforces
this format; `verify.py`-style gates run it.

## Case id

`acct-<account id>-<symptom slug>`, for example `acct-1530-shared-view-empty`,
`acct-1824-import-confirm-disabled`. A synthetic case with no real account uses
`synth-<symptom slug>`. **Never a person name** - not the customer user, not the CSM, not the
sharer. Ids only: account, user, view-def, session, ticket ids.

**The corpus lives in a public repo.** Keep only what the case needs: no customer-authored text
(view titles, file names, workflow or field names), no ids of people outside the case, no
pronouns for a user id ("the user" or "they").

Folders that start with `_` are not cases (`_benny-sources/` holds copies of the live Benny
skill bodies and references this skill wrote, for review).

## Files - exactly four per case

| File | What | Who writes it |
|---|---|---|
| `case.md` | frontmatter + the case restated | step 6, rewritten when the case is re-run |
| `gold-answer.md` | the investigator's gold answer, curated | step 6, rewritten only with new evidence |
| `rubric.txt` | machine-readable grading items | step 6 |
| `verdicts.jsonl` | append-only grading history | `grade.py record` (step R4); never edited, never truncated |

### `case.md`

```
---
id: acct-1530-shared-view-empty
source: slack C0BBE07EYUE/1791378561.557049
asked_utc: 2026-10-07T...Z
account: 1530
users: [20020, 16441]
other_ids: {view_def: 1786, version: 4189, role: 7785}
bar: pre-sql
---

## Replay message
<the exact text sent to Benny on replay: the opening question with names replaced by ids>

## What Benny did
<tools called and their outcomes, the verdict he gave, from his trace>

## What the humans said was wrong
<one to five lines, ids only>
```

`bar` is the rubric bar the judge applies today: `pre-sql` while Benny has no `run_sql`,
`full` once he has it. Raise it when the blocker is gone; never lower it to make a case pass.

### `gold-answer.md`

The investigator's sections 1-7 (see `investigator-prompt.md`), with this frontmatter added:

```
---
id: <case id>
investigated_utc: <when>
code_sha: <repo>@<short sha>
investigator: opus subagent, run <run dir name>
---
```

Keep section 7 even when it says "Agrees with the brief." Strip anything that names a person.

### `rubric.txt`

One item per line, four fields separated by ` | `:

```
# id | kind | bar | text
verdict-by-design | required | all | Line 1 says by design or permissions (access), not a bug.
role-change-useless | forbidden | all | Says changing the role or a role permission will not help.
```

- `id`: lowercase letters, digits and hyphens; unique in the file.
- `kind`: `required` (the reply must make this claim) or `forbidden` (the reply must not).
- `bar`: `all` (graded at every bar), `pre-sql` (only while the case bar is `pre-sql`) or
  `full` (only once the bar is `full`). Two items for one behaviour at different bars - for
  example the confidence label - each carry their own bar.
- `text`: one testable sentence, checkable from the reply text and the tool-call list alone.
- Lines starting with `#` and blank lines are ignored.

A case passes when every `required` item at its bar passes and no `forbidden` item at its bar
appears.

### `verdicts.jsonl`

One JSON object per line, appended by `scripts/grade.py record` (step R4), oldest first:

```
{"utc": "...", "run": "<run dir name>", "bar": "pre-sql", "benny_session": "cnv_...", "spec_archive": "benny/spec@<ts>", "spec_version": "sv1-...", "tools": ["search_code ok", "logfire_query error"], "items": {"verdict-by-design": "pass", "role-change-useless": "pass"}, "pass": false, "judges": 2, "agreement": "16/16", "reply_words": 132, "split": [], "fails": {"draft-offer": "<judge's one-line reason>"}, "note": "<one line>"}
```

- `items` holds every rubric item in force at `bar`, each `pass` or `fail`. For a `required` item,
  `pass` means the reply makes the claim; for a `forbidden` item, `pass` means it does NOT.
- An item is `pass` only when both judges pass it. `split` lists the items they disagreed on
  (recorded `fail`); `agreement` is items agreed over items graded.
- `pass` is true exactly when every item passes.
- `spec_archive` is the newest `list_spec_archives` key at replay time (the live spec is the
  one written after it); `spec_version` is `shapes.agent.spec_version` from the turn's trace.
- `tools`: `<name> <ok|error|no-result>` per call, in call order.
- `reply_words`: the words of the reply from line 1 up to the Evidence heading (up to the draft
  offer when there is no evidence list), counted by `grade.py`. Benny's limit is under 150; no
  rubric item grades it, so read it from this field.

`utc`, `run`, `bar`, `items` and `pass` are required (`tests/check.sh`); T02-era lines may lack
the rest. A new case starts with an empty file. Never rewrite a line; a regrade appends a new one.

## Replay record - `<RUN>/<case id>/replay.json` (run dir, never committed)

Written in step R3, read by `grade.py prompt` and `grade.py record`:

```
{"case": "<case id>", "utc": "<turn start>", "agent": "benny", "transport": "send_chat_turn",
 "session": "cnv_...", "turn": "trn_...", "trace": "<logfire trace id>", "outcome": "replied",
 "spec_archive": "benny/spec@<ts>", "spec_version": "sv1-...",
 "tools_offered": 20, "tools_dormant": 37,
 "tools": [{"name": "logfire_query", "arg": "<optional short argument>", "outcome": "error", "error": "Logfire authentication failed"}],
 "note": "<one line: dormant tools, anything unusual>", "reply": "<Benny's reply, verbatim>"}
```

Beside it in the same folder: `judge-input.md` (the filled judge prompt), `judge-1.json`,
`judge-2.json` (the judges' answers, format in `judge-prompt.md`).
