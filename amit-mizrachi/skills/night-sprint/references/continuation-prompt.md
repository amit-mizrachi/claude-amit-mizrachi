<REPO> - night sprint <SLUG>: ticket <NN> CONTINUED - <TICKET TITLE>

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - make the best call, state it in your summary, and keep going. Earn "done" by running it (charter #10) and report failures faithfully. ASCII only, no em/en dashes.

You are tag <CONT_TAG>. You are NOT starting a new ticket. Ticket <NN> is already partly built: the session before you (<PREV_TAG>) ran out of context and handed it to you with a full window. Its work is already on the branch. Your job is to finish the SAME ticket.

Repo: <ABSOLUTE REPO PATH> (<owner/repo>). Toolchain: <ENV SETUP>.
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

Command: `<FULL VERIFY COMMAND>`
Last known result: <green | which checks fail, with the actual failure text - not a paraphrase>

## What I learned - do not rediscover this

- <decision made, and why - so you do not re-litigate it>
- <approach tried and ruled out, and the reason it failed>
- <the trap, fixture, service or convention that cost the last session time>

## Manual steps found so far

<Anything only a human can do that this ticket ran into - a key to paste, a unit to apply, an
app to register. Already recorded in <WS>/state/<PREV_TAG>.manual; listed here so you do not
record it twice. If you meet more, append them to <WS>/state/<CONT_TAG>.manual in the same
`STEP / WHY / WHERE / VALUE / LANDS / SECRET / BLOCKING` format - the WIZARD session at the end
of the sprint builds a setup script out of every such block. Never a real secret value.>

## Files

Changed so far: <paths>
Next to change: <paths, and what the change is>

## Your contract

1. START BY RE-ESTABLISHING GROUND TRUTH, not by re-planning:
     cd <WORKTREE> && git status --short && git log --oneline -10
   Anything already committed for this ticket is DONE - keep it, do not redo it, do not revert
   it. Read only what you actually need; you have a fresh window but it is not infinite, and
   you may be relayed too.
2. Finish ticket <NN> and nothing else. Do not start the next ticket's work and do not expand
   scope because the ticket looks incomplete on its own - it was always meant to be this size.
3. VERIFY: `<FULL VERIFY COMMAND>` must be green before you commit. Never `--no-verify`.
4. WHEN YOU ARE DONE - all four, in this order:
   1. Commit to <BRANCH> with `SIGNAL: <CONT_TAG>-DONE` in the final commit body (or
      `SIGNAL: <CONT_TAG>-BLOCKED: <reason>`). Push.
   2. echo "<what you finished, in one line>" > <WS>/state/<CONT_TAG>.summary
   3. echo "DONE" > <WS>/state/<CONT_TAG>.status      (or "BLOCKED: <reason>")
   4. If and only if you wrote DONE: bash <WS>/launch.sh <WS> <NEXT_TAG>
      <NEXT_TAG is what ticket <NN> was always going to hand off to. If there is none, skip
      this step - the conductor takes it from here.>

CONTEXT: measure with `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` - the number counts UP,
0 is fresh and 100 is full. At <WARN_AT_USED>% used, start nothing new: finish what you are on
and stop widening your reading. At <RELAY_AT_USED>% used, relay this ticket on exactly the way it
was relayed to you - see the CONTEXT RELAY section of <WS>/PLAN.md. A ticket may take as many
sessions as it needs, and being the third or fourth in a chain is not a sign anything is wrong.

You are a continuation, so one thing deserves your attention more than it did your predecessor's:
you inherited a written handoff instead of a conversation. Read it once, act on it, and do not
re-derive it. If you find your window filling on re-reading what this prompt already told you,
that is the failure the relay exists to prevent, happening anyway.

Finally, post a 3-5 line summary: what you finished, what you decided on your own, and anything the next session must know.
