---
name: vibe-view-debug
label: "Debug a vibe view"
folder: "DoD"
description: "Finds why ONE vibe view (a custom AI-built view, link .../views/vda-<id>) is broken: generation failed or stuck, an edit (refine) did nothing, blank, crashes, or shows wrong or missing data. Ends with the cause, who fixes it (the user with a refinement prompt, or engineering) and a paste-ready refinement prompt. Open it for a vda- link, or when a CSM says a specific vibe view, custom view or AI view is wrong, including a shared view that is empty for one viewer. Not for general questions about what vibe views can do."
---

# Debug a vibe view

A vibe view is a small React app that the vibe agent generated from a customer's prompt. Each "refine" prompt makes a new version. Two worlds - pick the right one first:
| World | Symptom | Truth is in |
|---|---|---|
| Generation (no new version shipped) | "stuck", "failed to generate", "my edit did nothing" | the run's outcome and worker spans (Logfire) |
| Runtime (it shipped but is wrong) | "wrong numbers", "blank", "people missing", "crashes" | the generated code (database or Logfire), GraphQL failures and browser errors (Coralogix) |

A failed refine leaves the OLD version on screen: "my change did nothing" is usually a failed refine.

## Step 0 - Pin and resolve
You need the account id (`customer-identity`), the view number from `vda-<n>`, the symptom and the time. No link: ask the CSM for it once.
- With `run_sql`: resolve the link and read the version chain in the database (`references/database.md`, queries 1-2). You then know the version on screen (`is_current`) and its parents.
- Without it: read the view's runs from Logfire (`references/failure-classes.md`, "Resolve"). You do not know the chain: assume the newest `ready` run is current, and say so.
Always keep the account in the query. No rows for that account: stop and ask the CSM to check the link and the account; never run it again without the account.
For Logfire spans of a version, filter on `shapes.vibe.version_id` = the version id.

## Step 1 - Generation verdict
Newest run `failed`, after the last `ready` one: generation world. Read its `generation done` span and its loud spans (`references/failure-classes.md`). Today almost every failure is `no_output` with `finishReason: stop`: the vibe agent answered in text (often a question) and wrote no file. There is no code to read. Tell the CSM to open the view's chat, answer or rephrase as one concrete change, and send it again.

## Step 2 - Runtime: data and browser
- Coralogix `query_logs` with `account_id`, `tier: "archive"`: `graphql.request.failed` grouped by `normalisedCode` (`investigate-incident`, `references/coralogix.md`). FORBIDDEN: the viewer lacks a permission; a shared view renders with the VIEWER's permissions, by design.
- `rum_events` for the account and window: on `/views/vda-<n>` pages look for `[refineVibeViewDef] mutation failed`, `[useVibeViewVersionPoll] poll error` and `[useVibeViewRenderHtml] fetch error`. Give the `replay_link`.
- **0 rows and no GraphQL error** (the view is empty or rows are missing for this viewer, and no data call failed): this is row scoping, not a broken view. A shared view reads with the viewer's own login and sends the same queries as the product page, so the rows are hidden on that page too. Read `references/who-sees-which-rows.md` with `read_skill_resource` and apply the data area's rule before you look at the view's code. Do not blame a filter, a flag or a bug in the view.
- Other wrong data with no failures: no data call failed, and nothing more. Go to Step 3.

## Step 3 - Runtime: the code
With `run_sql`: list the files of the current version and read ONE file with line numbers (`references/database.md`, queries 3-4). It is the exact shipped code, with no replay and no 30-day limit. "It worked before my change": read the same file at `parentVersionId` and compare. Then go to item 4.
Without `run_sql`, use Logfire:
1. List the edits (path, tool, size, no content) of the current run AND of the older `ready` runs (`references/code-from-logfire.md`). A refine run holds only its own edits.
2. Pick ONE file (usually `data.js`). Read its last `write_file`, then every later `str_replace` on it, in time order. Each `old_str` must appear in the text you rebuilt so far. If one does not, the chain branched: stop and label the reading "Not sure".
3. More than 8 edits, or more than about 40,000 characters: do not rebuild. Say so and name the file and runs for R&D.
4. Read the file for the five recurring bugs (`references/failure-classes.md`). Cite file and line. On "wrong data", read the `review verdict` span first when it exists.
Gate spans are missing on about one run in three, and `render-gate ok: true` does not prove the view shows data: it renders without the viewer's data.

## Step 4 - Deliver: cause, owner, refinement prompt
1. **Cause** - the world, the evidence, the location (file and line, or span name and trace id). Label it Confirmed, Likely or Not sure.
2. **Owner** - the user (fix by refine) or engineering (SDK, worker, gates, io-server, an MCP connection).
3. **Refinement prompt** - only when the user can fix it. One change per prompt; describe the behaviour, not the diff:
```
In <File.jsx>, <what is wrong today, in behaviour terms>.
Please change it so that <the correct behaviour, precisely>.
Specifically:
- <rule 1, including the edge case>
- <rule 2>
Keep the rest of the view unchanged.
```
No refinement prompt for infra errors (502, 504, timed out, s3:PutObject - retry; ticket if it repeats), MCP connection failures, or SDK / bridge / gate bugs. Recommend a DoD ticket (Domain "Vibe views") only for the engineering owner; a view the user can fix by refine is not a DoD. Check `references/recent-changes.md` before you say what vibe views can or cannot do.

## Rules
- PII: generated code can hold hardcoded names; prompts and data-tool results hold employee data. Quote ids, counts, statuses, paths, lines, span names and error classes only. Never select `message` of `vibe.generateVibeViewDef` / `vibe.refineVibeViewDef`, `shapes.prompt`, or whole `attributes`. Never put names or values in a refinement prompt.
- Logfire keeps about 30 days. Older runs cannot be read: say so.
- Logfire answers 401: say "Couldn't check: Logfire (authentication)" and continue with Coralogix.
- Without `run_sql`, say "Couldn't check: database rows (version chain, current version)".
