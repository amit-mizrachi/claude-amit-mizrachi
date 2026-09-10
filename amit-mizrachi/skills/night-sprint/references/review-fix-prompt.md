<REPO> - night sprint <SLUG>: <CHECKPOINT REVIEW after ticket <NN> | FINAL REVIEW> - FIX

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - decide each comment yourself and say what you decided. Earn "done" by running the checks (charter #10). ASCII only, no em/en dashes.

Repo: <ABSOLUTE REPO PATH> (<owner/repo>). Toolchain: <ENV SETUP>.
Workspace: <WS>. You are tag <TAG>. Your finder was <FIND_TAG>.

YOU FIX WHAT IS ALREADY WRITTEN DOWN. The review has already happened. <FIND_TAG> ran the quad squad over this sprint's diff and left its findings as inline comments on the PR, with a copy at <WS>/state/<FIND_TAG>.findings.md. Your window is for implementing them, not for reviewing again.

DO NOT RUN `quad-review-squad`. Not to double-check, not "just on the files I touched", not because a finding looks thin. Re-running it is what this two-session split exists to prevent: it would refill your window with five specialist reports and leave you relaying mid-fix, which is exactly the failure the split was designed out of. If you genuinely believe a finding is wrong, reject it in one line with the reason - that is a cheap, allowed answer.

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd <WORKTREE>
Branch <BRANCH>, shared by the whole sprint. You hold it exclusively while you run; no implementer is working right now. Never rebase, force-push, or merge.

READ FIRST, and only this much:
- <WS>/state/<FIND_TAG>.findings.md - the findings, with severity, location and suggested fix.
- The PR comment threads - `gh pr view <PR NUMBER> --json comments,reviews` plus the inline threads. There will be comments from bots and CI as well as <FIND_TAG>'s, and they all count.
- <WS>/LOG.md - what the sprint already deferred on purpose. Do not re-litigate a conscious deferral.
Read source files only as each fix requires. You do not need the whole diff; <FIND_TAG> already did that reading and wrote down the result.

## STEP 1 - ADDRESS EVERY COMMENT

Run the `address-review` skill on the PR. It walks every comment thread, and every thread ends with a reply saying what happened - `Fixed in <sha>` or `Skipped: <reason>`. Nothing is silently ignored, including the ones <FIND_TAG> raised.

Work in severity order: BLOCKER, then HIGH, then MEDIUM, then LOW. If you run low on window, that ordering is what makes the stopping point defensible.

For each one:
- **Fix it** if it is correctness, security, data-integrity, permissions, or a real bug. Make the smallest change that actually resolves it.
- **Skip it** if it is wrong, or a style preference fighting this repo's conventions, or scope this sprint deliberately excluded. Reply with the reason on the thread. A reasoned skip is a legitimate outcome; a silent one is not.
- **Defer it** if it is real but bigger than this sprint. Reply saying so, and append one line to <WS>/state/FOLLOWUPS.md: `<severity> | <file> | <what is wrong> | <why deferred>`. The morning report turns that file into tickets.

<Permissions or access-control changes always need a human (charter #9) - do NOT self-approve one. Reply saying it needs a human, and record it as a manual step below.>

## STEP 2 - VERIFY, COMMIT, PUSH

  <FULL VERIFY COMMAND>

Must be green after your fixes. Never bypass hooks with `--no-verify`. If a fix cannot be made green, revert that one fix, reply on its thread saying so with the failure text, and keep the rest - one stuck finding must not hold the whole pass hostage. Commit and push to <BRANCH>.

## STEP 3 - ANYTHING THAT TURNED OUT TO NEED A HUMAN

If addressing a comment reached something no agent can do - a permissions change, a secret nothing sets, a rotation - append a block to <WS>/state/<TAG>.manual:

  cat >> <WS>/state/<TAG>.manual <<'EOF'
  STEP:     <one line: what a human must do>
  WHY:      <what breaks without it - the concrete failure>
  WHERE:    <the URL, dashboard path or command, as concretely as you know it>
  VALUE:    <ENV_VAR_NAME, or "none" for a pure action>
  LANDS:    <.env | github secret | terraform var | a service | nowhere>
  SECRET:   <yes|no>
  BLOCKING: <yes = the feature does not work at all without it | no>
  EOF

Both tests must pass before you write a block: the shipped feature does not work until a human acts, AND no agent could have done it. If an agent could have - including you, right now - then do it or file it in FOLLOWUPS.md. Never a real secret value.

<FINAL REVIEW ONLY - also do this, after your fixes are green and pushed:
- `gh pr ready <PR NUMBER>` to take it out of draft, and make sure the description reflects everything the sprint delivered.
- Do NOT merge and do NOT deploy - those are <USER>'s, always.
- Do not touch <WS>/state/SETUP.verdict unless your own fixes changed the answer: <FIND_TAG> swept the diff with all of it loaded and already wrote it. If a fix of yours introduced or removed a setup need, update it and say so in your summary.>

## CONTEXT

Measure, do not estimate:
  bash <WS>/context-used.sh --self <CONTEXT_WINDOW>

Check it after every few fixes. At <WARN_AT_USED>% used, start nothing new - finish the fix you are on, do not open a fresh line of investigation, and do not go reading beyond what the current finding needs. At <RELAY_AT_USED>% used, hand off per the CONTEXT RELAY section of <WS>/PLAN.md. Your continuation prompt must carry THE FULL LIST OF FINDINGS WITH YOUR VERDICT ON EACH - fixed (and the sha), skipped (and why), deferred, or still to do - so your successor works only the remainder. The threads you have already replied to are themselves a durable record; that is another reason to reply as you go rather than in a batch at the end.

Several sessions for one review pass is fine and expected. A pass that dies holding un-replied verdicts is not.

## WHEN DONE - all four, in this order

1. Final commit body line: `SIGNAL: <TAG>-DONE` (or `-BLOCKED: <reason>`). Push.
2. echo "<n fixed, n skipped, n deferred, in one line>" > <WS>/state/<TAG>.summary
3. echo "DONE" > <WS>/state/<TAG>.status   (or "BLOCKED: <reason>")
4. If and only if you wrote DONE: bash <WS>/launch.sh <WS> <NEXT_TAG>
   <NEXT_TAG is the next ticket after a checkpoint. For the FINAL pass it is TEST if the user
   opted into a test session. Otherwise it is THE WIZARD GATE, decided by
   <WS>/state/SETUP.verdict:
     NEEDED -> bash <WS>/launch.sh <WS> WIZARD
     NONE   -> launch NOTHING. Write these two instead, and the sprint ends here:
                 echo "SKIPPED: no manual setup" > <WS>/state/WIZARD.status
                 echo "<what was swept, and why nothing came up>" > <WS>/state/WIZARD.summary
               The conductor reads them and writes the morning report.>

Post a summary as your last message: what you fixed, what you skipped and why, what you deferred to follow-ups, and anything that needs a human decision in the morning.
