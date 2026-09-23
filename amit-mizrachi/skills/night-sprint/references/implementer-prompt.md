<REPO> - night sprint <SLUG>: ticket <NN> - <TICKET_TITLE>

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - make the best call, state it in your summary, keep going. Do not stop until this ONE ticket is implemented, verified green, committed and handed off. Earn "done" by running it (charter #10) and report failures faithfully. ASCII only, no em/en dashes.

Repo: <REPO_PATH> (<REPO_SLUG>). Toolchain: <TOOLCHAIN>.
Workspace: <WS>. You are tag <TAG> (ticket <NN> of <TOTAL>).

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd <WORKTREE>
This worktree and branch <BRANCH> already exist and are shared by the whole sprint. Earlier tickets have landed their commits here. You are the ONLY session touching it right now. Never create a branch, never open a second worktree, never rebase or force-push, never merge.

READ FIRST:
- <WS>/PLAN.md - goal, ticket order, verify command, review cadence.
- <WS>/tickets/<NN>-<slug>.md - YOUR ticket. Its acceptance criteria are the definition of done.
- <CONVENTIONS> - plus the 2-4 existing files whose pattern you should mirror.
- `git log --oneline -15` in the worktree - what earlier tickets actually landed, which is more current than the plan.

YOUR TASK: implement ticket <NN> and nothing else. Do not start the next ticket's work, do not "while I'm here" refactor past what your ticket needs, do not touch anything a later ticket owns. If a real problem in an earlier ticket's work blocks you, fix the minimum needed and say so.

VERIFY: `<VERIFY>` must be green before you commit. Never `--no-verify`. If a pre-existing failure is unrelated to your ticket, note it in your summary rather than silently absorbing it.

**LOCAL GREEN IS NOT CI GREEN.** If this repo's CI runs a formatter or lint gate that `<VERIFY>` does not, you will pass locally and turn the PR red. Run `<FORMAT_CHECK>` too, and if you find a gate CI runs that the verify command misses, say so in your summary - that mismatch is worth more to the sprint than the ticket.

<GOTCHAS>

## Anything only a human can do, written down the moment you hit it

Your ticket may need an API key nobody pasted, a terraform unit applied, a third-party app registered, a flag switched, a migration run against a real database. You cannot do those and must not try - but the morning report hands them to <USER>, and it can only use what you wrote down. Append a block per item to <WS>/state/<TAG>.manual as you find it:

    STEP:     <one line: what a human must do>
    WHY:      <what breaks without it - the concrete failure, not "for configuration">
    WHERE:    <URL, dashboard path or command, as concretely as you know it>
    VALUE:    <ENV_VAR_NAME, or "none" for a pure action>
    LANDS:    <.env | github secret | terraform var | a service | nowhere>
    SECRET:   <yes|no>
    BLOCKING: <yes = the feature does not work at all without it | no>

ONLY IF THE SHIPPED FEATURE DOES NOT WORK UNTIL A HUMAN DOES IT. A key the deployed feature needs counts. A value somebody fills into `.env.local` to run the app on their laptop does not, and neither does drift that was already broken on the base ref.

Be concrete about WHERE. "You need a Monday API key" sends the user hunting; "Monday -> Developer centre -> your app -> OAuth -> client secret" does not. If you walked that path while building, it is worth more than anything a later session can reconstruct from the diff. If you only know the hostname, say only the hostname - never invent a menu you did not see.

NEVER put a real secret value in that file, a commit, or your summary. Names and paths only.

## Your window is yours, and nothing else can touch it

A ticket may take more than one session. That is the plan, not a failure: this sprint would rather run three fresh sessions on a ticket than one exhausted one.

**Nobody is watching this number but you.** There is no way to send a message into a running session. No reminder is coming and no script will hand your ticket on for you. A session that does not measure itself runs until the harness auto-compacts it, losing the reasoning that mattered, and at worst dies mid-edit having written none of it down.

Measure, never estimate:

  bash <WS>/context-used.sh --self <CONTEXT_WINDOW>

The number counts UP: 0 is fresh, 100 is full, exactly as `/context` reports it. Believe it over your own sense of how much room is left; that sense is consistently wrong.

MEASURE AT EVERY ONE OF THESE: after each commit; after any subagent or fan-out returns; after any search, build or test that printed a lot; before opening a group of files you have not read; before starting the next acceptance criterion; whenever you cannot remember the last check.

**<WARN_AT_USED>% used - START NOTHING NEW.** No new subsystem, no refactor past your ticket, no wide reading of files you have not opened. Drive what you are on right now to a committed state. The expensive mistake is not running out of window, it is running out halfway through something.

**<RELAY_AT_USED>% used - HAND THE TICKET ON.** Stop taking new work and spend the rest of the window handing off well. Your successor should inherit a good handoff and a nearly full window.

Two exceptions, only these two. **One command from green: FINISH IT** - a split that saves nothing costs a whole session of re-reading. **Not one file changed yet: do NOT hand off** - your successor would start where you did, minus your reading, which is how a ticket loops all night without being built. Keep going until you have something real to pass on. Still reading at <CEILING_USED>% used? Hand off anyway, and say plainly in the continuation prompt that this ticket is bigger than the plan thought.

THE HANDOFF, in this order:
  1. Commit and push what you have. Not green? Commit as WIP whose body says `SIGNAL: <TAG>-RELAYED` and names the failing checks. Never stash, never revert.
  2. Fill <WS>/continuation-prompt.md into <WS>/prompt-<TAG>c2.txt: what landed, which acceptance criteria are met and which are not, the real verify output, files changed and files next, every decision and dead end so your successor does not rediscover them. Your successor starts empty and cannot read this conversation - assume it knows nothing.
  3. `echo "<what landed, what is left>" > <WS>/state/<TAG>.summary`
  4. `echo "<TAG>c2" > <WS>/state/<TAG>.next`
  5. `echo "RELAYED: <TAG>c2" > <WS>/state/<TAG>.status` - RELAYED, never DONE. The ticket is still in flight and DONE would release the next one.
  6. `bash <WS>/advance.sh <WS> <TAG>`

Then post your summary and stop. Your successor owns the ticket now, and owns what comes after it.

## Found something real that is not your ticket?

Do not fix it and do not leave it unsaid. One line:

  echo "<severity> | <file or area> | <what is wrong> | <why it is not this ticket>" >> <WS>/state/FOLLOWUPS.md

The morning report turns that file into tickets. This is the pressure valve for "while I'm here".

## WHEN YOU ARE DONE - in this order, and the order matters

1. Commit to <BRANCH> with `SIGNAL: <TAG>-DONE` in the final commit body (or `SIGNAL: <TAG>-BLOCKED: <one-line reason>`). Push.
2. `echo "<what you built, in one line>" > <WS>/state/<TAG>.summary`
3. `echo "<NEXT_TAG>" > <WS>/state/<TAG>.next` - written BEFORE your status. Leave it empty if nothing follows you.
4. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). **LAST**, because the status is what releases the chain, and it must never be read before `.next` is correct.
5. `bash <WS>/advance.sh <WS> <TAG>` - the one thing that starts whatever comes next. It reads the pair you just wrote, claims the tag atomically, and is a harmless no-op if the watcher got there first. Run it once and do not second-guess it.

If you are BLOCKED: still do 1-4 (with BLOCKED), push whatever you have so the work is not lost, then run step 5 - it will correctly launch nothing and let the conductor decide. A clear blocker reported at 2am is worth far more than a silent retry loop.

Finally, post a 3-5 line summary: what landed, what you decided on your own, what you deferred, and anything the next session must know.
