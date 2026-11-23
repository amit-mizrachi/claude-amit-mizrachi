---
name: agent-fix
description: "Fixes one reported AI agent issue end to end with no supervision: understands it from traces, code and the report, reproduces it as eval cases proved RED on the live agent, weighs fix options with Codex (Astra) and Fable as consultants, builds the cleanest fix as a night-sprint PR proved GREEN on the same cases, asks a named reviewer for approval on Slack, and publishes a simple before/after summary artifact. Interrupts the user once at most: a push notification when a large clean fix and a small plaster are both live and the call is not clear. Use when the user says \"agent fix\", \"fix this agent issue\", \"the agent got this wrong, fix it\", or hands over a bad agent answer (Slack thread, trace, conversation) to be reproduced and fixed."
argument-hint: "<issue: Slack link | trace id | conversation | description> [bench: <id>] [approver: <slack name>] [trials: <n>] [speed: serial|blitz] [parallel: <n>]"
---

# Agent Fix

## Overview

One agent issue, five stages, one person interrupted at most once.

1. **Understand** - what the agent did, what it should have done, and why, from the report, the traces and the code.
2. **Replicate** - the issue becomes eval cases. They are proved **RED** on the live agent before anything is fixed, then opened as one case PR.
3. **Solve** - fix options, a second and third opinion from Codex (Astra) and Fable, and the cleanest fix picked. When a large-scope clean fix and a small-scope plaster are both live and the call is not clear, the run sends the user a push notification and waits for their pick. That is the only question the run ever asks.
4. **Build** - a code `night-sprint` builds the fix, reviews it, fixes the findings and proves the same cases **GREEN**.
5. **Ship** - a simple summary artifact (the issue, the cases before and after, the solution, the PRs), then a Slack DM to the approver asking for approval.

You run the front door, in the user's session: the checks, the settings, the brief, the launch. Then you stop. Three background conductors do the rest, one after another, on night-sprint's phase chain: `TRIAGE` (stages 1-3), `BUILD` (stage 4), `SHIP` (stage 5).

**Ask nothing at the front door.** Never call `AskUserQuestion` and never ask a question in text. When something is unclear, decide, write it into `BRIEF.md` under `## Decided without asking`, and launch. The one sanctioned question is the TRIAGE fix-scope gate, and only TRIAGE raises it.

This skill builds on `night-sprint`, `to-spec`, `to-tickets`, `next-prompt` and `deep-review`, which ship next to it, and changes none of their rules.

## 1. Check you can run it - silently

    command -v claude git gh python3 && claude agents --json --all >/dev/null && echo ready

`AF` = this skill's base directory, `NS` = `<AF>/../night-sprint`, both absolute. Confirm `NS/references/phase-chain.sh` and `AF/references/triage-prompt.md` exist.

Then look up, with ToolSearch, and note which are present:

- **Eval tools** - the eval-ops MCP (`send_chat_turn`, `grade_trial`, `create_cases`, `get_case_schema`). Without them the run cannot replicate: stop and say so. This is a failed launch, not a question.
- **Codex (Astra)** - call the tool ending in `codex-bridge__codex_status`. `ready: yes` means TRIAGE consults it. Anything else: TRIAGE runs without it, and the brief says why.
- **Slack** - `slack_search_users` and `slack_send_message`. Without them SHIP writes the approval message to a file instead of sending it.

## 2. Settings - from the invocation, never asked

The issue is the invocation's text. None there? Take it from the conversation that led here. Still none? Stop and say so.

| Setting | Invocation | Default |
|---|---|---|
| **Bench** | `bench: <id>` | the bench whose agent the issue is about (`list_benches`); the only live bench when there is one |
| **Approver** | `approver: <slack name>` | `Talos` |
| **Trials** | `trials: <n>` | `3` - each question is asked this many times, before and after |
| **Speed** | `speed: serial\|blitz`, `parallel: <n>` | `serial` |

**Resolve the approver now**, while the user is here: `slack_search_users` for the name. Exactly one active match: `APPROVER_SLACK_ID` is its user id. No match, several, or no Slack tools: `none`, and say so in the brief - SHIP then writes the message to a file for the user to send.

**The tracker item.** If the user's own instructions (CLAUDE.md, memory) require a tracker item for every PR, find or create it now exactly as they say, and record its link as `TRACKER_ITEM`. Every PR of the run uses this one item. Otherwise `TRACKER_ITEM=none`.

**Where the repos are.** `REPOS_ROOT` = the directory that holds the user's clones: the parent of `git rev-parse --show-toplevel` when you are in a repo, else the working directory. TRIAGE finds the agent's repos under it.

## 3. The brief - shown, not approved

Slug: `agent-fix-` + the issue in kebab case (at most 32 characters) + `-<YYYYMMDD>`. Workspace `WS` = `~/claude-research/<slug>/`, adding `-2`, `-3` if it exists. **Never under `~/.claude`**: Claude Code guards writes there, and a background session stops on that prompt with nobody to answer it.

