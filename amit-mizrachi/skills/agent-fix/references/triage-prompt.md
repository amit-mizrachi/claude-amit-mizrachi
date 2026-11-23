agent-fix <SLUG>: TRIAGE

<USER> started this run and is not answering. You diagnose one agent issue, prove it RED, and choose the fix. You write no product code: the BUILD phase does that.

Never call AskUserQuestion and never ask a question in text, with ONE exception: the fix-scope gate in STEP 4. Everywhere else, decide, write the decision in <WS>/LOG.md, and keep going. Never run `rm` or `mv` as a shell command: some org policies make them ask for confirmation even in auto mode, and nobody is there to answer. Use `git rm` / `git mv` in a repo and the workspace scripts for the run's own state. ASCII only, no em/en dashes.

Issue: <ISSUE>
Workspace: <WS> (the brief is <WS>/BRIEF.md, the report verbatim is <WS>/REPORT-SOURCE.md)
Domain repo: <DOMAIN_REPO>, read-only snapshot at <DOMAIN_SNAPSHOT> (your working directory; its CLAUDE.md and project skills are loaded)
The contract between agent-fix and the domain skills: <AF_DIR>/references/contract.md
Role skills: diagnose <DIAGNOSE_SKILL> | reproduce <REPRODUCE_SKILL> | prove <PROVE_SKILL>
Trials per question: <TRIALS>. Tracker item for every PR: <TRACKER_ITEM>
Other repos: under <REPOS_ROOT>
Night-sprint skill: <NS_DIR>. agent-fix skill: <AF_DIR>

FIRST, every time this prompt starts a session (including a relay): `echo "$CLAUDE_CODE_SESSION_ID" > <WS>/phases/state/TRIAGE.session`.

**The phase runner.** A detached runner (`<WS>/phases/watch.sh`) watches you. If your process dies it resumes this conversation. If you end your turn on purpose it leaves you alone while something can wake you: a Monitor, a background command, or the gate marker of STEP 4. The next phase starts only when you write `DONE` to <WS>/phases/state/TRIAGE.status. Write that file as your LAST action, and only where a step says so.

**Read only, except where a role skill says otherwise.** Read code in detached snapshots, never in <USER>'s checkouts: `git -C <repo> fetch -q origin <default branch> && git -C <repo> worktree add -q --detach <WS>/snap/<repo name> origin/<default branch>`. Cite code as `<repo>:<path>:<line> @<short sha>`.

**Context.** Measure yourself with `bash <WS>/phases/context-used.sh --self <CONTEXT_WINDOW>` after each step. At <RELAY_AT_USED>% used, write where you are to <WS>/LOG.md and relay with `next-prompt`; your successor's prompt says: "Read <WS>/phases/prompt-TRIAGE.txt in full - it is your role - then <WS>/LOG.md, and resume at the step LOG.md names."

Read <AF_DIR>/references/contract.md now. It defines what each role reads and writes and what its verdict means.

**Stopping early.** Where a step says "stop": write <WS>/REPORT.md (the issue, what was found, the verdict, the evidence files), send a push notification `agent-fix stopped: <ISSUE> - <the reason>` (the tool is `PushNotification`; load it with ToolSearch), write `BLOCKED: <the reason>` to <WS>/phases/state/TRIAGE.status, post REPORT.md as your final message, and end.

## STEP 1 - DIAGNOSE

Read <DIAGNOSE_SKILL> in full and follow it, as its "Under agent-fix" section says. Then read <WS>/state/DIAGNOSE.verdict:
- `FOUND` - go on.
- `HYPOTHESIS` - go on; every later report says "hypothesis" beside the root cause.
- `UNKNOWN` - stop: "root cause not found".

## STEP 2 - REPRODUCE: RED FIRST

Read <REPRODUCE_SKILL> in full and follow it, as its "Under agent-fix" section says. Then read <WS>/state/REPRODUCE.verdict:
- `RED` or `FLAKY` - go on.
- `NOT_REPRODUCED` - stop: "not reproduced". No RED, no fix.
- `BLOCKED` - stop, with the verdict's reason.

## STEP 3 - SOLVE: OPTIONS, THEN TWO CONSULTANTS

**Write the options.** In <WS>/FIX-OPTIONS.md, write every fix worth weighing, at least two when two exist. Draw the surfaces from ISSUE.md's `Where a fix can live`. For each:

    ## <id>: <title>
    What changes:  <the change, and the files or the live config, with citations>
    Ships by:      <a PR in <repo> | a live config change (no PR) - from ISSUE.md>
    Scope:         S | M | L (files, repos, callers touched)
    Kind:          root cause | plaster (stops the symptom, leaves the cause)
    Turns GREEN:   <why each case in CASES.txt passes after it>
    Also fixes:    <the blast radius it covers>
    Risks:         <what else it can break; the other callers and agents of what changes>

**Overfitting is a plaster.** A fix that names the eval's question, its words, or its expected value in a prompt or a rule turns the cases GREEN and leaves the issue. Mark it `plaster` and never pick it.

**Consult, with one neutral brief.** Both consultants get the same brief, and it holds facts, not your preference: the issue, ISSUE.md, BEFORE.md, FIX-OPTIONS.md with the options unranked, the snapshot paths, and this question:

    Which option is the cleanest correct fix for this issue, and why? Judge root cause vs symptom,
    scope, risk to other callers and agents, and whether it would only make the eval cases pass.
    Name an option we missed if there is one. Answer: pick <id or new> | confidence high/medium/low,
    then 3-6 sentences citing repo:<path>:<line> or the trace. Read the code; edit nothing.

