---
id: synth-confirmed-workflows-setting-path
investigated_utc: 2026-10-08
code_sha: shapes-platform@95ad28468a
investigator: main session, run T04-apply; facts 7, 9 and 10 of the acct-1530-shared-view-empty gold answer
---

# Gold answer - synth-confirmed-workflows-setting-path

## 1. Case restated
A product question: the screen path and name of the role permission that shows other employees'
workflows, and its side effects. No account, no customer data.

## 2. Gold answer

**Account Settings -> Permissions -> the role -> Apps & Settings -> Workflows -> "Manage employees' workflows". Confirmed.**

An admin sets it per role, and it applies to every user with that role.

*Why:* It is one of two Workflows checkboxes. The app describes it as "View, edit and run workflows for employees".

*Next:*
1. Open Account Settings, then Permissions, and pick the role.
2. On the Apps & Settings tab, open Workflows and turn on "Manage employees' workflows". Side effect: users with the role can also edit and run those workflows. There is no view-only option.
3. For view access only, add the user to "Subscribers" on each workflow.

*Evidence:* the translations file and the Workflows permissions section (links).

Want me to draft a reply to the customer?

## 3. Fact table
| # | Fact | Source type | Pointer | Benny tool that could reach it |
|---|---|---|---|---|
| 1 | Labels: "Account Settings" -> "Permissions" -> tab "Apps & Settings" -> drawer "Workflows" -> checkbox "Manage employees' workflows", description "View, edit and run workflows for employees". | code | shapes-platform@95ad28468a:apps/dreamteam-io-client/src/translations/en.json:162,169,2717-2718,5739,5745 | search_code, read_file |
| 2 | The Workflows drawer has only two checkboxes, so there is no view-only workflows permission. | code | shapes-platform@95ad28468a:apps/dreamteam-io-client/src/components/permissions-view/permission-role-edit-components/admin-permission-role-edit/workflows-permissions-section/workflows-permissions-section-component.js:34-56 | search_code, read_file |
| 3 | The permission key is `manage_employee_workflows`; Super Admin always passes. | code | shapes-platform@95ad28468a:apps/dreamteam-io-server/src/services/permissions/apps/workflows-app-permissions-service.js:14,18-43 | search_code, read_file |

## 5. Rubric source
See `rubric.txt`: the path and setting name, the side effect, the Confirmed label, no tag.

## 7. Disagreement with the brief
None: no brief.
