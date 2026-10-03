night-marathon <SLUG>: <TAG> - the plan artifact

AUTONOMOUS RUN. <USER> will NOT answer anything now. Never ask a question - make the best call, state it in your summary, keep going. ASCII only, no em/en dashes.

Feature: <FEATURE>
Run mode: <MARATHON_MODE> (autonomous = the build starts from your recommendations; review = <USER> picks on your page first)
Workspace: <WS>. You are tag <TAG>, the last stage of the research sprint.
Repo snapshot: <REPO_SNAPSHOT> at <REPO_SHA> - READ ONLY. Never edit, commit or check out anything there.

WORK HERE:
  cd <WORKTREE>
Local repo, branch <BRANCH>, no remote. You are the ONLY session touching it.

READ FIRST: <WS>/BRIEF.md, <WS>/spec.md, every file in findings/ (already evidence-checked by REVIEW-FINAL), and <WS>/state/FOLLOWUPS.md.

You turn the findings into ONE plan and ONE page that shows it. You do no new research for claims: a claim not in a findings file does not go on the page. You DO open the repo snapshot again for visual fidelity - the token files, the components you draw, the screen next to the new one. That is expected, not new research.

The page is for <USER>, who will decide from it in a few minutes. **Short and UI first.** The mockups are the page; prose is the caption.

## STEP 1 - CHOOSE WHAT GOES IN FRONT OF <USER>

List every open choice the findings leave. Then sort each one:

**Put it on the page as a decision ONLY if at least one is true:**
- it changes what a user sees or does;
- it is expensive to reverse: a schema or data migration, a public API or contract, the permission or security model, a new service or dependency;
- the evidence is split and a reasonable engineer could pick either side.

**Everything else you decide yourself** and list in one line under "Decided for you": naming, file layout, which internal helper, library-internal choices, test strategy, anything with an obvious answer.

At most 5 decisions. More than 5 qualify? Merge the related ones, then decide the least consequential yourself. None qualify? Say so on the page - "Nothing needs your call" - and that is a good result.

Each decision gets 2 or 3 options, exactly one marked Recommended. Never pad with a strawman option.

## STEP 2 - WRITE THE PLAN FILE (the build reads THIS, never the HTML)

  <WS>/plan/PLAN.md

    # <feature title> - plan

    **Artifact:** <filled in at step 6>
    **Repo:** <REPO_SNAPSHOT> @ <REPO_SHA>

    ## What we build
    <3-5 sentences: the behaviour, for whom, where it lives>

    ## UI
    ### <screen or component name>
    - Mockup: <WS>/artifact/mockups/<nn>-<name>.html
    - Lives in: <route or parent screen, with the repo path of the nearest existing screen>
    - Components: <Component (variant, size) - import path>, one per line; NEW for anything the repo lacks, with what it is built from
    - States: <default, empty, loading, error, per-role - only the ones that exist>

    ## Decisions
    ### D1 <decision name>
    **Recommended:** <option id>
    - <id>: <option title> - <one line>
    - <id>: <option title> - <one line>
    **Why:** <one sentence>
    **Codex:** <filled in at step 3>

    ## Decided for you
    - <choice>: <what you chose> - <why, one clause>

    ## Build outline
    1. <one line per expected ticket, in dependency order; at most 10>

    ## Risks and gaps
    - <at most 5>

    ## Second opinion
    <filled in at step 3>

    ## Sources
    - [<n>] <as in the findings files>

Option ids are short and stable (A, B, C). The pick text in step 5 uses the same ids, and the build matches on them.

## STEP 3 - A SECOND OPINION FROM CODEX, THEN THE FINAL DECISIONS

A different model reviews the draft before anything is drawn, so the mockups and the page show the final recommendations. This step runs only if the codex-bridge MCP server is connected.

**Is it usable?** Call ToolSearch with the query `codex_status codex_ask`. Use the tools whose names end in `codex-bridge__codex_status`, `codex-bridge__codex_ask`, `codex-bridge__codex_check` and `codex-bridge__codex_cancel` (from this plugin they are `mcp__plugin_amit-mizrachi_codex-bridge__*`). Call `codex_status`. No such tool, or the result does not start with `ready: yes`: write `Skipped - <codex-bridge is not connected | the status result's codex: or login: line>.` under `## Second opinion` and `**Codex:** not consulted` under each decision, and go to STEP 4.

**Ask.** One `codex_ask` call:
- `model`: `gpt-6-astra`, `effort`: `medium`, `sandbox`: `read-only`, `cwd`: `<WS>`, `wait_seconds`: `900`.
- `prompt`, filled in:

      You are reviewing a feature plan before it is built. Feature: <FEATURE>.
      Read <WS>/plan/PLAN.md (the draft plan) and <WS>/BRIEF.md. The evidence is in <WS>/findings/; the code is a read-only snapshot at <REPO_SNAPSHOT>. Open them to check a claim; do not edit anything.
      For EACH decision under "## Decisions", answer in this shape:
        D<n>: pick <option id> | confidence high/medium/low
        Reasoning: <2-4 sentences. Cite the finding or repo:<path>:<line> it rests on.>
      Then:
        Missing decisions: <a choice the plan should put to a human and does not, with why - or "none">
        Decided-for-you to overturn: <an item under "## Decided for you" you would decide differently, with why - or "none">
        Biggest risk: <one, with why>
      Disagree with the draft where the evidence says so. Agreeing everywhere is fine only if you checked. At most 700 words.

