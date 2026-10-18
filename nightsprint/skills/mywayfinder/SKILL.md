---
name: mywayfinder
description: Wayfinder plus a published chart - the map's blocking graph as an interactive artifact, drawn when the map is charted and updated as the last step of resolving every ticket.
disable-model-invocation: true
---

Read the `wayfinder` skill now and run it exactly as written. It stays the source of truth for the map, the tickets, the fog and the frontier, and nothing here changes any of its rules.

`wayfinder` is a **prerequisite this plugin does not ship** - it is a separate, third-party skill. Find its `SKILL.md` by taking the first of these that exists, and read it from there:

1. `wayfinder` in your available skills list - invoke it directly, no file read needed
2. `~/.claude/skills/wayfinder/SKILL.md`
3. `~/.agents/skills/wayfinder/SKILL.md`

If none of them resolve, stop and tell the user: `mywayfinder` is the chart layer on top of `wayfinder` and has nothing to draw without it. Do not improvise a substitute - a map built from a guessed set of rules is worse than no map, because the tickets it cuts look authoritative.

This skill adds one thing: a **chart**.

The **map** is the effort's record on the issue tracker. The **chart** is the drawing of it - one published artifact page, charted alongside the map and updated as the last step of resolving any ticket. The tracker stays the source of truth. The chart is a convenience view: hand-maintained, it never reads the tracker, and when the two disagree the tracker wins.

## Why the chart exists

The tracker holds blocking but cannot draw it. A human deciding what to pick up next needs to see the shape of the whole effort - what is takeable now, what is waiting on what, and why the frontier is only three tickets wide - on one page, at a glance. That is the entire job. Everything the tracker already renders well, the chart leaves to the tracker.

If an effort's blocking graph is trivial enough to hold in your head, say so and skip the chart. `wayfinder` already refuses to build a map for a journey that fits in one session; the same test applies here.

## What the chart must carry

- **Dependency tiers with drawn connectors.** Cards laid out in columns by depth, with the blocking edges computed and drawn between them (SVG paths measured from the rendered card positions, redrawn on resize and on filter change). Hovering or focusing a card lights its edges and its neighbours and dims the rest - the graph is unreadable at fourteen tickets without it.
- **Filters that cut the way a human chooses work**, not the way a database indexes: frontier, blocked, resolved, needs-a-human, runnable-AFK. Each answers a question someone actually asks - "what can I take right now", "what can I leave running while I sleep", "what is waiting on me personally".
- **A detail panel** holding each ticket's question, its blockers, the gist of its answer once resolved, and what it hands forward. Enough to choose the next ticket without opening the tracker. The ticket holds the full record; the chart links to it and gists it, exactly as the map's Decisions-so-far does.
- **A dated chart log** - one entry per change, newest first - and a **masthead stamp** naming the last ticket the chart was updated after. See "Show staleness" below.
- **The fog and the out-of-scope list**, carried over from the map body so the page is a complete low-resolution view.
- **An upkeep panel on the page itself.** See "Teach the page's own upkeep" below.
- **A footer** carrying the chart's own artifact URL, the source file path, and pointers to the effort's materials.

## Show staleness

The chart is hand-maintained and does not read the tracker, so it will go stale. A stale view that cannot admit it is worse than no view - it is read as current and quietly misleads.

So the chart carries its own staleness signal in two places: the dated log's newest entry, and a masthead stamp naming the last ticket resolved into it. Both are visible without scrolling or clicking. Print the test on the page beside the log: if the newest log entry is older than the newest resolution on the tracker, this chart is stale - go to the tracker.

## Derive everything the ticket array knows

Hand-maintain only what the tracker holds: each ticket's id, title, question, answer gist, status, blockers, type, AFK-or-HITL mode, and link. Derive everything else at runtime from that array - the tallies, the "All N" filter chip, each ticket's tier depth from its blockers, and the reverse "unblocks" edges.

Counts typed into the markup go stale on their own schedule. On 2026-08-11 a background agent republished a chart mid-edit and shipped a masthead reading "12 tickets" while the array held 14. Deriving them makes that class of drift impossible, and it is why the tally row is the one part of the page nobody edits.

