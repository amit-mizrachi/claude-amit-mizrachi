---
name: product-research
description: Researches a product question end to end with ONE approval from the user. It interviews the user, writes a research brief, and gets it approved; after that it asks nothing again. A background conductor turns the brief into a spec and research tickets (to-spec, to-tickets), runs a night-sprint in research mode that answers each question from the user's connectors and the web with cited sources, checks the evidence, and ends in one published artifact. Use when the user says "product research", "research this", "look into X for me", "competitive analysis", "market research", "what do customers say about X", or wants a question researched from Slack, Drive, email, CRM or the web without supervising it.
argument-hint: "[what to research]"
---

# Product research

One conversation, one approval, then silence until the artifact is ready. You run the front
door in the user's session: the interview, the brief, the approval, the launch. Everything after
the approval happens in background sessions that never ask the user anything.

**Needs Claude Code with the `claude` command.** The research runs as background sessions
(`claude --bg`), which a plain claude.ai chat cannot start.

**This skill and every session it starts are READ ONLY on connectors.** They read Slack, Drive,
email, CRM and the rest; they never send, post, draft, edit, comment or react.

## 1. Check you can run it - silently

    command -v claude git python3 && claude agents --json --all >/dev/null && echo ready

Then find night-sprint, which ships next to this skill: `<this skill's base directory>/../night-sprint`.
Resolve it to an absolute path - call it `NS` - and confirm `NS/references/research-mode.md`
exists.

If anything fails, stop and say exactly what is missing. Do not interview the user for a run
that cannot start.

## 2. See which sources exist

List the information sources in your tool list, loaded or deferred: claude.ai connectors are
`mcp__claude_ai_<Name>__*`, other connectors are `mcp__<server>__*`. Web search (WebSearch,
WebFetch) is always available. Note which look relevant to the topic; you offer those in step 3.

## 3. Interview - short

If the user has not said what to research, ask in plain text and wait. If they have, do not ask
it again.

Then ONE `AskUserQuestion` call, up to four questions, each with options derived from the topic:

- **Decision** - what will this research help decide? (e.g. whether to build it, which segment
  first, how to price it)
- **Audience** - who reads the result? (just me, the product team, leadership, a customer-facing team)
- **Sources** - `multiSelect`. The four most relevant from step 2, with web search first. The
  user can name more through "Other".
- **Depth** - Quick: 3 questions, about an hour. Standard (recommended): 5 questions, a few
  hours. Deep: 8 questions, overnight.

A second round only if an answer leaves the question too vague to split into sub-questions.

## 4. The brief - the only approval

Pick the slug: the topic in kebab case, at most 40 characters, plus `-<YYYYMMDD>`. The workspace
is `~/claude-research/<slug>/` - add `-2`, `-3` if it exists. **Never under `~/.claude`:**
Claude Code guards writes there, and a background session stops on that prompt with nobody
awake to answer it.

Write `<WS>/BRIEF.md`:

    # <Title>

    **Question:** <one sentence>
    **Decision it informs:** <one sentence>
    **Audience:** <who>
    **Depth:** <Quick | Standard | Deep> - <n> questions, <rough duration>

    ## Sub-questions
    1. <one line each, answerable from the allowed sources>

    ## Sources (read only)
    - <each allowed source>

    ## Out of scope
    - <what this will not cover>

    ## Deliverable
    One private artifact page: the answer and what it means for the decision, findings by theme
    with confidence and citations, where the evidence disagrees, gaps, and every source.

Show the brief in full in your reply. Say plainly: **"After you approve, I will not ask you
anything else. The research runs in the background and you get the artifact link at the end."**
Then `AskUserQuestion`: "Start the research with this brief?" with **Approve and start** and
**Change something**. On a change, revise the brief, show it again, and ask again.

## 5. Start it behind the scenes - no more questions from here

After the approval you never call `AskUserQuestion` again in this skill, and nothing you start
does either.

1. Write `<WS>/facts.env` with the keys `research-mode.md` lists, every value on one line.
   Leave out `TOTAL`; the conductor adds it once the tickets exist. `USER` is the user's first
   name if you know it. `CONTEXT_WINDOW` is `1000000` if your own model id ends in `[1m]`,
   else `200000`.
2. Write `<WS>/vars-CONDUCTOR.env` with one line: `NS_DIR=<NS>`.
3. Render the conductor's prompt:

       bash <NS>/references/render.sh <WS> <this skill's base directory>/references/conductor-prompt.md <WS>/prompt-CONDUCTOR.txt <WS>/vars-CONDUCTOR.env

4. Launch it from the workspace:

       cd <WS> && claude --bg -n "ns-<SLUG>-CONDUCTOR" --permission-mode auto "$(cat <WS>/prompt-CONDUCTOR.txt)"

5. Confirm it is running: find the row named `ns-<SLUG>-CONDUCTOR` in
   `claude agents --json --all` and write its `sessionId` to `<WS>/CONDUCTOR.session`. **Not**
   into `<WS>/state/`: the runner treats every `state/*.session` as a ticket.

If the launch fails - most often `auto` mode is not available on the account's model - do not
ask what to do. Say what failed and give one command the user can paste into a fresh terminal
to launch the conductor themselves.

## 6. Tell the user, then stop

Four lines, no more:

- It is running, and nothing more will be asked.
- The workspace path, and `claude agents` / `claude attach <short id>` to look in on it.
- What arrives at the end: the artifact link, in a push notification where available, in the
  conductor's last message, and in `<WS>/REPORT.md`.
- The rough duration, from the depth.

Do not watch the run from this session. The conductor owns it.
