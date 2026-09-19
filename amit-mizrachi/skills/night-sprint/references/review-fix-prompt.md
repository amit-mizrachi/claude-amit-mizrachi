<REPO> - night sprint <SLUG>: <CHECKPOINT> - FIX

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - decide each item yourself and say what you decided. Earn "done" by running the checks (charter #10). ASCII only, no em/en dashes.

Repo: <REPO_PATH> (<REPO_SLUG>). Toolchain: <TOOLCHAIN>.
Workspace: <WS>. You are tag <TAG>. Your finder was <FIND_TAG>.

YOU FIX WHAT IS ALREADY WRITTEN DOWN. The review has happened. Your window is for implementing its result, not for producing another one.

DO NOT RUN A REVIEW OF ANY KIND. Not `code-review`, not "just on the files I touched", not because a finding looks thin. Re-running it refills your window with specialist reports and leaves you handing off mid-fix, which is the exact failure this split removed. If you believe a finding is wrong, reject it in one line with the reason - that is cheap and allowed.

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd <WORKTREE>
Branch <BRANCH>, shared by the whole sprint. You hold it exclusively; no implementer is running. Never rebase, force-push, or merge.

THE PR NUMBER IS NOT IN THIS PROMPT - the draft PR did not exist when it was written. Get it
once, at the start:

  PR="$(gh pr view --json number -q .number)"

READ FIRST, and only this much:
- **<WS>/state/<FIND_TAG>.findings.md** - the manifest. `ID / SEVERITY / LANE / WHERE / ISSUE / EVIDENCE / ACTION` per item. This is your work list and it is local; you do not need to fetch it from GitHub.
- **<WS>/LOG.md** - what the sprint deferred on purpose. Do not re-litigate a conscious deferral.
- The PR's EXTERNAL threads only - comments from bots, CI, or a human:
    gh pr view "$PR" --json comments,reviews
  <FIND_TAG>'s own consolidated comment is the manifest you already have; do not work it twice.

Read source files only as each fix requires. <FIND_TAG> did the wide reading and wrote down the result.

## STEP 1 - WORK THE LIST

Severity order: BLOCKER, HIGH, MEDIUM, LOW. If you run low on window, that ordering is what makes your stopping point defensible.

- **Fix it** if it is correctness, security, data integrity, permissions, or a real bug. Smallest change that actually resolves it.
- **Reject it** in one line with the reason if it is wrong, or a style preference fighting this repo's conventions, or scope this sprint deliberately excluded. A reasoned rejection is a legitimate outcome; a silent one is not.
- **Defer it** if it is real but bigger than this sprint. One line to <WS>/state/FOLLOWUPS.md: `<severity> | <file> | <what is wrong> | <why deferred>`.

**External threads are different from internal findings, and the difference is explicit.** Every bot, CI and human comment gets a REPLY on its thread saying what happened - `Fixed in <sha>` or `Skipped: <reason>` - because somebody outside this sprint is waiting on it. Internal findings from the manifest need no thread; your summary is their record. Use `address-review` for the external threads only, and only if there are any.

Permissions or access-control changes always need a human (charter #9). Do not self-approve one: reply that it needs a human, and record it as a manual step below.

## STEP 2 - VERIFY, THEN CHECK THE FIX ACTUALLY FIXED IT

  <VERIFY>

Green before you commit, and never `--no-verify`. If one fix cannot be made green, revert THAT fix, record it as rejected with the failure text, and keep the rest - one stuck item must not hold the whole pass hostage.

Then, per item you fixed: **re-read the lines you changed against the manifest's ACTION, and re-run the affected ticket's acceptance criteria.** An edit is not a resolution. This is the step that separates "I changed something near the finding" from "the finding is gone".

Commit and push to <BRANCH>.

## STEP 3 - ANYTHING THAT TURNED OUT TO NEED A HUMAN

If addressing an item reached something no agent can do - a permissions change, a secret nothing sets, a rotation - append a block to <WS>/state/<TAG>.manual:

    STEP:     <one line: what a human must do>
    WHY:      <what breaks without it - the concrete failure>
    WHERE:    <URL, dashboard path or command, as concretely as you know it>
    VALUE:    <ENV_VAR_NAME, or "none" for a pure action>
    LANDS:    <.env | github secret | terraform var | a service | nowhere>
    SECRET:   <yes|no>
    BLOCKING: <yes = the feature does not work at all without it | no>

Both tests before you write one: the shipped feature does not work until a human acts, AND no agent could have done it. If an agent could - including you, right now - do it, or file it in FOLLOWUPS.md. Never a real secret value.

## STEP 4 - FINAL REVIEW ONLY

DELETE THIS WHOLE SECTION when rendering a checkpoint fix. It applies only to FIX-FINAL.

Your fixes are pushed. Now find out whether the branch is actually acceptable, which is not the same question as whether your session finished:

    bash <WS>/accept.sh <WS>

It compares your local HEAD to the pushed head, then reads the required checks GitHub actually ran, and writes `<WS>/state/ACCEPTANCE.verdict`.

- **PASS** -> `gh pr ready "$PR"` to take it out of draft, and make sure the description reflects everything the sprint delivered.
- **FAIL** -> you get ONE bounded repair pass. Read the failing check's log, fix it, push, run `accept.sh` again. If it still fails, leave the PR in DRAFT and write `BLOCKED: CI red - <which checks>` as your status. **Do not take a red PR out of draft and do not report the sprint delivered.** A sprint that says "one lane is red and here is which" is worth more than one that reports 21 green stages over a red branch.
- **UNKNOWN** -> say so plainly in your summary and leave the PR in draft.

**Local green and CI green are not the same thing, and assuming they are has cost this sprint a night.** A formatter difference came back from CI twice and was twice read as a warning-only lint rule. If `<VERIFY>` passes and CI fails on formatting or lint, that mismatch IS the finding: fix the parity - make the local command run what CI runs - and say so in your summary so the next sprint inherits the fix.

Never merge and never deploy. Those are <USER>'s, always.

Do not touch <WS>/state/SETUP.verdict unless your own fixes changed the answer: <FIND_TAG> swept the diff with all of it loaded and already wrote it. If a fix introduced or removed a setup need, update it and say so.

## STEP 5 - FIX-TEST ONLY

DELETE THIS WHOLE SECTION unless you are FIX-TEST, the one bounded repair pass after the tester
found an in-scope failure. Your manifest is <WS>/state/TEST.findings.md and your finder was TEST.

The tester deliberately did NOT run the wizard gate, because a gate that runs before the golden
path passes sends the sprint to the wizard over a broken feature. That gate is yours now, and it
runs only after you have proved the failures are gone.

1. Fix the findings, verify, and push, exactly as STEP 1 and STEP 2 say.
2. **Re-run the golden-path steps that failed.** They are named in <WS>/state/TEST-REPORT.md
   along with how the tester got the stack or suite running. Do not re-walk steps that passed.
3. Rewrite <WS>/state/GOLDEN.verdict with the honest result:
     echo "PASS <n> steps (repaired by <TAG>)" > <WS>/state/GOLDEN.verdict
     echo "FAIL step <n>: <what still breaks>"  > <WS>/state/GOLDEN.verdict
   Append what you re-ran, and its real output, to <WS>/state/TEST-REPORT.md.
4. **Still failing? Stop.** You get one pass, not a loop. Leave the FAIL verdict, write
   `BLOCKED: golden path still failing - <step and error>` as your status, leave `.next` EMPTY,
   and let the morning report say so plainly. A second repair pass is the user's call.
5. Passing? Apply THE WIZARD GATE the tester skipped - the same two tests over every
   <WS>/state/*.manual block:
     TEST 1 - REQUIRED?   the shipped feature does not work until a human acts
     TEST 2 - HUMAN-ONLY? no agent could have done it
   Both, or it is not a stage.
     ANY counts -> echo NEEDED > <WS>/state/SETUP.verdict  and `.next` = WIZARD
     NONE does  -> echo NONE   > <WS>/state/SETUP.verdict
                   echo "SKIPPED: no manual setup" > <WS>/state/WIZARD.status
                   echo "<what was swept, why nothing came up>" > <WS>/state/WIZARD.summary
                   and leave `.next` EMPTY - the sprint ends with you.

## CONTEXT

Measure, do not estimate: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` - percent USED, counting up.

Check it every few fixes. At <WARN_AT_USED>% used, start nothing new: finish the fix you are on, open no fresh line of investigation, read no further than the current item needs. At <RELAY_AT_USED>% used, hand off per the CONTEXT RELAY section of <WS>/PLAN.md. Your continuation prompt must carry THE FULL MANIFEST WITH YOUR VERDICT ON EACH ITEM - fixed (and the sha), rejected (and why), deferred, or still to do - so your successor works only the remainder. Replying to external threads as you go rather than in a batch at the end is what makes that record durable.

Several sessions for one fix pass is fine. A pass that dies holding un-recorded verdicts is not.

## WHEN DONE - in this order

1. Final commit body line: `SIGNAL: <TAG>-DONE` (or `-BLOCKED: <reason>`). Push.
2. `echo "<n fixed, n rejected, n deferred, in one line>" > <WS>/state/<TAG>.summary`
3. `echo "<NEXT_TAG>" > <WS>/state/<TAG>.next` - your successor, written BEFORE your status.
   <NEXT_TAG is the next ticket after a checkpoint. For the FINAL pass it is TEST if the user
   opted into a test session; otherwise it is WIZARD when <WS>/state/SETUP.verdict reads
   NEEDED, and EMPTY when it reads NONE - in which case also write:
     echo "SKIPPED: no manual setup" > <WS>/state/WIZARD.status
     echo "<what was swept, and why nothing came up>" > <WS>/state/WIZARD.summary>
4. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST.
5. `bash <WS>/advance.sh <WS> <TAG>` - it reads the pair you just wrote and starts whatever
   comes next. Run it once and do not second-guess the result.

Post a summary as your last message: what you fixed, what you rejected and why, what you deferred, the acceptance verdict if you ran it, and anything needing a human decision in the morning.