The run exits at once with an error that names the model (not supported, not found, no access): this account cannot use `gpt-6-astra`. Ask again ONCE with the same arguments and no `model`, so Codex uses the account's default; the result's `model:` line names it. Any other failure gets no second try.

If the result says the run is still going, call `codex_check` with that `run_id` and `wait_seconds` `900`, once. Still not finished, or the run failed: `codex_cancel` it, write `Skipped - <timeout | the error line>.` under `## Second opinion` and `**Codex:** not consulted` under each decision, and go to STEP 4. Never retry in a loop; the plan is good without it.

**Keep the answer.** Write Codex's answer verbatim to <WS>/plan/CODEX-REVIEW.md, with a header line naming the model, the effort, the session id, and the `codex resume <session_id>` takeover line from the result.

**Decide.** You own the final call; Codex's opinion is evidence, not a vote. For each decision:
- Codex agrees: keep it.
- Codex picks another option: change your recommendation when its reasoning rests on a finding or code you missed or weighed wrong. Open what it cites and confirm it first; a cited fact you could not confirm changes nothing. Keep yours when its reasoning contradicts the findings or rests on an assumption the sources do not support.
- A missing decision Codex names passes STEP 1's filter: add it (still at most 5, merge or decide the least consequential yourself). A decided-for-you item it argues well against: change it, or promote it to a decision if it now passes the filter.

Then fill in PLAN.md:
- Under each decision: `**Codex:** <id> (<confidence>) - <its reasoning, one sentence>`. If your recommendation changed: `**Changed after review:** was <old id> - <why, one clause>`. If you kept yours against Codex: `**Kept over Codex:** <why, one clause>`.
- Under `## Second opinion`: `Codex <the model that answered> (medium effort). Agreed on <n> of <total>; changed <ids or "none">; kept over Codex <ids or "none">. Takeover: <the codex resume line>.` Then its missing-decision and biggest-risk points in one line each, and what you did with them. A risk you accept goes under `## Risks and gaps` too.

## STEP 4 - DRAW THE UI, FROM THE REAL KIT

Load the `artifact-design` skill first. If the feature has no UI at all, skip the mockups: the page's UI section becomes one flow diagram plus the contract (load `artifact-diagramming` for the diagram), and PLAN.md's `## UI` says "No UI".

Otherwise, every mockup obeys these rules. They are what makes the page worth reading, so do not cut them to save time:

1. **Open the source before you draw.** The findings file about the UI kit names the token files, the component packages and the nearest existing screen. Open each one in the snapshot. A mockup drawn from memory of "what a dashboard looks like" is the failure this step exists to prevent.
2. **Real tokens only.** Copy the real values - CSS variables, the theme or Tailwind config, the font stack, radius, spacing, shadows - into a tokens block at the top of each mockup, with a comment naming the file they came from. Never invent a colour or a size. If the product font is on Google Fonts, load it from there; otherwise use the nearest system stack and say so in the caption.
3. **Real components only.** Every element is a component the repo already has, drawn the way its source renders it: its variants, sizes, icon set, focus and disabled states. The caption names each one with its import path, for example `Button (variant=primary, size=sm) - @acme/ui`. Something the repo does not have is tagged **NEW** on the mockup, and the caption says which existing parts it is built from.
4. **In context.** Draw the screen inside its real shell - navigation, header, page container - dimmed, so the reader sees where the new thing lives. Never a component floating on a blank page.
5. **Real-looking data.** Domain-true names, numbers and text lengths, from the findings. No lorem ipsum. Include one long value, so truncation and wrapping are visible.
6. **Every state that exists**: default, empty, loading, error, and any role or permission that changes what is shown. Show them as state tabs over one frame. Skip a state the screen cannot reach.
7. **Narrow width** too, if the product has a mobile or narrow layout in that area.
8. **Options that look different get their own mockup** inside their decision card. Options that look the same get none.

Each mockup is self-contained HTML (inline CSS, no scripts, no remote images), written to

  <WS>/artifact/mockups/<nn>-<name>.html

because the build sprint's implementers use these files as their UI spec. On the page, embed each one in a sandboxed `<iframe srcdoc>` that is sized to its content.

## STEP 5 - BUILD THE PAGE

