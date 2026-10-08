---
id: acct-1530-shared-view-empty
investigated_utc: 2026-10-08
code_sha: shapes-platform@95ad28468a
investigator: opus subagent, run T02-acct-1530-shared-view-empty
curation: section 2 step 3 ("do not use Manage workflow templates") dropped for length; step 4 (misleading empty-state text) added from section 6 claim 7. Facts 12-14 and the code pointers of facts 1, 6 and 9 were re-checked by the main session.
---

# Gold answer - acct-1530-shared-view-empty

Code sha: shapes-platform@95ad28468a (origin/main, committed 2026-10-08 10:02:57 +0300). All code pointers below are at this sha.
Question time: Slack ts 1791378561.557049 = 2026-10-07T13:09:21Z, channel C0BBE07EYUE.

## 1. Case restated

- Question: account 1530, viewer user 20020 (employee 88695) does not see the data in a shared vibe view. Why?
- The view: view-def 1786, kind vibe, link type workflows, current version 4189, shared by user 16441 (Super Admin, employee 85960).
- What Benny said: "Likely permissions, by design. I can't confirm the role." He said a shared view runs with the viewer's permissions "since 3 Aug". He told the CSM to change the role or employee scope "in Account Settings -> Permissions" without a setting name. He could not check the role, the scope, the view code, or Logfire (his `logfire_query` call failed to authenticate). Later he could not see another bot's reply in the thread, asked the CSM to paste it, and then drafted a customer reply that repeated that bot's fix ("add the user as a participant, or make the user Super Admin; changing the role will not help").
- What the humans said was wrong: the CSM said Benny "does not answer the question in the proper way". The closing human said: "This is the correct behavior. The user has no permissions to see these workflows. Once [the user] has permissions [they] will be able to see them."

## 2. Gold answer (Benny's reply shape)

**By design: user 20020 has no access to these workflows. Confirmed.**

User 20020 opens the shared view and sees 0 workflows, because the view reads data with the user's own login.

*Why:* The user's role (7785) has no Workflows permission. The user is not a subscriber on any workflow. So Shapes sends the user an empty list, with no error, also on the Workflows page.

*Next:*
1. Account Settings -> Permissions -> the user's role -> Apps & Settings -> Workflows: turn on "Manage employees' workflows". Side effect: the user can also edit and run workflows for all employees in their scope. No view-only option.
2. View-only: add the user to "Subscribers" on each workflow (46 workflows, one at a time).
3. The user's role hides field 132859, so that column can stay empty.
4. The text "No workflows match the selected filters" misleads: the cause is access. It is in this view's own code.

*Evidence:*
- Code: the view sends the viewer's own login token (shapes-platform@95ad28468a apps/dreamteam-io-client/src/features/vibe/hooks/use-host-bridge.ts:251-253).
- Code: a non-Super-Admin sees a workflow only through a subscription or "Manage employees' workflows" (apps/dreamteam-io-server/src/services/permissions/workflow-employee-assignment/index.js:54-114).
- Database: role 7785 has only a Time Management app permission; one user has it.
- Database: user 20020 has 0 active workflow subscriptions.
- Logs: 0 failed API requests for user 20020, 2026-10-04 to 2026-10-07.
- Browser: the user opened the view on 2026-10-05; its API calls returned 200.

Want me to draft a reply to the customer?

## 3. Fact table

All SQL is read-only on the EU replica. All log windows are UTC.

