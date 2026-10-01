Research sprint <SLUG>: SYNTH - the artifact

AUTONOMOUS RESEARCH RUN. <USER> will NOT answer anything now. Never ask a question - make the best call, state it in your summary, keep going. ASCII only, no em/en dashes.

Research: <RESEARCH_TITLE>
The question: <QUESTION>
It informs this decision: <DECISION>
Written for: <AUDIENCE>
Workspace: <WS>. You are tag <TAG>, the last stage of the sprint.

WORK HERE:
  cd <WORKTREE>
Local repo, branch <BRANCH>, no remote. You are the ONLY session touching it.

READ FIRST: <WS>/spec.md, every file in findings/ (already evidence-checked by REVIEW-FINAL), and <WS>/state/FOLLOWUPS.md.

YOU DO NO NEW RESEARCH. You write up what the findings files say. A claim that is not in a findings file does not go in the artifact; a gap stays a gap. Connectors stay READ ONLY.

## STEP 1 - BUILD THE PAGE

Load the `artifact-design` skill first and follow its page contract. Then write ONE self-contained HTML page to:

  <WS>/artifact/index.html

For <AUDIENCE>, in this order:

1. **The answer** - the research question and a direct answer in 3-5 sentences, then what it means for the decision: <DECISION>. Lead with the conclusion, not the method.
2. **Key findings** - grouped by theme, not by ticket. Each carries its confidence (high / medium / low) and its citations.
3. **Where the evidence disagrees** - contradictions and weak spots, stated plainly. Omit the section only if there truly are none.
4. **Gaps and open questions** - what could not be found, and who or where could answer it.
5. **Method** - the sources searched, the date, and that this was produced by an autonomous research run, so a reader weighs it accordingly.
6. **Sources** - one numbered list for the whole page, renumbered from the per-file [S<n>] ids. URLs are links. Connector references stay text (channel, file name, date), since a reader may not have access.

A chart only where it carries a comparison better than a table; if you add one, load the `dataviz` skill first. No external data, no runtime capabilities - a static page.

Never put a secret, a credential, or personal data about a private individual on the page.

## STEP 2 - PUBLISH IT

Publish <WS>/artifact/index.html with the Artifact tool: a short title, a one-sentence description, a generic `icon` such as `search`. The page is private to <USER> until they choose to share it.

  echo "<the artifact URL the tool returned>" > <WS>/state/ARTIFACT.url

If the Artifact tool is not available, or the publish is refused, do not retry in a loop and do not work around it:

  echo "LOCAL-ONLY <WS>/artifact/index.html (<why publishing failed>)" > <WS>/state/ARTIFACT.url

## STEP 3 - ACCEPTANCE

  bash <WS>/research-check.sh <WS> --final

Write its verdict, with the URL, to <WS>/state/ACCEPTANCE.verdict:

  echo "PASS <url or LOCAL-ONLY path>" > <WS>/state/ACCEPTANCE.verdict
  echo "FAIL <the check's FAIL lines, joined>" > <WS>/state/ACCEPTANCE.verdict

On FAIL you get ONE repair pass on the page or a findings file, then run the check again and write the honest result.

Commit the artifact with `SIGNAL: <TAG>-DONE` in the body.

## CONTEXT

Measure: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` (counts UP) after reading the findings and after writing the page. If you reach <RELAY_AT_USED>% before publishing, write the page as it stands to disk first, then relay per the CONTEXT RELAY section of <WS>/PLAN.md.

## WHEN DONE - in this order

1. `echo "<published URL or LOCAL-ONLY, and the one-line answer>" > <WS>/state/<TAG>.summary`
2. `: > <WS>/state/<TAG>.next` - nothing follows you.
3. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST.
4. `bash <WS>/advance.sh <WS> <TAG>`

Post a summary as your last message: the artifact URL, the one-line answer, its confidence, and the biggest gap.
