---
id: acct-1530-shared-view-empty
source: slack C0BBE07EYUE/1791378561.557049
asked_utc: 2026-10-07T13:09:21Z
account: 1530
users: [20020, 16441]
other_ids: {view_def: 1786, version: 4189, role: 7785}
bar: pre-sql
---

## Replay message
account id 1530 - user 20020 does not see the data in a shared vibe view (view-def 1786, a workflows view, shared by user 16441). Can you explain why?

## What Benny did
First answer (trace `01a1167b9e353ffd67ab2d06a7d9cb7a`, 2026-10-07T13:09Z, 8 of 16 steps):
activated `vibe-view-debug` and `dod-verdict`; ran `query_logs` x2, `rum_sessions`,
`query_feature_flags` x2, `search_code` x6, `search_slack_history` x2, `search_helpdesk`;
`logfire_query` failed with HTTP 401. Verdict "Likely permissions, by design", with "Couldn't
check: the role and scope, the view's code, Logfire". Next step: "change the role or employee
scope in Account Settings -> Permissions", with no setting named. No draft offer, no
escalation.
In later turns he could not see another bot's reply in the thread (`thread_context: false`);
after the CSM pasted it, his customer draft adopted that bot's fix ("add as a participant" or
"Super Admin") without a source of his own.

## What the humans said was wrong
- The CSM: Benny "does not answer the question in the proper way".
- The engineer who closed the thread: correct behaviour; user 20020 has no permission to see these
  workflows; once the user has it, they will see them.
- Another bot's answer (participation only; "changing the role changes nothing") was wrong and
  reached the customer draft.