Write `<WS>/BRIEF.md`:

    # <the issue, one line>

    **Report:** <the link, trace id or quoted text it came from>
    **What went wrong:** <1-3 sentences, as far as the report says>
    **Bench:** <id> | **Trials:** <n> before and after
    **Consultants:** Codex gpt-6-astra (<ready | not available: why>), Fable
    **Approver:** <name> (<slack id | none: why - SHIP writes the message to a file>)
    **Tracker item:** <link | none>
    **Speed:** <serial | blitz, at most <n> at once>

    ## Decided without asking
    - <each setting that came from a default, and each judgement call, one line each>

    ## Deliverables
    - A case PR: eval cases proved RED on the live agent.
    - A fix PR (one per repo the fix touches), reviewed, with the same cases proved GREEN.
    - A summary artifact: the issue, the cases before and after, the solution, the PR links.
    - A Slack DM to the approver asking for approval, sent only when the fix is GREEN and CI is green.
    - Nothing merged or deployed.

Do not show it for approval. Go to step 4.

## 4. Start it

1. **Write `<WS>/facts.env`**, one `KEY=VALUE` per line, every value on one line:

       SLUG=<slug>
       USER=<user's first name>
       WS=<WS>
       ISSUE=<the issue, one line>
       BENCH=<bench id>
       TRIALS=<n>
       APPROVER=<name>
       APPROVER_SLACK_ID=<id | none>
       TRACKER_ITEM=<link | none>
       CODEX=<ready | none>
       REPOS_ROOT=<absolute path>
       SPEED=<serial|blitz>
       BLITZ=<1 for blitz, else 0>
       MAX_PARALLEL=<parallel: from the invocation, else 3>
       NS_DIR=<NS>
       AF_DIR=<AF>
       CONTEXT_WINDOW=<1000000 if your model id ends in [1m] or the user's instructions say the window is 1M, else 200000>
       PERMISSION_MODE=auto
       WARN_AT_USED=20
       RELAY_AT_USED=30
       CEILING_USED=60

   Put the full report text (the Slack thread, the conversation, the quoted answer) in `<WS>/REPORT-SOURCE.md`, verbatim, so TRIAGE does not depend on this session.

2. **Set up the phase chain.** BUILD's working directory is a placeholder until TRIAGE knows which repo the fix lives in; TRIAGE re-points it before it hands over.

       bash <NS>/references/phase-chain.sh init <WS>/phases <NS>/references <SLUG> <CONTEXT_WINDOW>
       bash <NS>/references/phase-chain.sh add  <WS>/phases TRIAGE <WS> BUILD
       bash <NS>/references/phase-chain.sh add  <WS>/phases BUILD  <WS> SHIP
       bash <NS>/references/phase-chain.sh add  <WS>/phases SHIP   <WS>

3. **Render TRIAGE and SHIP, launch TRIAGE, start the runner.** BUILD's prompt is rendered by TRIAGE, once the fix is chosen.

       bash <NS>/references/render.sh <WS> <AF>/references/triage-prompt.md <WS>/phases/prompt-TRIAGE.txt
       bash <NS>/references/render.sh <WS> <AF>/references/ship-prompt.md   <WS>/phases/prompt-SHIP.txt
       bash <WS>/phases/phase-chain.sh start <WS>/phases TRIAGE

   Each render must report no unfilled slot. `start` must print `runner: running`. Start it from here, while the user is at the keyboard: a permission prompt on the detached runner can be answered now and not at 3am.

If the launch or the runner fails, do not ask what to do. Say what failed and give one paste-ready command: `cd <WS>/phases && bash phase-chain.sh start <WS>/phases TRIAGE`.

## 5. Tell the user, then stop

Five lines, no more:

- It is running. The only possible interruption: a push notification if the fix scope needs their call (large clean fix vs small plaster).
- The brief at `<WS>/BRIEF.md`, with its `Decided without asking` lines.
- The workspace, and `claude agents` / `claude attach <short id>` to look in. `<WS>/phases/state/EVENTS.log` logs every launch, death and revive.
- What arrives: the case PR (TRIAGE), the fix PR (BUILD), then the summary artifact, the Slack DM to the approver and a push notification (SHIP).
- If the run stops early (the issue does not reproduce, or the fix is not a code change), a push notification says why, and `<WS>/REPORT.md` has the evidence.

Do not watch the run from this session.

## Red Flags - STOP

| Thought | Reality |
|---|---|
| "The cause is obvious, skip the RED proof and fix it." | A fix with no RED case cannot be proved GREEN. Replicate first, always. No RED, no build. |
| "I'll make the prompt mention the eval's question so the case passes." | That is overfitting, the worst plaster: the case goes GREEN and the issue stays. The fix addresses the cause; the cases only measure it. |
| "Astra and Fable disagree with each other, so I'll ask the user." | Ask only when the split is large clean fix vs small plaster and you are not sure. Any other disagreement you settle yourself and record. |
| "Codex says so, so it wins." | A consultant is evidence, not a vote. Confirm what it cites in the code before it changes your pick. |
| "CI is still running, but the fix is GREEN, so I'll ping the approver." | The approver gets a PR that is ready: GREEN cases and green CI. Otherwise the message goes to a file and the user decides. |
| "The case PR timed out, I'll call `create_cases` again." | It is not idempotent. Check for the PR first, or a human closes duplicates by hand. |
| "I'll start a full-track eval run to be safe." | It takes the shared eval env from the whole team. Single-question trials and small case selections only. |
