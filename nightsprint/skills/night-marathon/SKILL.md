---
name: night-marathon
description: "Takes a feature from an idea to one pull request with no supervision between the stages, and asks the user nothing once it is invoked. It researches what the plan needs from the code and the allowed sources, publishes a short plan artifact with realistic UI mockups drawn from the repo's own design system and a pick list of the few decisions that matter, then builds the chosen plan overnight as one PR. Two modes: autonomous (the default - the recommended options are built without stopping) and review (only when the invocation says `mode: review` - the run stops at the plan artifact until the user pastes their picks into the conductor session). Use when the user says \"night marathon\", \"feature e2e\", \"feature end to end\", \"research, plan and build this\", \"take this feature all the way\", or wants a feature planned with mockups and then built while they are away."
argument-hint: "<feature description> [repo: <path>] [mode: autonomous|review] [speed: serial|blitz] [parallel: <n>] [test: none|dev-stack|evals|<command>] [depth: quick|standard|deep] [sources: <connector>, ...]"
---

# Night Marathon

## Overview

One feature, three stages, and **no questions**. From the moment the skill is invoked it asks the user nothing: every setting comes from the invocation or a default (step 2), and the brief is shown, not approved.

1. **Research** - a `night-sprint` in research mode answers what the plan needs to know, from the repo and the allowed sources, with citations.
2. **Plan** - its last stage drafts the plan, asks Codex (`gpt-6-astra`, medium effort) to review the whole plan when the codex-bridge MCP server is connected - its decisions and the blind spots nobody knew to decide - settles the final plan with that second opinion, then publishes a plan artifact: UI mockups built from the repo's real tokens and components, and only the decisions worth a human's time, each with a recommendation and a **Pick this** radio. The page copies the picks as text.
3. **Build** - a code `night-sprint` runs `to-spec` and `to-tickets` on the chosen plan and delivers one PR.

**Between stages 2 and 3 the mode decides.** `autonomous` (default): the conductor takes every recommended option and starts the build. `review` (only when the invocation names it): the conductor stops, sends the artifact link, and waits until the user pastes their copied picks into it. That wait is the user's own choice at invocation, never a question this skill raises.

You run the front door, in the user's session: the checks, the settings, the brief, the launch. Then you stop. Background sessions do the rest.

**Never call `AskUserQuestion` and never ask a question in text, at any step.** When something is unclear, decide, write the decision into `BRIEF.md` under `## Decided without asking`, and go on. The user reads the brief after launch and can stop the run if a call was wrong; a question asked now is a run that has not started when they come back.

This skill builds on `night-sprint`, `to-spec`, `to-tickets` and `next-prompt`, which ship next to it. It changes none of their rules; the conductor prompt in `references/` tells them where the hand-offs are.

## 1. Check you can run it - silently

    command -v claude git python3 && claude agents --json --all >/dev/null && echo ready

`NM` = this skill's base directory, `NS` = `<NM>/../night-sprint`, both absolute. Confirm `NS/references/research-mode.md` and `NM/references/conductor-prompt.md` exist.

The repo is `repo:` from the invocation, else the git top level of the working directory (`git rev-parse --show-toplevel`), else the one repo the conversation is plainly about. None of these? Stop and say so (below). `BASE` is the default branch: `git -C <repo> symbolic-ref --short refs/remotes/origin/HEAD`, without the `origin/`.

Anything missing: stop and say exactly what, with the invocation that would work. That is a failed launch, not a question: do not wait for an answer.

Codex is optional. ToolSearch `codex_status` and call the tool whose name ends in `codex-bridge__codex_status` (this plugin ships the server). A result starting `ready: yes` means the plan stage gets a second opinion. No tool, or `ready: no`, means it runs without one: never stop the run over it, and say which in the brief, with the status result's `fix:` line when there is one.

## 2. Settings - from the invocation, never asked

The feature is the invocation's text. No feature there? Take it from the conversation that led here. Still none? Stop and say so, as in step 1.

Take each setting from the invocation when it names one, else use the default. Do not ask about any of them.

