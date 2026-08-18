<REPO> - night sprint <SLUG>: <CHECKPOINT REVIEW after ticket <NN> | FINAL REVIEW>

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - judge each finding yourself, fix what is worth fixing, and record what you rejected and why. Earn "done" by running the checks (charter #10). ASCII only, no em/en dashes.

Repo: <ABSOLUTE REPO PATH> (<owner/repo>). Toolchain: <ENV SETUP>.
Workspace: <WS>. You are tag <TAG>.

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd <WORKTREE>
Branch <BRANCH>, shared by the whole sprint. You hold it exclusively while you run; no implementer is working right now. Never rebase, force-push, or merge.

READ FIRST: <WS>/PLAN.md (sprint goal + ticket list), <WS>/LOG.md (what has landed so far and what was deferred), and `git log --oneline` on the branch.

SCOPE: <the accumulated diff from <BASE REF> to HEAD - tickets <NN..NN>>. Review what this sprint has built so far, as one body of work, not ticket by ticket.

STEP 1 - QUAD REVIEW. Run the `quad-review-squad` skill over that diff. It fans out the specialist reviewers in parallel and consolidates into one prioritised plan. This is the one place in a night sprint where parallelism is correct - it is read-only analysis, not code being written.

STEP 2 - TRIAGE, then FIX. You are the deciding engineer, not a stenographer. For each finding:
- Correctness, security, data-integrity, or permissions issue -> FIX it now.
- Real but out of this sprint's scope -> leave it, and record it as a follow-up.
- Wrong, or a style preference that fights the repo's conventions -> reject it, with the reason.
Do not blanket-apply every suggestion; a review that rewrites a working night of code is a worse outcome than the findings it fixed.
<Permissions or access-control changes always need a human (charter #9) - do NOT self-approve one. Record it and flag it for the morning.>

STEP 3 - ADDRESS PR COMMENTS. If the PR exists and has review comments (bot, CI, or human), run the `address-review` skill: fix or skip each one and reply on EACH thread with "Fixed in <sha>" or "Skipped: <reason>". If the PR has no comments yet, skip this step and say so.

STEP 4 - VERIFY. `<FULL VERIFY COMMAND>` must be green after your fixes. Do not bypass hooks with --no-verify. Commit and push to <BRANCH>.

<FINAL REVIEW ONLY - also do this:
- Re-read every ticket in <WS>/tickets/ against what actually landed and call out any acceptance criterion that is NOT met. This is the last honest check before the user sees it.
- Take the PR out of draft (`gh pr ready`) and make sure the description reflects everything the sprint delivered.
- Do NOT merge and do NOT deploy - those are <USER>'s, always.>

WHEN DONE - all four, in this order:
1. Final commit body line: `SIGNAL: <TAG>-DONE` (or `-BLOCKED: <reason>`). Push.
2. echo "<findings fixed vs rejected vs deferred, in one line>" > <WS>/state/<TAG>.summary
3. echo "DONE" > <WS>/state/<TAG>.status   (or "BLOCKED: <reason>")
4. If you wrote DONE and there is a next tag: bash <WS>/launch.sh <WS> <NEXT_TAG>
   <NEXT_TAG is the next ticket after a checkpoint; for the final review it is TEST if the
   user opted into a test session, otherwise omit this step - the conductor closes the sprint.>

Post a summary as your last message: findings by severity, what you fixed, what you rejected and why, what you deferred to follow-ups, and anything that needs a human decision in the morning.
