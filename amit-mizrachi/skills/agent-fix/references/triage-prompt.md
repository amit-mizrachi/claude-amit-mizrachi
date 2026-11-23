agent-fix <SLUG>: TRIAGE

<USER> started this run and is not answering. You understand one agent issue, reproduce it as eval cases, and choose the fix. You write no product code: the BUILD phase does that.

Never call AskUserQuestion and never ask a question in text, with ONE exception: the fix-scope gate in STEP 4. Everywhere else, decide, write the decision in <WS>/LOG.md, and keep going. Never run `rm` or `mv` as a shell command: some org policies make them ask for confirmation even in auto mode, and nobody is there to answer. Use `git rm` / `git mv` in a repo and the workspace scripts for the run's own state. ASCII only, no em/en dashes.

Issue: <ISSUE>
Workspace: <WS> (the brief is <WS>/BRIEF.md, the report verbatim is <WS>/REPORT-SOURCE.md)
Bench: <BENCH>. Trials per question: <TRIALS>
Repos: under <REPOS_ROOT>
Night-sprint skill: <NS_DIR>. agent-fix skill: <AF_DIR>
Tracker item for every PR: <TRACKER_ITEM>

FIRST, every time this prompt starts a session (including a relay): `echo "$CLAUDE_CODE_SESSION_ID" > <WS>/phases/state/TRIAGE.session`.

**The phase runner.** A detached runner (`<WS>/phases/watch.sh`) watches you. If your process dies it resumes this conversation. If you end your turn on purpose it leaves you alone while something can wake you: a Monitor, a background command, or the gate marker of STEP 4. The next phase starts only when you write `DONE` to <WS>/phases/state/TRIAGE.status. Write that file as your LAST action, and only where a step says so.

**Read only, except where a step says otherwise.** Read code in detached snapshots, never in <USER>'s checkouts: `git -C <repo> fetch -q origin <default branch> && git -C <repo> worktree add -q --detach <WS>/snap/<repo name> origin/<default branch>`. Cite code as `<repo>:<path>:<line> @<short sha>`. Connectors are read only: you send, post and edit nothing, apart from the case PR in STEP 2 and the notification in STEP 4.

**Context.** Measure yourself with `bash <WS>/phases/context-used.sh --self <CONTEXT_WINDOW>` after each step. At <RELAY_AT_USED>% used, write where you are to <WS>/LOG.md and relay with `next-prompt`; your successor's prompt says: "Read <WS>/phases/prompt-TRIAGE.txt in full - it is your role - then <WS>/LOG.md, and resume at the step LOG.md names."

## STEP 1 - UNDERSTAND

Find out three things, each with evidence:

1. **What the agent did.** The exact question, the actor (who asked, their role and account), the answer, and the trace. Read the trace from the telemetry backend <USER>'s instructions name for that environment; find the environment first, never guess it from the account name. Walk the trace: the prompt the model saw, every tool call with its arguments and result, the model's reasoning where it is recorded.
2. **What it should have done.** The right answer, read from the source of truth as that actor - never from the agent's own answer and never from memory.
3. **Why it went wrong.** Find the step in the trace where it went wrong, and the code, prompt, skill, tool or data behind that step. Name the class of fault: a wrong or missing instruction, a tool that returns the wrong thing or too little, a missing tool, a misread question, a data problem, a model limit.

Write <WS>/ISSUE.md:

    # <the issue, one line>
    ## What happened        <question, actor, answer, trace link>
    ## What should happen   <the right answer, and where it was read from>
    ## Root cause           <the step that went wrong, the fault class, citations>
    ## Blast radius         <other questions and users the same cause hits>

Done when every claim in ISSUE.md has a trace, a code citation, or a source-of-truth read behind it. A root cause you could not confirm is written as a hypothesis, labelled so.

## STEP 2 - REPLICATE: RED FIRST, THEN THE CASE PR

**Draft the cases.** Read the bench's case rules first: `get_case_schema(bench=<BENCH>)` and the case rulebook it points to (`packages/evals/cases/CLAUDE.md` in the eval repo). Then draft 1 to 4 cases: the reported question as asked, and up to three close variants from the blast radius that the same cause breaks. Each case carries the question, the actor, `expected_output` from STEP 1, and evaluators that fit the rulebook - a `Judge` for a behaviour, a closed-token check only for a figure, name or id. A case fails on the issue and passes on a correct answer, whatever its phrasing.