## Teach the page's own upkeep

A session may open the chart without ever reading this skill - a fresh agent handed a URL, a background job picking up a ticket. The page has to teach its own maintenance, so it carries an upkeep panel stating: the source file path, the four-step close-out, the derived-counts rule, and both republish gotchas. Write it for a reader who has no other context.

## Where the chart lives

Two locations, both recorded on the map's `## Notes` so any session can find them from the tracker alone:

- **The source file** - `wayfinder-map.html`, in the effort's own working directory, alongside its research pack and materials. Durable, not a scratch or job tmp directory: those are deleted with the job, and the published page would outlive any ability to edit it.
- **The published artifact URL** - also printed in the chart's own footer, so a session that opens the page can find it without the tracker.

## Charting the chart

Added to `wayfinder`'s **Chart the map** mode, after the tickets exist and the blocking edges are wired - the chart needs a graph to draw.

1. Load the `artifact-design` skill before writing any of the page. A strict CSP blocks every external request: no font CDNs, no remote scripts, no remote images. Inline all CSS and JS, use system font stacks, embed any asset as a data URI.
2. **Light mode, always.** A chart is a plotting sheet, and it commits to a single visual world rather than following the reader. So do not build the dual-theme palette `artifact-design` asks for by default - this is the deliberate single-theme case it allows for. Define the tokens once on `:root`, set `color-scheme: light` there, and write no `@media (prefers-color-scheme: dark)` block and no `:root[data-theme="dark"]` override, so neither the viewer's OS preference nor their theme toggle can move the palette. Anything reading a token at runtime, such as an SVG stroke colour pulled from `getComputedStyle`, then stays correct with no theme listener to maintain.
3. Write `wayfinder-map.html` into the effort's working directory.
4. Publish it, and record the returned URL on the map's `## Notes` and in the page's own footer.
5. Open the first chart log entry: the date, "Map charted", and the destination in one line.

## Resolving a ticket

Replaces `wayfinder`'s **Record the resolution** step. Four steps, in this order, in the same session, before the summary is written:

1. Append the answer to the ticket and set its status to resolved.
2. Move anything it unblocked off hold.
3. Gist it into the map's **Decisions so far**.
4. **Update the chart and republish.**

Step 4 is the one that gets dropped, because by then the work feels finished. It is not finished: an effort whose chart lags its tracker by three tickets has a chart nobody trusts, and a chart nobody trusts is deleted. The ticket is closed out when the chart's masthead stamp names it and the republish has returned the same URL it had before.

To update the chart: **re-read the source file first** - several sessions share it, including background agents, so it may have moved since you last looked. Then set the resolved ticket's status, paste its answer gist and what it hands forward into its body, move anything it unblocked from hold to frontier, add ticket cards for anything newly created, promote any fog patch that graduated, and add a chart log entry plus the masthead stamp. Leave the tallies and the "All N" chip alone - they are derived.

## Republishing

Every republish passes `url=` the chart's existing artifact address, the one in its footer. This is the gotcha that costs the most and warns you least: a session that did not itself publish the page will, without `url=`, silently mint a **new** artifact at a **different** address. The link on the tracker then points at a frozen copy while the real work continues somewhere else, and nothing anywhere says so.

On a publish conflict, another session published between your read and your write. Re-read the file, merge your change on top of the newer content, and publish again. Do not force - forcing discards their version.

## Sharing

Published artifacts are **private by default**. Say so when you hand the human the URL, and tell them teammates will need either an explicit share from the artifact page or a plain-text mirror of the map. A URL pasted into a channel on the assumption it is readable is a silent dead end for everyone who clicks it.

## Keep it a view

The chart renders the map. It does not sync with the tracker, poll it, or hold anything the tracker does not. If the chart and the tracker disagree, the tracker is right and the chart is stale. Every pull toward live data - a fetch, an embedded query, a webhook - trades that guarantee for a page that can be wrong in ways nobody can see.
