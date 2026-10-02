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

    **Artifact:** <filled in at step 5>
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

    ## Decided for you
    - <choice>: <what you chose> - <why, one clause>

    ## Build outline
    1. <one line per expected ticket, in dependency order; at most 10>

    ## Risks and gaps
    - <at most 5>

    ## Sources
    - [<n>] <as in the findings files>

Option ids are short and stable (A, B, C). The pick text in step 4 uses the same ids, and the build matches on them.

## STEP 3 - DRAW THE UI, FROM THE REAL KIT

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

## STEP 4 - BUILD THE PAGE

ONE self-contained HTML page at <WS>/artifact/index.html, following the `artifact-design` page contract (its dual theme applies to the page; the mockups keep the product's own look). In this order:

1. **Header** - the feature name, at most 4 sentences on what gets built and for whom, and one meta line: repo @ <REPO_SHA>, the date, "autonomous run".
2. **The UI** - the biggest section. One block per screen: the mockup with its state tabs, then a caption with the components. No paragraphs.
3. **Your decisions** - one card per decision from step 1, options side by side. Each option: its id, a title, one line on what it is, at most 3 pros and 3 cons, a cost (S / M / L), its mockup if it has one, a "Recommended" badge on one, and a **Pick this** radio. Under the options: "Why <id>:" in one sentence, and a note box ("Note for the build, optional").
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

## STEP 5 - PUBLISH IT

Publish <WS>/artifact/index.html with the Artifact tool: a short title (the feature name), a one-sentence description, `icon` = `layout`. The page is private to <USER> until they share it.

  echo "<the artifact URL the tool returned>" > <WS>/state/ARTIFACT.url

Then write the same URL into the `**Artifact:**` line of <WS>/plan/PLAN.md.

If the Artifact tool is not available, or the publish is refused, do not retry in a loop and do not work around it:

  echo "LOCAL-ONLY <WS>/artifact/index.html (<why publishing failed>)" > <WS>/state/ARTIFACT.url

## STEP 6 - ACCEPTANCE

  bash <WS>/research-check.sh <WS> --final && test -s <WS>/plan/PLAN.md && grep -q '^## Decisions' <WS>/plan/PLAN.md

Write its verdict, with the URL, to <WS>/state/ACCEPTANCE.verdict:

  echo "PASS <url or LOCAL-ONLY path>" > <WS>/state/ACCEPTANCE.verdict
  echo "FAIL <the FAIL lines, joined>" > <WS>/state/ACCEPTANCE.verdict

On FAIL you get ONE repair pass, then run the check again and write the honest result.

  git -C <WORKTREE> commit --allow-empty -q -m "plan: <TAG>" -m "SIGNAL: <TAG>-DONE"

## CONTEXT

Measure: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` (counts UP) after reading the findings, after each mockup, and after writing the page. If you reach <RELAY_AT_USED>% before publishing, write PLAN.md and every finished mockup to disk first, then relay per the CONTEXT RELAY section of <WS>/PLAN.md, naming the mockups still to draw.

## WHEN DONE - in this order

1. `echo "<published URL or LOCAL-ONLY>, <n> decisions, <n> mockups" > <WS>/state/<TAG>.summary`
2. `: > <WS>/state/<TAG>.next` - nothing follows you in this sprint. The conductor takes it from here.
3. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST.
4. `bash <WS>/advance.sh <WS> <TAG>`

Post a summary as your last message: the artifact URL, each decision with its recommended option, and the biggest risk.