| # | Fact | Source type | Pointer | Benny tool that could reach it |
|---|------|-------------|---------|-------------------------------|
| 1 | The vibe view host in the web app gives the view the logged-in viewer's own access token; the transport attaches it as the bearer token. No sharer token exists in this path. | code | shapes-platform@95ad28468a:apps/dreamteam-io-client/src/features/vibe/hooks/use-host-bridge.ts:251-253; apps/dreamteam-io-client/src/features/vibe/hooks/apollo-fetch.ts:15-16,29-30 | search_code, read_file |
| 2 | The vibe SDK reads workflows and assignments through the io-server GraphQL queries `workflows` and `workflowEmployeeAssignments`. | code | shapes-platform@95ad28468a:apps/shapes-vibe/packages/bridge-apollo/src/ops/workflows.ts:117-118 and :245-249 | search_code, read_file |
| 3 | The normal Workflows page uses the same two queries. | code | shapes-platform@95ad28468a:apps/dreamteam-io-client/src/redux/state/entities/workflows/actions/fetch-workflows-entities/fetch-workflows-entities.js:12; apps/dreamteam-io-client/src/redux/state/entities/workflow-employee-assignments/actions/fetch-workflow-employee-assignments-entities/fetch-workflow-employee-assignments-entities.js:22 | search_code, read_file |
| 4 | The `workflows` query gate is "employee and above", so any logged-in user passes; rows are then filtered, never refused. | code | shapes-platform@95ad28468a:apps/dreamteam-io-server/src/graphql/permissions/workflow.js:13; apps/dreamteam-io-server/src/graphql/resolvers/workflow.js:3-4; apps/dreamteam-io-server/src/graphql/data-sources/workflows-api.js:28-44 | search_code, read_file |
| 5 | For a non-Super-Admin, running (non-template) workflows are limited to the permitted assignment ids; Super Admin is unrestricted. | code | shapes-platform@95ad28468a:apps/dreamteam-io-server/src/services/permissions/workflow/index.js:52-97 | search_code, read_file |
| 6 | Permitted assignments = (a) workflows the user subscribes to, whose employee the user can view, OR (b) if the user's role has `manage_employee_workflows`, assignments of employees in the user's manage scope. Being the workflow's own employee (subject) is not a path. | code | shapes-platform@95ad28468a:apps/dreamteam-io-server/src/services/permissions/workflow-employee-assignment/index.js:54-114 (subscriptions 64-86, manage permission 88-105) | search_code, read_file |
| 7 | `manage_employee_workflows` is the Workflows app permission key; Super Admin always passes. | code | shapes-platform@95ad28468a:apps/dreamteam-io-server/src/services/permissions/apps/workflows-app-permissions-service.js:14,18-43 | search_code, read_file |
| 8 | "Manage workflow templates" (manage_settings) adds only templates, not running workflows. | code | shapes-platform@95ad28468a:apps/dreamteam-io-server/src/services/permissions/workflow/index.js:75-88 | search_code, read_file |
| 9 | On-screen labels: "Account Settings" (en.json:162) -> "Permissions" (en.json:169) -> role -> tab "Apps & Settings" (en.json:5745) -> drawer "Workflows" (en.json:5739) -> checkbox "Manage employees' workflows", description "View, edit and run workflows for employees" (en.json:2717-2718); other checkbox "Manage workflow templates" (en.json:2719-2720). | code | shapes-platform@95ad28468a:apps/dreamteam-io-client/src/translations/en.json:162,169,2717-2720,5739,5745 | search_code, read_file |
| 10 | The Workflows drawer has only two checkboxes, so there is no view-only workflows permission. The drawer sits in the "Settings" group of the Apps & Settings tab. | code | shapes-platform@95ad28468a:apps/dreamteam-io-client/src/components/permissions-view/permission-role-edit-components/admin-permission-role-edit/workflows-permissions-section/workflows-permissions-section-component.js:34-56; .../apps-and-settings-tab/apps-and-settings-tab-component.js:104-126; .../admin-permission-role-edit-component.js:203-207 | search_code, read_file |
| 11 | Per-workflow "Subscribers" is the on-screen name of the subscription list, shown in the workflow header. | code | shapes-platform@95ad28468a:apps/dreamteam-io-client/src/translations/en.json:4866; apps/dreamteam-io-client/src/components/workflow-header/workflow-header-component.js:13,126 | search_code, read_file |
| 12 | User 20020: active, employee 88695, role 7785, roleType admin; role 7785 has no Workflows app permission. Sharer 16441: role 7499, super_admin. | db | `SELECT u.id, u.status, u."accountId", u."employeeId", u."permissionRoleId", r."roleType", r.status, r.permissions::text FROM "Users" u LEFT JOIN "PermissionRoles" r ON r.id = u."permissionRoleId" AND r."accountId" = 1530 WHERE u."accountId" = 1530 AND u.id IN (20020, 16441)` | none (no run_sql) |
| 13 | Role 7785 is used by exactly 1 user (active). | db | `SELECT count(*) FROM "Users" u WHERE u."accountId" = 1530 AND u."permissionRoleId" = 7785` (also with `AND u.status = 1`) | none (no run_sql) |
| 14 | Employee 88695 has 0 active Workflow subscriptions (16 rows, all status 2 = DELETED; status values at constants.ts:124-127). | db | `SELECT s."entityType", s.status, count(*) FROM "EmployeeSubscriptions" s WHERE s."accountId" = 1530 AND s."employeeId" = 88695 GROUP BY 1,2`; status constants shapes-platform@95ad28468a:apps/dreamteam-io-server/src/constants.ts:124-127 | none (no run_sql) |
| 15 | Workflows of type 7338: 46 active running workflows, 4 active templates, 33 deleted running, 3 deleted templates (86 rows in total). | db | `SELECT t.id, t.status, w."isTemplate", w.status, count(*) FROM "Workflows" w JOIN "WorkflowTypes" t ON t.id = w."workflowTypeId" AND t."accountId" = 1530 WHERE w."accountId" = 1530 AND t.context = 'salary_adjustment' GROUP BY 1,2,3,4` | none (no run_sql) |
| 16 | Their assignments: 46 active (on active workflows), 33 deleted; employee 88695 is subject of 0; employee 85960 (sharer) is subject of 1 active. | db | `SELECT a.status, w.status, count(*), count(*) FILTER (WHERE a."employeeId" = 88695), count(*) FILTER (WHERE a."employeeId" = 85960) FROM "WorkflowEmployeeAssignments" a JOIN "Workflows" w ON w.id = a."workflowId" AND w."accountId" = 1530 JOIN "WorkflowTypes" t ON t.id = w."workflowTypeId" AND t."accountId" = 1530 WHERE a."accountId" = 1530 AND t.context = 'salary_adjustment' GROUP BY 1,2` | none (no run_sql) |
| 17 | View-def 1786: active, kind vibe, link type workflows, current version 4189; version 4189 is ready, made by user 16441 on 2026-08-03T11:54:07Z. | db | `SELECT d.id, d.status, d.kind, d."linkType", d.settings->>'currentVersionId' FROM "ViewDefs" d WHERE d."accountId" = 1530 AND d.id = 1786`; `SELECT v.id, v."userId", v.status, v."generationStatus", v."createdAt" FROM "VibeViewVersions" v WHERE v."accountId" = 1530 AND v."viewDefId" = 1786 ORDER BY v.id DESC LIMIT 5` | none (no run_sql) |
| 18 | The view is shared with employee 88695 by an active grant (318, granted by 16441 on 2026-08-23). | db | `SELECT g.id, g.status, g."targetType", g."targetData"::text, g."grantedBy", g."createdAt" FROM "ViewDefGrants" g WHERE g."accountId" = 1530 AND g."viewDefId" = 1786` | none (no run_sql) |
| 19 | In version 4189, data.js is written once (message idx 94) and never edited after; its data calls are at lines 62-67: two workflow lists (context salary_adjustment; type 7496), workflow assignments, employees, and field values for 118977 and 132859. Client-side filters are by workflow name only (lines 90, 107). | db | `SELECT l.n, l.line FROM "VibeViewMessages" m, jsonb_array_elements(m.blocks) b, regexp_split_to_table(b->'payload'->'input'->>'content', E'\n') WITH ORDINALITY AS l(line, n) WHERE m."accountId" = 1530 AND m."viewDefId" = 1786 AND m.id = 45583 AND b->>'type' = 'TOOL_CALL' AND (l.line ~ 'shapes\.' OR l.line ~* 'filter')`; edit list: same table, `m."versionId" = 4189`, tool name and path per TOOL_CALL | none (no run_sql) |
| 20 | The empty-state text "No workflows match the selected filters." is in the view's own code (the view's main file, line 554, written in version 3651, message idx 47); no later edit removes it. | db | `SELECT m.idx, m."versionId", b->'payload'->>'toolName', b->'payload'->'input'->>'path' FROM "VibeViewMessages" m, jsonb_array_elements(m.blocks) b WHERE m."accountId" = 1530 AND m."viewDefId" = 1786 AND b->>'type' = 'TOOL_CALL' AND (b->'payload'->'input')::text LIKE '%No workflows match%'` | none (no run_sql) |
| 21 | Role 7785 sets field 118977 to level 2 (VIEW) and field 132859 to level 1 (HIDE) at the "others" level. | db + code | Row from fact 12 (`permissions.others.employee_field_types`); levels at shapes-platform@95ad28468a:apps/dreamteam-io-server/src/constants.ts:983-986 | none (no run_sql) |
| 22 | 0 `graphql.request.failed` log rows for user 20020; 143 rows for account 1530 (other users). | log | Coralogix: `source logs \| filter $d.msg == 'graphql.request.failed' && $d['shapes.account.id']:string == '1530' \| aggregate count() as account_rows, count_if($d['shapes.user.id']:string == '20020') as viewer_rows`, window 2026-10-04T13:09:21Z to 2026-10-07T13:09:21Z | query_logs |
| 23 | The user's runtime manage scope is "All employees": manage-filter resolution ran 309 times with specific-group mode false and 0 custom filters. | log | Coralogix: `source logs \| filter $d['shapes.account.id']:string == '1530' && $d['shapes.user.id']:string == '20020' && $d.msg == 'enriched-user.match-filters.custom-filters-resolved' \| groupby $d.attrs.isSpecificGroupMode:string, $d.attrs.customFiltersCount:string aggregate count()`, same window | query_logs |
| 24 | The user opened the view (page workflows/1786) on 2026-10-05T08:08:50Z; its API calls returned status 200 (3) and 0 (1, an aborted request); no error event. | rum | Coralogix: `source rum.events \| filter $d.session_context.account_id:string == '1530' && $d.session_context.user_id:string == '20020' && $d.page_context.page_url:string ~ '1786' \| choose $d.event_context.type, $d.network_request_context.status_code, $d.network_request_context.url`, window 2026-10-05T08:00:00Z to 08:20:00Z | rum_events |
| 25 | Benny's `logfire_query` call in this thread returned the error "Logfire authentication failed - check LOGFIRE_READ_TOKEN" (no exception flag). | trace | Logfire project shapes-internal: `SELECT span_id, attributes->>'gen_ai.tool.call.result' FROM records WHERE trace_id = '01a1167b9e353ffd67ab2d06a7d9cb7a' AND span_name = 'execute_tool logfire.logfire_query'`, window 2026-10-07T13:09:00Z to 13:11:00Z | logfire_query (auth failed) |
| 26 | The thread: the other bot's reply and the closing human verdict ("correct behavior ... no permissions"). | slack | slack_read_thread C0BBE07EYUE / 1791378561.557049 | none (thread_context false) |

