<REPO> - night sprint <SLUG>: ticket <NN> - <TICKET TITLE>

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - make the best call, state it in your summary, and keep going. Do not stop until this ONE ticket is implemented, verified green, committed, and handed off. Earn "done" by running it (charter #10) and report failures faithfully. ASCII only, no em/en dashes.

Repo: <ABSOLUTE REPO PATH> (<owner/repo>). Toolchain: <ENV SETUP>.
Workspace: <WS>. You are tag <TAG> (ticket <NN> of <TOTAL>).

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd <WORKTREE>
This worktree and its branch <BRANCH> already exist and are shared by the whole sprint. Tickets before you have already landed their commits here. You are the ONLY session touching it right now. Never create a branch, never open a second worktree, never rebase or force-push, never merge anything.

READ FIRST:
- <WS>/PLAN.md - the sprint: goal, ticket order, verify command, review cadence.
- <WS>/tickets/<NN>-<slug>.md - YOUR ticket. Its acceptance criteria are the definition of done.
- <REPO CONVENTIONS FILE(S)> - plus the 2-4 existing files whose pattern you should mirror.
- `git log --oneline -15` in the worktree - what the earlier tickets actually landed, which is more current than the plan.

YOUR TASK: implement ticket <NN> and nothing else. Do not start the next ticket's work, do not "while I'm here" refactor beyond what your ticket needs, and do not touch anything a later ticket owns. If you find a real problem in an earlier ticket's work that blocks you, fix the minimum needed and say so in your summary.

VERIFY: `<FULL VERIFY COMMAND>` must be green before you commit. Do not bypass git hooks with --no-verify. If a pre-existing failure is unrelated to your ticket, note it in your summary rather than silently absorbing it.

<GOTCHAS: the 2-4 traps that would otherwise cost this session hours - conventions, env setup, a fixture that must be regenerated, a service that must be running.>

WRITE DOWN ANYTHING ONLY A HUMAN CAN DO, THE MOMENT YOU HIT IT. Your ticket may need an API key nobody has pasted, a terraform unit applied, a third-party app registered, a flag switched on, a migration run against a real database. You cannot do those and you must not try - but the LAST session of this sprint builds a setup wizard out of them, and it can only use what you wrote down. Append a block to <WS>/state/<TAG>.manual for each one, as you find it:

  cat >> <WS>/state/<TAG>.manual <<'EOF'
  STEP:     <one line: what a human must do>
  WHY:      <what breaks without it - the concrete failure, not "for configuration">
  WHERE:    <the URL, dashboard path or command, as concretely as you know it>
  VALUE:    <ENV_VAR_NAME, or "none" for a pure action>
  LANDS:    <.env | github secret | terraform var | a service | nowhere>
  SECRET:   <yes|no>
  BLOCKING: <yes = the feature does not work at all without it | no>
  EOF

ONLY WRITE A BLOCK IF THE SHIPPED FEATURE DOES NOT WORK UNTIL A HUMAN DOES IT. That is the whole test. A key the deployed feature needs counts; a value somebody fills into `.env.local` to run the app on their laptop does not, and neither does config drift that was already broken on the base ref before your ticket existed. Blocks that fail this test become wizard stages that configure nothing, and the user reads a script in the morning that does not turn anything on.

Be concrete about WHERE. "You need a Monday API key" sends the user hunting; "Monday -> Developer centre -> your app -> OAuth -> client secret" does not. If you actually walked the path while building, that path is worth more than anything the final session can reconstruct from the diff. If you only know the hostname, say only the hostname - never invent a menu you did not see.

NEVER put a real secret value in that file, in a commit, or in your summary. Names and paths only.

CONTEXT - A TICKET MAY TAKE MORE THAN ONE SESSION, AND THAT IS THE PLAN, NOT A FAILURE. This sprint would rather run three fresh sessions on a ticket than one exhausted one, so the handoff line is early and you should expect to reach it. Measure, never estimate:

  bash <WS>/context-used.sh --self <CONTEXT_WINDOW>

The number counts UP: 0 is a fresh session, 100 is a full one, exactly as `/context` reports it. Check it after any large read, long build, or subagent fan-out, and believe it over your own sense of how much room is left. There are two rungs.

RUNG 1 - <WARN_AT_USED>% USED: START NOTHING NEW. You are still comfortable, but not comfortable enough to open a new front. Do not begin a new subsystem, do not start a refactor beyond what your ticket needs, do not go reading widely through files you have not already opened. DO drive whatever you are on right now to a finished, committed state. The expensive mistake is not running out of window - it is running out halfway through something, because a half-finished thing is what makes a handoff expensive. The conductor may send you this same reminder; it is advice, not an instruction to stop.

RUNG 2 - <RELAY_AT_USED>% USED: HAND THE TICKET ON. Stop taking new work and spend the rest of the window handing off well - you still have most of it, and that is deliberate: your successor should inherit a good handoff and a nearly full window. Two exceptions. If you are one command from green, FINISH IT - a split that saves nothing costs the sprint a whole session of re-reading. And if you have not yet changed a single file, do NOT hand off: your successor would start exactly where you did, minus your reading, which is how a ticket loops all night without being built. Keep going in that case, and relay once you have something real to pass on.

The conductor watches the same number and may send you the relay instruction first; either way the procedure is identical:

  1. Commit and push what you have. If it is not green, commit it anyway as WIP whose body says `SIGNAL: <TAG>-RELAYED` and names the failing checks. Never stash, never revert.
  2. Fill <WS>/continuation-prompt.md into <WS>/prompt-<TAG>c2.txt: what landed, which acceptance criteria are met and which are not, the real verify output, the files changed and the ones next, every decision and dead end so your successor does not rediscover them, and that it must launch <NEXT_TAG> when the ticket is finally green. Your successor starts empty and cannot read this conversation - assume it knows nothing.
  3. echo "<what landed, what is left>" > <WS>/state/<TAG>.summary
  4. echo "RELAYED: <TAG>c2" > <WS>/state/<TAG>.status   (RELAYED, never DONE - the ticket is still in flight, and DONE would let the sprint move on with your work unfinished)
  5. bash <WS>/launch.sh <WS> <TAG>c2

FOUND SOMETHING REAL THAT IS NOT YOUR TICKET? Do not fix it and do not leave it unsaid. One line:
  echo "<severity> | <file or area> | <what is wrong> | <why it is not this ticket>" >> <WS>/state/FOLLOWUPS.md
The morning report turns that file into tickets. This is the pressure valve for "while I'm here" - use it instead of expanding your ticket at 3am.

WHEN YOU ARE DONE - do all four, in this order:

1. Commit to <BRANCH>. Put a line in the final commit body:
     SIGNAL: <TAG>-DONE
   (or `SIGNAL: <TAG>-BLOCKED: <one-line reason>` if you truly cannot finish). Push.
2. Write your one-line ledger entry - what you actually built, in plain words:
     echo "<what you did in one line>" > <WS>/state/<TAG>.summary
3. Write your status LAST, because it is what releases the next session:
     echo "DONE" > <WS>/state/<TAG>.status
   or, if blocked:
     echo "BLOCKED: <reason>" > <WS>/state/<TAG>.status
4. If and only if you wrote DONE, hand off to the next ticket:
     bash <WS>/launch.sh <WS> <NEXT_TAG>
   That script claims the tag atomically - if the conductor already launched it, the script
   simply says so and exits. Run it exactly once and do not second-guess the result.
   <If this is the last ticket before a review checkpoint, NEXT_TAG is the reviewer's tag.>
   <If there is no next tag, skip this step - the conductor takes it from here.>

If you are blocked: still do steps 1-3 (with BLOCKED), push whatever you have so the work is not lost, and do NOT launch the next ticket - the conductor decides what happens next. A clear blocker reported at 2am is worth far more than a silent retry loop.

Finally, post a 3-5 line summary as your last message: what landed, what you decided on your own, what you deferred, and anything the next session must know.
