Research sprint <SLUG>: ticket <NN> CONTINUED - <TICKET_TITLE>

AUTONOMOUS RESEARCH RUN. <USER> will NOT answer anything now. Never ask a question - make the best call, state it in your summary, keep going. ASCII only, no em/en dashes.

You are tag <CONT_TAG>. You are NOT starting a new ticket. Ticket <NN> is already partly researched: <PREV_TAG> ran out of context and handed it to you with a full window. Its findings file is committed. Your job is to finish the SAME ticket.

Research: <RESEARCH_TITLE>
Workspace: <WS>. Predecessor: <PREV_TAG>.

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd <WORKTREE>
Local repo, branch <BRANCH>, no remote. You are the ONLY session touching it right now.

THE RULES OF <WS>/prompt-T<NN>.txt STILL BIND YOU - read its "Sources you may use" section and the findings format before you do anything else. Above all: connectors are READ ONLY. Never send, post, draft, edit or comment on anything.

## Where the ticket stands

Ticket file: <WS>/tickets/<NN>-<slug>.md - its acceptance criteria are still the definition of done.
Findings file: <WORKTREE>/findings/<NN>-<slug>.md

ANSWERED already:
- <criterion, and the claims that answer it>

NOT answered yet - this is your work:
- <criterion, and what specifically is missing>

## Sources already checked - do not re-open them

- <source, what it said, and whether it is cited as [S<n>]>

## Open leads

- <where the next piece of evidence probably is, and why>

## Dead ends - do not rediscover these

- <what was searched and came up empty, or a source that would not open>

## Your contract

1. START BY RE-ESTABLISHING GROUND TRUTH: `cd <WORKTREE> && git log --oneline -10` and read the findings file. Everything committed is kept.
2. Finish ticket <NN> and nothing else.
3. VERIFY: `<VERIFY>` must PASS before you commit.
4. WHEN YOU ARE DONE - in this order:
   1. Commit with `SIGNAL: <CONT_TAG>-DONE` in the body (or `SIGNAL: <CONT_TAG>-BLOCKED: <reason>`). Do not push.
   2. `echo "<the answer, in one line>" > <WS>/state/<CONT_TAG>.summary`
   3. `echo "<NEXT_TAG>" > <WS>/state/<CONT_TAG>.next` - what ticket <NN> was always going to hand off to.
   4. `echo "DONE" > <WS>/state/<CONT_TAG>.status` (or `BLOCKED: <reason>`). LAST.
   5. `bash <WS>/advance.sh <WS> <CONT_TAG>`

CONTEXT - measure with `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` (counts UP) after each commit, after any big search or fetch, and before opening a new group of sources. At <WARN_AT_USED>% used, start nothing new. At <RELAY_AT_USED>% used, hand this ticket on exactly the way it was handed to you, to <CONT_TAG> incremented by one.

Finally, post a 3-5 line summary: what you answered, its confidence, and anything the next session must know.