| Setting | Invocation | Default |
|---|---|---|
| **Mode** | `mode: autonomous\|review` | `autonomous` - the recommended plan is built |
| **Speed** | `speed: serial\|blitz`, `parallel: <n>` | `serial`. `blitz` runs the research questions, then the build tickets, side by side on their dependency graph (night-sprint's blitz mode), at most `parallel` writers at once (default 3). Faster, and it costs more tokens and quota per hour, which is why it is never the default |
| **Test the build** | `test: none\|dev-stack\|evals\|<command>` (night-sprint's `test:` values) | `none` |
| **Extra sources** | `sources: <connector>, ...` | every connector in your tool list (`mcp__claude_ai_<Name>__*`, `mcp__<server>__*`) that could hold earlier talk about this feature - Slack, Monday, Figma, Drive - at most four. All are read only. The repo and the web are always in |
| **Depth** | `depth: quick\|standard\|deep` | `standard` - 5 research questions (quick 3, deep 8) |

## 3. The brief - shown, not approved

Slug: the feature in kebab case, at most 40 characters, plus `-<YYYYMMDD>`. Workspace `WS` = `~/claude-research/<slug>/`, adding `-2`, `-3` if it exists. **Never under `~/.claude`**: Claude Code guards writes there, and a background session stops on that prompt with nobody to answer it.

Write `<WS>/BRIEF.md`:

    # <Feature>

    **Feature:** <what it does, for whom, 1-3 sentences>
    **Repo:** <owner/repo>, base <BASE>
    **Mode:** <autonomous | review> - <what that means, one line>
    **Speed:** <serial | blitz, at most <n> at once>
    **Build test:** <none | dev-stack | evals | the command>
    **Second opinion:** <Codex gpt-6-astra (medium) reviews the draft plan before it is final | none - <codex-bridge is not connected | the fix: line>>

    ## What the plan must learn
    1. <one line per research question, answerable from the sources>

    ## Sources (read only)
    - The repo, at a snapshot of origin/<BASE>
    - Web
    - <each extra connector>

    ## Out of scope
    - <what this will not build>

    ## Decided without asking
    - <each setting that came from a default, and each judgement call, one line each>

    ## Deliverables
    - A plan artifact: UI mockups from the repo's own components, the decisions that matter with a recommendation each, and a copy-your-picks bar.
    - One pull request implementing the chosen plan, in draft until CI is green. Never merged or deployed by the run.

Do not show it for approval. Go straight to step 4; the brief goes into the report in step 5.

## 4. Start it

1. **Snapshot the repo**, so research reads the code at one commit and never the user's own checkout:

       git -C <repo> fetch -q origin <BASE> && git -C <repo> worktree add -q --detach <WS>/repo origin/<BASE>

   `REPO_SHA` = `git -C <WS>/repo rev-parse --short HEAD`.
2. **Write `<WS>/facts.env`**, one `KEY=VALUE` per line, every value on one line. The research-mode keys from `NS/references/research-mode.md`, filled like this:

   | Key | Value |
   |---|---|
   | `MODE` | `research` |
   | `WORKTREE` / `BRANCH` | `<WS>/work` / `research/<slug>` |
   | `VERIFY` | `bash <WS>/research-check.sh <WS>` |
   | `RESEARCH_TITLE` | `<Feature> - plan` |
   | `QUESTION` | `What must we learn to plan <feature> well, and how should its UI look?` |
   | `DECISION` | `Which plan to build for <feature>` |
   | `AUDIENCE` | `<user's first name>, who picks the plan` |
   | `SOURCES` | `The repo snapshot at <WS>/repo (read only; cite as repo:<path>:<line> @<REPO_SHA>); Web (WebSearch, WebFetch); <each extra connector>` |
   | `CONTEXT_WINDOW` | `1000000` if your model id ends in `[1m]`, else `200000` |

   plus `PERMISSION_MODE=auto`, `WARN_AT_USED=20`, `RELAY_AT_USED=30`, `CEILING_USED=60`, `SLUG`, `USER`, `WS` - and these night-marathon keys:

       FEATURE=<one-line feature description>
       MARATHON_MODE=<autonomous|review>
       REPO_PATH=<absolute repo path>
       BASE=<BASE>
       REPO_SNAPSHOT=<WS>/repo
       REPO_SHA=<REPO_SHA>
       BUILD_TEST=<none|dev-stack|evals|the command>
       SPEED=<serial|blitz>
       BLITZ=<1 for blitz, else 0>
       MAX_PARALLEL=<parallel: from the invocation, else 3>
       DEPTH=<3|5|8>
       NS_DIR=<NS>
       NM_DIR=<NM>

   Leave out `TOTAL`; the conductor adds it once the tickets exist.
3. **Set up the phase chain** - one runner over the whole run. Each conductor of the run is a phase: the research conductor, then the build. The runner launches each phase when the one before it writes `DONE`, and it classifies and resumes any conductor that dies, the way night-sprint's runner does for tickets. It lives in `<WS>/phases/`, **not** `<WS>/state/`, where the research sprint's runner treats every `.session` file as a ticket.

       bash <NS>/references/phase-chain.sh init <WS>/phases <NS>/references <SLUG> <CONTEXT_WINDOW>
       bash <NS>/references/phase-chain.sh add  <WS>/phases CONDUCTOR <WS> BUILD
       bash <NS>/references/phase-chain.sh add  <WS>/phases BUILD <REPO_PATH>

   A run that ends in more than one PR gets one build phase per PR, in merge order, each in its own repo: `add ... CONDUCTOR <WS> BUILD-A`, `add ... BUILD-A <repo A> BUILD-B`, `add ... BUILD-B <repo B>`. Render each build phase's prompt here, at kickoff, from `build-prompt.md` with that phase's facts, to `<WS>/phases/prompt-<PHASE>.txt`, then point its session and status files at its own phase:

       sed -i '' 's#phases/state/BUILD\.#phases/state/<PHASE>.#g; s#phases/prompt-BUILD\.txt#phases/prompt-<PHASE>.txt#g' <WS>/phases/prompt-<PHASE>.txt

   Each build phase's own night-sprint gets its own workspace (`<WS>/build-<phase>`), and the earlier phase writes what the later one needs (a contract file) into it. No build phase launches another: the runner does.
4. **Render, launch the conductor and start the runner:**

       bash <NS>/references/render.sh <WS> <NM>/references/conductor-prompt.md <WS>/phases/prompt-CONDUCTOR.txt
       bash <WS>/phases/phase-chain.sh start <WS>/phases CONDUCTOR

   The render must report no unfilled slot. `start` launches the conductor (its id lands in `<WS>/phases/state/CONDUCTOR.session`), then starts the runner detached from every session, so no conductor's death takes it down. It must print `runner: running`. Start it from here, while the user is at the keyboard: if starting a detached process asks for a permission, the user can answer it now and nobody can at 3am.

If the launch or the runner fails - most often because `auto` mode is not available on the account's model - do not ask what to do. Say what failed and give one command the user can paste into a fresh terminal: an absolute `cd <WS>/phases`, then the `start` line.

## 5. Tell the user, then stop

Six lines, no more:

- It is running. Autonomous: nothing will be asked. Review: the next stop is the plan artifact.
- The brief at `<WS>/BRIEF.md`, with its `Decided without asking` lines. To change a call, stop the run and invoke again with that setting named.
- The workspace path, and `claude agents` / `claude attach <short id>` to look in. Every conductor launch, death and revive is logged in `<WS>/phases/state/EVENTS.log`. `night-watch` in any terminal draws the run's live progress, stage by stage.
- What arrives: the plan artifact link (push notification and `<WS>/REPORT.md`), then the PR from the build session (`<WS>/build/REPORT.md`).
- Review mode: on the page, pick, press **Copy decisions**, then `claude attach <short id>` and paste. The notification carries the id.
- The rough duration: a few hours for the research and plan at Standard depth, then a night for the build.

Do not watch the run from this session. The conductors own it.

## Red Flags - STOP

| Thought | Reality |
|---|---|
| "I'll just confirm the mode, the test or the brief before I launch." | The skill asks nothing once invoked. Take the setting from the invocation or the default, write the call under `Decided without asking`, and launch. A question at kickoff is a run that has not started when the user comes back. |
| "I'll have research read the user's checkout, it is right there." | It is on some branch, maybe dirty, and it moves. The snapshot pins one commit, and the citations name it. |
| "The mockup can use a generic look, the decisions are what matter." | A generic mockup is invented UI that the build then copies faithfully. The UI-kit ticket and the real-source rule exist for this. |
| "Put every choice on the page, the user can skip the small ones." | The user asked for the few decisions that matter. The synth prompt's filter decides the rest and lists them in one collapsed line each. |
| "In review mode I'll ask the user to approve the tickets too." | Picking the plan is the approval. A second gate turns a one-night build into a two-day wait. |
| "The conductor can launch the build itself with `claude --bg` and stop." | That is how a night was lost: the build died 2.5 minutes in on a dropped connection and nothing watched it for six hours. The phase runner owns every hop, and keeps watching. |
| "The build conductor can use `~/.claude/night-sprint/<slug>/` like a normal sprint." | It is a background session; a write there stops on a prompt. It uses `<WS>/build`. |
| "`to-tickets` found a GitHub tracker config, publishing issues is fine." | Nothing is posted at night. Spec and tickets stay local in the workspace. |
| "Codex disagrees, so its option wins." | It is a second opinion, not a vote. The plan stage confirms what Codex cites before it changes a recommendation, and records every agree, change and keep in PLAN.md. |
| "Codex says the plan missed something, so it goes on the page." | A blind spot is a lead, not a fact. The plan stage confirms it in the code first, then files it where it belongs: a decision only if it passes the filter, otherwise decided for you, a build step or a risk. |
