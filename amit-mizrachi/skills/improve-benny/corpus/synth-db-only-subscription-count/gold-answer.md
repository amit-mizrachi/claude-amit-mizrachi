---
id: synth-db-only-subscription-count
investigated_utc: 2026-10-08
code_sha: shapes-platform@95ad28468a
investigator: main session, run T04-apply; fact from acct-1530-shared-view-empty gold answer fact 14
---

# Gold answer - synth-db-only-subscription-count

## 1. Case restated
The CSM wants the exact count of active workflow subscriptions for user 20020 (employee 88695)
on account 1530. Only a database read answers it; no log, trace or code line holds the count.

## 2. Gold answer (pre-SQL bar: Benny has no database tool)

**Not sure: I cannot count user 20020's workflow subscriptions without database access.**

The CSM needs the exact number of active workflow subscriptions for user 20020.

*Why:* Only the database holds subscriptions. My logs and code tools do not show them.

*Next:*
1. In the app, open each workflow and check whether the user is in "Subscribers".
2. Or ask a developer to count them.

Want me to draft a reply to the customer?
<@U0AJ9T58ZA7> couldn't check: the database (the user's active workflow subscriptions). I have no database access.

## 2b. Gold answer (full bar: Benny has `run_sql`)
**User 20020 has 0 active workflow subscriptions. Confirmed.** All 16 of the employee's
subscription rows are deleted. No tag.

## 3. Fact table
| # | Fact | Source type | Pointer | Benny tool that could reach it |
|---|---|---|---|---|
| 1 | Employee 88695 has 0 active Workflow subscriptions (16 rows, all status 2 = DELETED). | db | `SELECT s."entityType", s.status, count(*) FROM "EmployeeSubscriptions" s WHERE s."accountId" = 1530 AND s."employeeId" = 88695 GROUP BY 1,2`; status constants shapes-platform@95ad28468a:apps/dreamteam-io-server/src/constants.ts:124-127 | none (no run_sql) |
| 2 | "Subscribers" is the on-screen name of a workflow's subscription list. | code | shapes-platform@95ad28468a:apps/dreamteam-io-client/src/translations/en.json:4866 | search_code, read_file |

## 5. Rubric source
See `rubric.txt`. Pre-SQL: label Not sure, a tag naming the database, no invented count.
Full: the count 0 from a database read in the turn, no tag.

## 7. Disagreement with the brief
None: no brief.
