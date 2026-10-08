# Who sees which rows

Read this when a page or a shared vibe view shows no rows, or fewer rows than expected, and no request failed.

## The rule for every data area
- Shapes checks access at two points. (1) The request gate: a user without access gets an error (FORBIDDEN). (2) Row scoping: the request passes, and the server sends only the rows this user may see. A user with no permitted rows gets an empty list and NO error.
- So "0 rows and no error" is row scoping until a source shows another cause. It is by design. It is not a bug, a feature flag or a filter in the view.
- A shared vibe view reads data with the VIEWER's own login, not the sharer's. It sends the same queries as the product page. So the same rows are also hidden from this user on the normal product page (for workflows: the Workflows page). Tell the CSM this.
- Shared views always read with the viewer's login. Never give a start date for this. The date of a view version is not the date of a product change.
- A role change DOES help when the role gets the setting that the data area's rule names. Never say that a role change will not help.
- An empty text inside a vibe view (for example "No workflows match the selected filters") is the view's own text. When the cause is access, say that this text is misleading.

## How to check it
1. Logs (`investigate-incident`): no `graphql.request.failed` for this user in the window. A FORBIDDEN row is the request gate, not row scoping.
2. Browser (`rum_events`): the view's data calls returned 200.
3. The data area's rule below: which path would give this user the rows.
4. The database: the role's permissions and the user's subscriptions. This needs `run_sql`. Without it, the label is at most Likely, and the escalation line names "the database (the role's permissions and the user's subscriptions)".

## Workflows (running workflows, as on the Workflows page)
Code (io-server, shapes-platform at a pinned sha): [the permitted assignments](https://github.com/dreamteamapp/shapes-platform/blob/62e0342064536f0ad5c1daf4e75e4097789b030c/apps/dreamteam-io-server/src/services/permissions/workflow-employee-assignment/index.js#L54-L114), [the permitted workflows](https://github.com/dreamteamapp/shapes-platform/blob/62e0342064536f0ad5c1daf4e75e4097789b030c/apps/dreamteam-io-server/src/services/permissions/workflow/index.js#L52-L97), [the Workflows app permission](https://github.com/dreamteamapp/shapes-platform/blob/62e0342064536f0ad5c1daf4e75e4097789b030c/apps/dreamteam-io-server/src/services/permissions/apps/workflows-app-permissions-service.js#L12-L43), [the on-screen names](https://github.com/dreamteamapp/shapes-platform/blob/62e0342064536f0ad5c1daf4e75e4097789b030c/apps/dreamteam-io-client/src/translations/en.json#L2717-L2720), [the shared view sends the viewer's login](https://github.com/dreamteamapp/shapes-platform/blob/62e0342064536f0ad5c1daf4e75e4097789b030c/apps/dreamteam-io-client/src/features/vibe/hooks/use-host-bridge.ts#L250-L253).

A user sees a running workflow when ONE of these is true:
1. The user is a Super Admin. The user sees all workflows.
2. The user's role has "Manage employees' workflows", and the workflow's employee is in the employees the user manages. Where: Account Settings -> Permissions -> the user's role -> Apps & Settings -> Workflows -> "Manage employees' workflows". Side effect: the user can also edit and run these workflows (the app says "View, edit and run workflows for employees"). There is no view-only workflow permission.
3. The user is in "Subscribers" on the workflow, and the workflow's employee is in the employees the user can view. This is the view-only way. It is set on each workflow, one at a time.

These do NOT give access: being the workflow's employee, a participant or the assignee of a task in it. "Manage workflow templates" gives templates only, not running workflows.

The fix to give the CSM: path 2 with its side effect, or path 3 when the user must only view. Super Admin also works, but it opens all of the account; do not give it as the fix.

## Other data areas
Not mapped yet. Find the area's permission service in io-server (`apps/dreamteam-io-server/src/services/permissions/`) with `search_code`, read the function that builds the permitted ids, and cite its line. Give the on-screen setting name from `apps/dreamteam-io-client/src/translations/en.json`, not from `packages/audit-shared`.

## The reply for this case
Keep the reply shape and the word limit. One short sentence for each point:
- Line 1: "By design: user <id> has no access to these <rows>. Likely." Confirmed only after a database read of the role and the subscriptions.
- Why: the view reads with the viewer's login; the server sends an empty list with no error; the same rows are hidden on the product page too.
- Next: at most two steps. (1) The setting by its full path, with its side effect in the same step: "the user can also edit and run these workflows; there is no view-only workflow permission". (2) The view-only way.
- Evidence: only sources you queried in this turn. The code links above are this reference's sources, not yours: before you cite the rule, read it with `read_file` (repo `dreamteamapp/shapes-platform`, path `apps/dreamteam-io-server/src/services/permissions/workflow-employee-assignment/index.js`) and cite that file.
- Without the database, the last line: "<@U0AJ9T58ZA7> couldn't check: the database (the role's permissions and the user's subscriptions). I have no database access."
