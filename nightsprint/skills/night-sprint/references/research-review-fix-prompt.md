Research sprint <SLUG>: REVIEW-FINAL - FIX

AUTONOMOUS RESEARCH RUN. <USER> will NOT answer anything now. Never ask a question - decide each item yourself and say what you decided. ASCII only, no em/en dashes.

Research: <RESEARCH_TITLE>
Workspace: <WS>. You are tag <TAG>. Your finder was <FIND_TAG>.

YOU FIX WHAT IS ALREADY WRITTEN DOWN. Do not run another review. If you believe a finding is wrong, reject it in one line with the reason.

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd <WORKTREE>
Local repo, branch <BRANCH>, no remote.

READ FIRST, and only this much: <WS>/state/<FIND_TAG>.findings.md (your work list), then each findings file as an item needs it.

Connectors are READ ONLY: you may re-open a source to correct a claim; you never send, post, draft, edit or comment on anything.

## STEP 1 - WORK THE LIST

Severity order: BLOCKER, HIGH, MEDIUM, LOW.

- **Correct it** - reword the claim to what the source says, fix the citation, downgrade the confidence, add a second source, remove copied personal data, or move an unanswered question to `## Gaps`. Never strengthen a claim to fit the old Answer: change the Answer instead.
- **Reject it** in one line with the reason.
- **Defer it** - one line to <WS>/state/FOLLOWUPS.md.

## STEP 2 - VERIFY

  <VERIFY>

PASS before you commit. Commit the corrected findings files with `SIGNAL: <TAG>-DONE` in the body. Do not push - there is no remote.

## CONTEXT

Measure: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` (counts UP) every few items. At <WARN_AT_USED>% used, start nothing new. At <RELAY_AT_USED>% used, relay per the CONTEXT RELAY section of <WS>/PLAN.md, carrying the full manifest with your verdict on each item.

## WHEN DONE - in this order

1. Commit (above).
2. `echo "<n fixed, n rejected, n deferred>" > <WS>/state/<TAG>.summary`
3. `echo "<NEXT_TAG>" > <WS>/state/<TAG>.next` - written BEFORE your status.
4. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST.
5. `bash <WS>/advance.sh <WS> <TAG>`

Post a summary as your last message: what you corrected, what you rejected and why, what you deferred.