ONE self-contained HTML page at <WS>/artifact/index.html, following the `artifact-design` page contract (its dual theme applies to the page; the mockups keep the product's own look). In this order:

1. **Header** - the feature name, at most 4 sentences on what gets built and for whom, and one meta line: repo @ <REPO_SHA>, the date, "autonomous run", and "reviewed by Codex <the model that answered>" (or "no second opinion" when STEP 3 skipped).
2. **The UI** - the biggest section. One block per screen: the mockup with its state tabs, then a caption with the components. No paragraphs.
3. **Your decisions** - one card per decision from step 1, options side by side. Each option: its id, a title, one line on what it is, at most 3 pros and 3 cons, a cost (S / M / L), its mockup if it has one, a "Recommended" badge on one, and a **Pick this** radio. Under the options: "Why <id>:" in one sentence; a **Codex** line - its pick and its reasoning in one sentence, marked "agrees", "disagrees - kept <id>" or "changed the recommendation from <id>" (leave the line out when STEP 3 skipped); and a note box ("Note for the build, optional").
4. **Decided for you** - a collapsed `<details>`, one line each. <USER> can still override any of them in a note.
5. **Build outline** - the numbered list from PLAN.md.
6. **Risks and gaps** - at most 5 bullets.
7. **Sources** - a collapsed `<details>`, one numbered list. Cite inline as [n]. Repo sources print as `path:line @sha`; connector sources stay text.

There is no "key findings" section and no method essay. Outside the mockups and the decision cards, keep the prose under about 500 words. If a sentence does not help <USER> pick, cut it.

**The picks bar** - fixed to the bottom of the viewport, always visible:
- "Picks: n of N", updated live.
- **Pick all recommended**, **Copy decisions**, and **Clear** (Clear asks for a second click before it clears).
- Picks and notes are saved per viewer in `localStorage` under `nm-<SLUG>-picks`. Wrap every read and write in try/catch; the page must work when storage throws.
- If the clipboard call fails, show a textarea holding the text, selected, so it can be copied by hand.

**Copy decisions** produces exactly this text, which the conductor parses, so do not change its shape:

    night-marathon picks: <SLUG>
    D1 <decision name>: B - <option title>
      Note: <the note, on one line>
    D2 <decision name>: (not picked - use recommended A)

One line per decision in page order; a `Note:` line only where the note box has text. With no decisions on the page, the button copies `night-marathon picks: <SLUG>` and the line `Build as planned`.

Under the bar's buttons, one line of instruction:
- review mode: "Paste your picks into the conductor session: `claude attach <short id>`". Read the id from <WS>/phases/state/CONDUCTOR.session and use its first 8 characters. Add: "Not found? `claude agents` lists it as ns-<SLUG>-CONDUCTOR."
- autonomous mode: "This run builds the recommended options. Your picks still copy, for a change request on the PR."

A static page: no runtime capabilities, no external data. Never put a secret, a credential, or personal data about a private individual on the page. Keep it under 16MB.

## STEP 6 - PUBLISH IT

Publish <WS>/artifact/index.html with the Artifact tool: a short title (the feature name), a one-sentence description, `icon` = `layout`. The page is private to <USER> until they share it.

  echo "<the artifact URL the tool returned>" > <WS>/state/ARTIFACT.url

Then write the same URL into the `**Artifact:**` line of <WS>/plan/PLAN.md.

If the Artifact tool is not available, or the publish is refused, do not retry in a loop and do not work around it:

  echo "LOCAL-ONLY <WS>/artifact/index.html (<why publishing failed>)" > <WS>/state/ARTIFACT.url

## STEP 7 - ACCEPTANCE

  bash <WS>/research-check.sh <WS> --final && test -s <WS>/plan/PLAN.md && grep -q '^## Decisions' <WS>/plan/PLAN.md

Write its verdict, with the URL, to <WS>/state/ACCEPTANCE.verdict:

  echo "PASS <url or LOCAL-ONLY path>" > <WS>/state/ACCEPTANCE.verdict
  echo "FAIL <the FAIL lines, joined>" > <WS>/state/ACCEPTANCE.verdict

On FAIL you get ONE repair pass, then run the check again and write the honest result.

  git -C <WORKTREE> commit --allow-empty -q -m "plan: <TAG>" -m "SIGNAL: <TAG>-DONE"

## CONTEXT

Measure: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` (counts UP) after reading the findings, after STEP 3, after each mockup, and after writing the page. If you reach <RELAY_AT_USED>% before publishing, write PLAN.md and every finished mockup to disk first, then relay per the CONTEXT RELAY section of <WS>/PLAN.md, naming the mockups still to draw. If <WS>/plan/CODEX-REVIEW.md exists, or `## Second opinion` says Skipped, STEP 3 is done: your successor does not ask Codex again.

## WHEN DONE - in this order

1. `echo "<published URL or LOCAL-ONLY>, <n> decisions, <n> mockups, codex: <agreed n of N | skipped>" > <WS>/state/<TAG>.summary`
2. `: > <WS>/state/<TAG>.next` - nothing follows you in this sprint. The conductor takes it from here.
3. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST.
4. `bash <WS>/advance.sh <WS> <TAG>`

Post a summary as your last message: the artifact URL, each decision with its recommended option and Codex's pick, and the biggest risk.
