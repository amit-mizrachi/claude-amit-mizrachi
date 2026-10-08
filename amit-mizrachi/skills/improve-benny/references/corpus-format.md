# Corpus format

The corpus is the regression suite for Benny. Every case `/improve-benny` has worked on lives in
`<skill dir>/corpus/<case-id>/`, and every replay grades against it. `tests/check.sh` enforces
this format; `verify.py`-style gates run it.

## Case id

`acct-<account id>-<symptom slug>`, for example `acct-1530-shared-view-empty`,
`acct-1824-import-confirm-disabled`. A synthetic case with no real account uses
`synth-<symptom slug>`. **Never a person name** - not the customer user, not the CSM, not the
sharer. Ids only: account, user, view-def, session, ticket ids.

Folders that start with `_` are not cases (`_benny-sources/` holds copies of the live Benny
skill bodies and references this skill wrote, for review).

## Files - exactly four per case

| File | What | Who writes it |
|---|---|---|
| `case.md` | frontmatter + the case restated | step 6, rewritten when the case is re-run |
| `gold-answer.md` | the investigator's gold answer, curated | step 6, rewritten only with new evidence |
| `rubric.txt` | machine-readable grading items | step 6 |
| `verdicts.jsonl` | append-only grading history | the judge step; never edited, never truncated |

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

One JSON object per line, appended by the judge step, oldest first:

```
{"utc": "...", "run": "<run dir name>", "bar": "pre-sql", "benny_session": "improve-benny-<case>-<utc>", "spec_archive": "<key or null>", "items": {"verdict-by-design": "pass", "role-change-useless": "pass"}, "pass": false, "note": "<one line>"}
```

A new case starts with an empty file. Never rewrite a line; a regrade appends a new one.