## 4. Customer draft

Hi, thank you for your patience, and sorry for the confusion.

We checked this, and the view works as designed. A shared view shows each person only the data that their own permissions allow. User 20020's permission role does not include access to workflows, so the view is empty for them. They would see the same empty list on the Workflows page.

You can give the user access in one of two ways:
1. Account Settings -> Permissions -> the user's role -> Apps & Settings -> Workflows -> turn on "Manage employees' workflows". Please note: this also lets the user edit and run workflows for the employees they manage (today, all employees). There is no view-only option. No other user has this role.
2. If the user should only view them, add the user to "Subscribers" on each workflow they need to see. This is done one workflow at a time.

One more note: the user's role hides one of the two date fields this view shows, so that column may stay empty for them.

Please let us know if you want help with this.

## 5. Rubric (draft)

Required claims:
- R1: States the cause is the viewer's permissions (by design, not a bug).
- R2: Uses the label "Confirmed".
- R3: Says the view reads data with the viewer's own login / permissions, not the sharer's.
- R4: Says the user's role has no Workflows permission (or names role 7785 with no Workflows permission).
- R5: Says the user is not a subscriber on any of these workflows (or has 0 subscriptions).
- R6: Says there is no error: the server returns an empty list.
- R7: Names the path Account Settings -> Permissions -> role -> Apps & Settings (or "Workflows" section) -> "Manage employees' workflows".
- R8: States the side effect of that setting: it also allows edit and run (no view-only option).
- R9: Offers the view-only alternative: add the user as a subscriber on each workflow, with the per-workflow effort.
- R10: Ends with "Want me to draft a reply to the customer?"

