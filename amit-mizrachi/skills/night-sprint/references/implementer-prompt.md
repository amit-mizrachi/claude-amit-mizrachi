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