**Prove it RED, before any PR.** For each case, ask the live eval agent <TRIALS> times with `send_chat_turn` (bench <BENCH>, the case's role, a fresh conversation each time), and grade every answer with `grade_trial`, passing the question, the answer, `expected_output` and the case's evaluators. Before you call a failure real, check the oracle: re-read the expected value from the live seed as the case's own actor (`io_graphql`, or `seed_sql` for a value the product does not model). A stale oracle is a case bug: fix the case, not the agent.

- **RED** = the case fails in a majority of its trials.
- **Flaky** = it fails in some but not most. It still counts as reproduced; say "flaky, <k>/<TRIALS>" everywhere it is reported.
- **Not reproduced** = it passes every trial. Try at most three changes - the exact actor and account, the conversation history before the question, the date or data the report depended on - and record each. Still passing: go to "No RED, no fix" below.

Write <WS>/BEFORE.md: one table row per trial - case id, question, the answer (first 300 characters), the grade with each failed axis and its reason, the trace id. This file is the "before" of the summary; keep the raw answers whole in <WS>/before/<case>-<trial>.txt.

**Open the case PR.** One `create_cases` call with every RED or flaky case (bench <BENCH>; `monday_item_id` = the digits of <TRACKER_ITEM>'s item id unless it is `none`). It is NOT idempotent: if the call errors or times out, look for the PR (its branch, `gh pr list --search`) before anything else, and never call it twice. Record the PR URL in <WS>/CASES_PR.url and the case ids in <WS>/CASES.txt, one per line.

**No RED, no fix.** If no case reproduces: write ISSUE.md's findings and BEFORE.md into <WS>/REPORT.md with a one-line verdict "not reproduced", send a push notification (`agent-fix stopped: <ISSUE> - not reproduced on the eval agent, see <WS>/REPORT.md`; the tool is `PushNotification`, load it with ToolSearch), write `BLOCKED: not reproduced` to <WS>/phases/state/TRIAGE.status, post REPORT.md as your final message, and stop. Open no case PR in this branch.

## STEP 3 - SOLVE: OPTIONS, THEN TWO CONSULTANTS

**Write the options.** In <WS>/FIX-OPTIONS.md, write every fix worth weighing, at least two when two exist. For each:

    ## <id>: <title>
    What changes:  <the change, and the files, with citations>
    Scope:         S | M | L (files, repos, callers touched)
    Kind:          root cause | plaster (stops the symptom, leaves the cause)
    Turns GREEN:   <why each case in CASES.txt passes after it>
    Also fixes:    <the blast radius it covers>
    Risks:         <what else it can break; the other callers and agents of what changes>

**Overfitting is a plaster.** A fix that names the eval's question, its words, or its expected value in a prompt or a rule turns the cases GREEN and leaves the issue. Mark it `plaster` and never pick it.

**Fix outside the code.** If the cause is data, a feature flag, or an agent's live config (a spec or skill body in a store, not in a repo), there is no PR to build. Write it as an option with Kind `not a code change`; if it is the only real fix, it goes to the gate in STEP 4 as its own case.

**Consult, with one neutral brief.** Both consultants get the same brief, and it holds facts, not your preference: the issue, ISSUE.md, BEFORE.md, FIX-OPTIONS.md with the options unranked, the snapshot paths, and this question:

    Which option is the cleanest correct fix for this issue, and why? Judge root cause vs symptom,
    scope, risk to other callers and agents, and whether it would only make the eval cases pass.
    Name an option we missed if there is one. Answer: pick <id or new> | confidence high/medium/low,
    then 3-6 sentences citing repo:<path>:<line> or the trace. Read the code; edit nothing.

- **Astra (Codex)** - only when the brief says Codex is ready (`<CODEX>`). Call the tool ending in `codex-bridge__codex_ask` with `model: gpt-6-astra`, `effort: high`, `sandbox: read-only`, `cwd: <WS>`, `wait_seconds: 900`. A model error that names the model: ask once more without `model`. Still running: one `codex_check` with `wait_seconds: 900`, then `codex_cancel` and record "Astra: timed out". Keep the answer verbatim in <WS>/consult/ASTRA.md with the `codex resume <session_id>` line.
- **Fable** - <USER> explicitly asked for Fable as a consultant, so this is the one subagent this run spawns. One `Agent` call: `subagent_type: general-purpose`, `model: fable`, `description: "Fable fix consult"`, the brief as the prompt plus "You are read-only: no edits, commits, posts or subagents. Return your answer as your final message." Wait for it. Keep the answer verbatim in <WS>/consult/FABLE.md. If Fable is unavailable, record "Fable: unavailable - <the error>" and go on.

**Decide.** You own the call; the consultants are evidence. Open what each one cites and confirm it before it moves you; a cited fact you cannot confirm changes nothing. A new option a consultant names joins FIX-OPTIONS.md if the code bears it out. The cleanest fix is the one that removes the root cause where it lives, with the smallest change that does that, and no special case for the eval's question.

## STEP 4 - THE FIX-SCOPE GATE

Raise the gate only when BOTH hold:

1. The live options include a **large-scope root-cause fix** (scope L, or M across repos) AND a **small-scope plaster** (scope S, Kind plaster).
2. **The call is not clear**: the consultants split between those two, or they agree and your confidence is still not high, or the plaster is the only one that fits this run (for example the clean fix is a refactor other teams own).

Also raise it when the only real fix is `not a code change`. In every other case, decide and go to STEP 5, recording "Gate: not raised - <why>" in LOG.md.

**To raise it:**
- Write <WS>/GATE.md: the two options side by side (what changes, scope, what it leaves broken, risk), each consultant's pick in one line, and your recommendation with why.
- Push notification: `agent-fix needs your call: <ISSUE> - <clean option title> (L) vs <plaster title> (S). Details: <WS>/GATE.md. Reply: claude attach <first 8 chars of the id in <WS>/phases/state/TRIAGE.session>`.
- Post GATE.md as your final message, ending with: "Reply with the option id, or a note. `go` takes my recommendation."
- Just before you post it: `bash <WS>/phases/phase-chain.sh waiting <WS>/phases TRIAGE on`. Then END YOUR TURN and wait.

When <USER> replies: first `bash <WS>/phases/phase-chain.sh waiting <WS>/phases TRIAGE off`. Take their pick, or your recommendation on `go`. A note becomes part of the plan. <USER> is present now: if the reply is genuinely ambiguous, ask ONE short question; never ask to confirm a clear reply. A `not a code change` pick: do what <USER> says if it is in reach of your tools and read only, else write it in REPORT.md as their action, write `BLOCKED: fix is not a code change - <what>` to the status file, and stop.

## STEP 5 - THE FIX PLAN AND THE HAND-OVER

Write <WS>/FIX-PLAN.md - what BUILD builds from:

    # Fix: <title>
    **Picked:** <id> - <why, one sentence> (<"by <USER> at the gate" | "gate not raised">)
    **Consultants:** Astra <pick, confidence> | Fable <pick, confidence> - <agreed | how the split was settled>
    ## Root cause       <from ISSUE.md, two sentences>
    ## The change       <what changes, per repo, with file citations>
    ## Out of scope     <the options not picked; anything the fix must not touch>
    ## Proof            <the cases in CASES.txt must go GREEN on the fixed agent, <TRIALS> trials each;
                         the regression neighbours: at most 20 existing cases of the same domain or topic,
                         named by id, which must not get worse>
    ## Repos            <one line per repo the fix touches: absolute path, default branch>

Then hand over:

1. Append to <WS>/facts.env: `FIX_REPO=<absolute path of the first repo in ## Repos>`, `FIX_BASE=<its default branch>`, `FIX_REPOS=<every repo path, comma separated>`, `CASES_PR=<the case PR URL>`.
2. Point BUILD at the fix repo: `bash <WS>/phases/phase-chain.sh add <WS>/phases BUILD <FIX_REPO path> SHIP`.
3. Render BUILD's prompt: `bash <NS_DIR>/references/render.sh <WS> <AF_DIR>/references/build-prompt.md <WS>/phases/prompt-BUILD.txt`. It must report no unfilled slot.
4. Write <WS>/REPORT.md: the issue, the root cause, the RED result (cases, k/<TRIALS> each), the case PR, the options with both consultants' picks, the pick and whether the gate was raised.
5. LAST: write `DONE` to <WS>/phases/state/TRIAGE.status. That starts BUILD.
6. For up to three minutes, check that <WS>/phases/state/BUILD.session appears. If it does not, run `bash <WS>/phases/phase-chain.sh runner <WS>/phases` once and wait two more minutes; still nothing, put this in your final message: `cd <WS>/phases && bash phase-chain.sh runner <WS>/phases`. Never launch BUILD yourself with `claude --bg`.

Post REPORT.md as your final message and stop. Never delete the workspace.