Forbidden claims:
- F1: "Changing the role / permission will not help" (it does: fact 6, fact 12).
- F2: "Add the user as the workflow's participant / subject / assignee" as the fix (being the subject gives no access: fact 6).
- F3: "Role 7785 already grants access" to the workflows or to all compensation fields.
- F4: Labels "Likely" or "Not sure", or "I can't confirm the role".
- F5: Claims an error, a bug, a feature-flag cause, or proposes a bug ticket for the data being empty.
- F6: "The sharer sees all 86 workflows" (86 counts deleted rows and templates; 46 are open).
- F7: "Since 3 Aug" as the date of the viewer-login behavior.
- F8: Asks the CSM to paste another bot's reply, or repeats another bot's fix without checking it.

Expected confidence label: Confirmed.
Escalation tag expected: No (by-design permission case; no developer action needed).

## 6. Claims in the thread, checked

| Claim | Who made it | Verdict | Evidence |
|-------|-------------|---------|----------|
| 1. A shared vibe view reads data with the viewer's login, not the sharer's (since 3 Aug). | Benny | true (the "since 3 Aug" date is unproven) | Fact 1 (use-host-bridge.ts:251-253, apollo-fetch.ts:15-16,29-30). The vibe transport file exists since 2026-05-27 (`git log origin/main -- apps/dreamteam-io-client/src/features/vibe/hooks/apollo-fetch.ts`). 2026-08-03 is the creation date of view version 4189 (fact 17), not a change to the login model. |
| 2. `Query.workflows` is scoped by participation: subject or subscriber, or can manage that subject; super_admin sees all; a non-participant gets an empty array, never FORBIDDEN. | Sherlock bot | false in part | "Subject" is not a path: the only paths are subscription (with the employee in the user's view scope) and the Workflows permission "Manage employees' workflows" (fact 6, index.js:54-114). Super Admin sees all: true (fact 5). Empty array, no FORBIDDEN: true (fact 4, facts 22 and 24). |
| 3. "Changing the permission role changes nothing here. Role 7785 already grants compensation-field access." Fix = add the user as a participant, or make the user super_admin. | Sherlock bot | false | Turning on "Manage employees' workflows" on role 7785 adds the manage clause (fact 6, lines 88-105); the user's runtime manage scope is all employees (fact 23), so they would see all 46. Role 7785 has no Workflows key (fact 12). Field 132859 is HIDE in the role (fact 21). Adding the user as the workflow's employee gives no access (fact 6); adding the user as a subscriber does. Super Admin works (fact 5) but is far wider. |
| 4. 86 salary_adjustment workflows (type 7338), 79 assignments; sharer 1 assignment; viewer 0. | Sherlock bot | true as raw row counts, misleading | 86 = 46 active running + 4 active templates + 36 deleted rows (fact 15). 79 = 46 active + 33 deleted assignments (fact 16). Sharer subject of 1, viewer 0: true (fact 16). "Sharer sees all 86" is false: deleted rows are not live, and the view asks only for running workflows (fact 19). |
| 5. data.js:48-50 calls `workflows.list({workflowTypeContexts:["salary_adjustment"]})` and `workflows.assignments.list()`; the only client-side filter is by name. | Sherlock bot | false in part | The calls are at data.js:62-67 in version 4189 and there are six: two workflow lists (salary_adjustment context and type 7496), assignments, employees, field values 118977 and 132859 (fact 19). Name-only client filters: true (lines 90, 107). |
| 6. 0 `graphql.request.failed` rows for account 1530 in Coralogix in a 72h window. | Sherlock bot | false | 143 rows for account 1530 in the 72h before the question; 0 for user 20020 (fact 22). The conclusion "no error for the viewer" still holds. |
| 7. The empty-state text "No workflows match the selected filters" is misleading when the cause is access. | Sherlock bot | true | The text is in the view's own generated code (the view's main file, line 554, fact 20), shown when the server returns an empty list (facts 4-6). It is view content, not product copy. |