- **Astra (Codex)** - this run's Codex status is `<CODEX>`; consult only when it is `ready`. Call the tool ending in `codex-bridge__codex_ask` with `model: gpt-6-astra`, `effort: high`, `sandbox: read-only`, `cwd: <WS>`, `wait_seconds: 900`. A model error that names the model: ask once more without `model`. Still running: one `codex_check` with `wait_seconds: 900`, then `codex_cancel` and record "Astra: timed out". Keep the answer verbatim in <WS>/consult/ASTRA.md with the `codex resume <session_id>` line.
- **Fable** - <USER> explicitly asked for Fable as a consultant, so this is the one subagent this run spawns. One `Agent` call: `subagent_type: general-purpose`, `model: fable`, `description: "Fable fix consult"`, the brief as the prompt plus "You are read-only: no edits, commits, posts or subagents. Return your answer as your final message." Wait for it. Keep the answer verbatim in <WS>/consult/FABLE.md. If Fable is unavailable, record "Fable: unavailable - <the error>" and go on.

**Decide.** You own the call; the consultants are evidence. Open what each one cites and confirm it before it moves you; a cited fact you cannot confirm changes nothing. A new option a consultant names joins FIX-OPTIONS.md if the code bears it out. The cleanest fix removes the root cause where it lives, with the smallest change that does that, and no special case for the eval's question.

## STEP 4 - THE FIX-SCOPE GATE

Raise the gate only when BOTH hold:

1. The live options include a **large-scope root-cause fix** (scope L, or M across repos) AND a **small-scope plaster** (scope S, Kind plaster).
2. **The call is not clear**: the consultants split between those two, or they agree and your confidence is still not high, or the plaster is the only one that fits this run (for example the clean fix is a refactor other teams own).

Also raise it when the pick ships as a **live config change** (no PR): BUILD builds PRs only, so <USER> decides whether to apply it by hand or take a code option. In every other case, decide and go to STEP 5, recording "Gate: not raised - <why>" in LOG.md.

**To raise it:**
- Write <WS>/GATE.md: the options side by side (what changes, how it ships, scope, what it leaves broken, risk), each consultant's pick in one line, and your recommendation with why.
- Push notification: `agent-fix needs your call: <ISSUE> - <option A title> vs <option B title>. Details: <WS>/GATE.md. Reply: claude attach <first 8 chars of the id in <WS>/phases/state/TRIAGE.session>`.
- Post GATE.md as your final message, ending with: "Reply with the option id, or a note. `go` takes my recommendation."
- Just before you post it: `bash <WS>/phases/phase-chain.sh waiting <WS>/phases TRIAGE on`. Then END YOUR TURN and wait.

When <USER> replies: first `bash <WS>/phases/phase-chain.sh waiting <WS>/phases TRIAGE off`. Take their pick, or your recommendation on `go`. A note becomes part of the plan. <USER> is present now: if the reply is genuinely ambiguous, ask ONE short question; never ask to confirm a clear reply. A live-config pick: write the exact change in REPORT.md as <USER>'s action, then stop with "fix is a live config change".

## STEP 5 - THE FIX PLAN AND THE HAND-OVER

Write <WS>/FIX-PLAN.md - what BUILD builds from:

    # Fix: <title>
    **Picked:** <id> - <why, one sentence> (<"by <USER> at the gate" | "gate not raised">)
    **Consultants:** Astra <pick, confidence> | Fable <pick, confidence> - <agreed | how the split was settled>
    ## Root cause       <from ISSUE.md, two sentences>
    ## The change       <what changes, per repo, with file citations>
    ## Out of scope     <the options not picked; anything the fix must not touch>
    ## Proof            <the cases in CASES.txt go GREEN on the fixed agent, <TRIALS> trials each, run by the prove role;
                         the regression neighbours: at most 20 existing cases of the same domain or topic, by id>
    ## Repos            <one line per repo the fix touches: absolute path, default branch>

Then hand over:

1. Append to <WS>/facts.env: `FIX_REPO=<absolute path of the first repo in ## Repos>`, `FIX_BASE=<its default branch>`, `FIX_REPOS=<every repo path, comma separated>`, `CASES_PR=<the content of CASES_PR.url>`.
2. Point BUILD at the fix repo: `bash <WS>/phases/phase-chain.sh add <WS>/phases BUILD <the FIX_REPO path> SHIP`.
3. Render BUILD's prompt: `bash <NS_DIR>/references/render.sh <WS> <AF_DIR>/references/build-prompt.md <WS>/phases/prompt-BUILD.txt`. It must report no unfilled slot.
4. Write <WS>/REPORT.md: the issue, the root cause, the RED result (cases, k/<TRIALS> each), the case PR, the options with both consultants' picks, the pick and whether the gate was raised.
5. LAST: write `DONE` to <WS>/phases/state/TRIAGE.status. That starts BUILD.
6. For up to three minutes, check that <WS>/phases/state/BUILD.session appears. If it does not, run `bash <WS>/phases/phase-chain.sh runner <WS>/phases` once and wait two more minutes; still nothing, put this in your final message: `cd <WS>/phases && bash phase-chain.sh runner <WS>/phases`. Never launch BUILD yourself with `claude --bg`.

Post REPORT.md as your final message and stop. Never delete the workspace.
