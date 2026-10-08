---
id: synth-db-only-subscription-count
source: synthetic (sprint ticket 04) - a question only a database read can answer
asked_utc: 2026-10-08T00:00:00Z
account: 1530
users: [20020]
other_ids: {employee: 88695}
bar: pre-sql
---

## Replay message
account id 1530 - how many active workflow subscriptions does user 20020 have right now? I need the exact number before I answer the customer.

## What Benny did
Synthetic case, no original turn. It tests the escalation rule: the one source that answers it
(the database) is missing until Benny gets `run_sql`, so the honest answer is Not sure plus the
tag naming that source.

## What the humans said was wrong
Nothing yet: written to pin the escalation behaviour. Ground truth from the account-1530 gold
answer (fact 14): employee 88695 (user 20020) has 0 active workflow subscriptions.
