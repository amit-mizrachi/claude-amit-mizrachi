---
name: to-tickets
description: Break a plan, spec, or the current conversation into a set of tracer-bullet tickets, each declaring its blocking edges so the set forms a dependency graph that can run in parallel waves, published to the configured tracker (edges as text in one file per ticket locally, or native blocking links on a real tracker). Use when a user or an agent needs a feature, spec or plan split into independently landable tickets in dependency order, for example before a night-sprint.
---

# To Tickets

Break a plan, spec, or conversation into a set of **tickets**: tracer-bullet vertical slices, each declaring the tickets that **block** it.

The issue tracker and triage label vocabulary should have been provided to you (usually in `docs/agents/issue-tracker.md`, written by `/setup-matt-pocock-skills`, which this plugin does not ship). If not, use the **Local files** form in step 5.

An agent may invoke this skill as well as a human. Ask questions only if a human can answer in this session. In a headless or background session, or when the agent that invoked you says it owns the approval gate, skip step 4: use your own judgement on granularity and edges, publish, and return the numbered breakdown, marked **not yet approved by a human**, so the caller can show it to its human.

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes a reference (a spec path, an issue number or URL) as an argument, fetch it and read its full body and comments.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Ticket titles and descriptions should use the project's domain glossary vocabulary, and respect ADRs in the area you're touching.

Look for opportunities to prefactor the code to make the implementation easier. "Make the change easy, then make the easy change."

### 3. Draft vertical slices

Break the work into **tracer bullet** tickets.

<vertical-slice-rules>

- Each slice cuts a narrow but COMPLETE path through every layer (schema, API, UI, tests): vertical, NOT a horizontal slice of one layer
- A completed slice is demoable or verifiable on its own
- Each slice is sized to fit in a single fresh context window
- Any prefactoring should be done first

</vertical-slice-rules>

Give each ticket its **blocking edges**: the other tickets that must complete before it can start. A ticket with no blockers can start immediately.

**The edges are a schedule, not a reading order.** A runner such as night-sprint's blitz mode starts every ticket whose blockers are done at the same time, so the graph decides how much runs in parallel:

- **An edge means "cannot be built until that one has landed"**: it needs that ticket's schema, API, type or file to exist. "Comes later in the story" is not an edge. An edge that only follows the numbering makes a ticket wait for nothing.
- **Cut for width.** Prefer slices that each depend on one shared foundation over a long chain where each needs the one before. A prefactor or a contract (schema, interface, types) that many tickets build on is its own early ticket, and the rest fan out from it.
- **Heavy overlap is an edge too.** Two tickets that would both rewrite the same file or function cannot be merged cleanly when built side by side. Make one block the other, or move the shared change into its own earlier ticket.
- **No cycles.** If A needs B and B needs A, they are one ticket, or a third ticket holds what both need.

**Wide refactors are the exception to vertical slicing.** A **wide refactor** is one mechanical change (rename a column, retype a shared symbol) whose **blast radius** fans across the whole codebase, so a single edit breaks thousands of call sites at once and no vertical slice can land green. Don't force it into a tracer bullet; sequence it as **expand-contract**. First expand: add the new form beside the old so nothing breaks. Then migrate the call sites over in batches sized by blast radius (per package, per directory), each batch its own ticket blocked by the expand, keeping CI green batch to batch because the old form still exists. Finally contract: delete the old form once no caller remains, in a ticket blocked by every migrate batch. When even the batches can't stay green alone, keep the sequence but let them share an integration branch that all block a final integrate-and-verify ticket; green is promised only there.

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each ticket, show:

- **Title**: short descriptive name
- **Blocked by**: which other tickets (if any) must complete first
- **What it delivers**: the end-to-end behaviour this ticket makes work

Then show the **waves**: the tickets that can run together, computed from the edges. Wave 1 is every ticket with no blockers; wave N is every ticket whose blockers are all in earlier waves. For example `Wave 1: 01, 02, 05 - Wave 2: 03, 04 - Wave 3: 06`. A breakdown whose waves hold one ticket each is a chain; say so, and say why it has to be one.

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the blocking edges correct: does each ticket only depend on tickets that genuinely gate it, so the waves are as wide as the work allows?
- Should any tickets be merged or split further?

Iterate until the user approves the breakdown. Skip this step when no human can answer (see above).

### 5. Publish the tickets to the configured tracker

Publish the approved tickets. **How** depends on the tracker `/setup-matt-pocock-skills` configured; the tickets are the same either way, only the shape of the blocking edges changes:

- **Local files** → write one file per ticket under `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01` in dependency order (blockers first). Each file's "Blocked by" lists the numbers/titles it depends on. Use the per-ticket file template below: one ticket per file, never a single combined file.
- **A real issue tracker (GitHub, Linear, …)** → publish one issue per ticket in dependency order (blockers first) so each ticket's blocking edges can reference real identifiers. Use the platform's native blocking / sub-issue relationship where it has one; otherwise set each ticket's "Blocked by" to the blocking issues. Apply the `ready-for-agent` triage label unless instructed otherwise; the tickets are agent-grabbable by construction.

Work the **frontier**: any ticket whose blockers are all done. For a purely linear chain that means top to bottom. Return the waves with the published tickets, so the caller can see at a glance how much can run at once.

Do NOT close or modify any parent issue.

<local-ticket-template>

# <NN>: <Ticket title>

**What to build:** the end-to-end behaviour this ticket makes work, from the user's perspective, not a layer-by-layer implementation list.

**Blocked by:** the two-digit numbers of the tickets that gate this one, comma separated and nothing else on the line (`**Blocked by:** 01, 03`), or `None (can start immediately)`. A runner turns this line into the dependency graph, so keep it to numbers.

**Status:** ready-for-agent

- [ ] Acceptance criterion 1
- [ ] Acceptance criterion 2

</local-ticket-template>

<issue-template>

## Parent

A reference to the parent issue on the tracker (if the source was an existing issue, otherwise omit this section).

## What to build

The end-to-end behaviour this ticket makes work, from the user's perspective, not layer-by-layer implementation.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Blocked by

- A reference to each blocking ticket, or "None (can start immediately)".

</issue-template>

In either form, avoid specific file paths or code snippets: they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it and note briefly that it came from a prototype. Trim to the decision-rich parts, not a working demo, just the important bits.
