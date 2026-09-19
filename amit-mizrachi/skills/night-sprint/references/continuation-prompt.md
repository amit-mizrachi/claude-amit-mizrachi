<REPO> - night sprint <SLUG>: ticket <NN> CONTINUED - <TICKET_TITLE>

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - make the best call, state it in your summary, keep going. Earn "done" by running it (charter #10) and report failures faithfully. ASCII only, no em/en dashes.

You are tag <CONT_TAG>. You are NOT starting a new ticket. Ticket <NN> is already partly built: <PREV_TAG> ran out of context and handed it to you with a full window. Its work is on the branch. Your job is to finish the SAME ticket.

Repo: <REPO_PATH> (<REPO_SLUG>). Toolchain: <TOOLCHAIN>.
Workspace: <WS>. Predecessor: <PREV_TAG>.

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd <WORKTREE>
Branch <BRANCH>, shared by the whole sprint. You are the ONLY session touching it right now. Never create a branch, never open a second worktree, never rebase or force-push, never merge.

## What already landed

<Commits <PREV_TAG> pushed for this ticket - sha + subject, one per line. Say which are complete and which are WIP.>

## Where the ticket stands

Ticket file: <WS>/tickets/<NN>-<slug>.md - its acceptance criteria are still the definition of done.

MET already:
- <criterion, and the commit that met it>

NOT met yet - this is your work:
- <criterion, and what specifically remains>

## Verify status right now

Command: `<VERIFY>`
Last known result: <green | which checks fail, with the actual failure text, not a paraphrase>

## What I learned - do not rediscover this

- <decision made, and why - so you do not re-litigate it>
- <approach tried and ruled out, and why it failed>
- <the trap, fixture, service or convention that cost the last session time>

## Manual steps found so far

<Anything only a human can do that this ticket ran into. Already recorded in <WS>/state/<PREV_TAG>.manual; listed here so you do not record it twice. If you meet more, append them to <WS>/state/<CONT_TAG>.manual in the same `STEP / WHY / WHERE / VALUE / LANDS / SECRET / BLOCKING` format. Never a real secret value.>

## Files

Changed so far: <paths>
Next to change: <paths, and what the change is>

## Your contract

1. START BY RE-ESTABLISHING GROUND TRUTH, not by re-planning:
     cd <WORKTREE> && git status --short && git log --oneline -10
   Anything already committed for this ticket is DONE - keep it, do not redo it, do not revert it. Read only what you actually need.
2. Finish ticket <NN> and nothing else. Do not start the next ticket's work and do not expand scope because the ticket looks incomplete on its own - it was always meant to be this size.
3. VERIFY: `<VERIFY>` must be green before you commit. Never `--no-verify`. Run `<FORMAT_CHECK>` too: local green is not CI green, and a formatter gate CI runs that the verify command misses will turn the PR red after you have reported success.
4. WHEN YOU ARE DONE - in this order:
   1. Commit to <BRANCH> with `SIGNAL: <CONT_TAG>-DONE` in the final commit body (or `SIGNAL: <CONT_TAG>-BLOCKED: <reason>`). Push.
   2. `echo "<what you finished, in one line>" > <WS>/state/<CONT_TAG>.summary`
   3. `echo "<NEXT_TAG>" > <WS>/state/<CONT_TAG>.next` - what ticket <NN> was always going to hand off to. Empty if nothing follows.
   4. `echo "DONE" > <WS>/state/<CONT_TAG>.status` (or `BLOCKED: <reason>`). LAST.
   5. `bash <WS>/advance.sh <WS> <CONT_TAG>`

CONTEXT - NOBODY IS WATCHING YOUR WINDOW BUT YOU. There is no way to send a message into a running session, so no reminder is coming and no script will hand this ticket on for you. Measure with `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` - the number counts UP, 0 is fresh and 100 is full - after each commit, after any fan-out returns, after any noisy build or search, before opening a group of unread files, and whenever you cannot remember the last check.

At <WARN_AT_USED>% used, start nothing new: finish what you are on, stop widening your reading. At <RELAY_AT_USED>% used, hand this ticket on exactly the way it was handed to you - see the CONTEXT RELAY section of <WS>/PLAN.md - to <CONT_TAG> incremented by one. A ticket may take as many sessions as it needs; being third or fourth in a chain is not a sign anything is wrong.

You are a continuation, so one thing deserves more of your attention than it did your predecessor's: you inherited a written handoff instead of a conversation. Read it once, act on it, do not re-derive it. If you find your window filling on re-reading what this prompt already told you, that is the failure the relay exists to prevent, happening anyway.

Finally, post a 3-5 line summary: what you finished, what you decided on your own, and anything the next session must know.