## 7. Where you disagree with the brief

The brief is right on the verdict, the label and the main fix. These parts differ:

1. "It calls the same two io-server queries": the view makes six data calls (data.js:62-67, fact 19). The workflow ones do use the same two queries as the Workflows page (facts 2-3), so the conclusion stands.
2. "Two custom employee date fields (118977, 132859), which the role can already read": the stored role sets 118977 to VIEW but 132859 to HIDE (fact 21, constants.ts:983-986). After the fix, the 132859 column can stay empty for the user. Unproven: whether a higher level applies at runtime through the manage-scope field levels (the stored role row has no manage-scope block, but the logs show one at runtime, fact 23).
3. "(a) the user is subscribed to it": the subscription path also needs the workflow's employee to be inside the employees the user can view (workflow-employee-assignment/index.js:82-84).
4. "The user has 0 workflow subscriptions": 0 active. The user had 16, all removed (status 2), the last on 2026-06-01, all on now-deleted workflows or templates (fact 14).
5. Fix path: add the "Apps & Settings" tab between the role and the Workflows drawer (fact 9-10). The user's runtime manage scope is "All employees" (fact 23), so the side effect is wide: the user can edit and run every employee's workflows.
6. "Secondary defect: the empty-state text": the text is written by the view generator in this view's own code (fact 20), not by product copy. The product owner in the thread said no more work goes into the old Workflows app. So it is not a product ticket; the sharer can ask the view to change the text.

Unproven (no resolving pointer, kept out of the table):
- Whether the subject employee of a workflow is auto-added as a subscriber when a workflow starts (would make "subject" an indirect path). Not checked in code.
- Whether adding a subscriber sends notifications to that subscriber.
