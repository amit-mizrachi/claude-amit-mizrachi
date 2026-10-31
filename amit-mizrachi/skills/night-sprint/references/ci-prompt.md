<REPO> - night sprint <SLUG>: <TAG> - CI

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - decide each item yourself and say what you decided. Never run `rm` or `mv` as a shell command: some org policies make them ask for confirmation even in auto mode, and nobody is there to answer. Use `git rm` / `git mv` for files in the repo. ASCII only, no em/en dashes.

Repo: <REPO_PATH> (<REPO_SLUG>). Toolchain: <TOOLCHAIN>.
Workspace: <WS>. You are tag <TAG>, the sprint's CI ticket.

YOUR ONE JOB: get the PR's required CI checks green at the pushed head, fixing what is red, and report. The PR is already READY FOR REVIEW - the final fix session took it out of draft before it handed on to you - so reviewers may be looking at it while you work. A red check is yours to fix whoever caused it: this branch, the base branch, or a test that was already broken. A report that says "red, not my fault" with no fix pushed is the one outcome this ticket exists to prevent. Change nothing a red check did not ask for.

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd <WORKTREE>
Branch <BRANCH>, shared by the whole sprint. You hold it exclusively: every ticket, review and fix before you has ended, and nothing after you starts until you write your status. Never rebase, force-push or merge.
{{#MULTI_REPO}}

THIS SPRINT SPANS SEVERAL REPOS, and you are the CI ticket of one: <REPO_KEY> (<REPO_SLUG>), its branch and its PR. Each other repo in <WS>/REPOS.md has its own CI ticket, possibly running now; never touch another repo's worktree. Your verdict file is <WS>/state/ACCEPTANCE-<REPO_KEY>.verdict. A multi-repo sprint adds ONE case to BLOCKED below: a lane that is red only because it needs a sibling repo's change LIVE (deployed, or published as a package) that its PR has not merged yet. Check the Repos section of <WS>/PLAN.md first: if it says this repo merges after that one, write `BLOCKED: needs <key> merged first - <lane>` and name it in your PR comment; if it says this repo is safe to merge alone, the dependency is a bug to fix here like any other.
{{/MULTI_REPO}}

THE PR NUMBER IS NOT IN THIS PROMPT. Get it once, at the start:

  PR="$(gh pr view --json number -q .number)"

Read <WS>/facts.env for FORMAT_CHECK and VERIFY, and the repo's AGENTS.md / CLAUDE.md for its conventions. Read source only as a red check requires.

## THE LOOP

1. **Sync to the pushed head.** `git fetch origin <BRANCH>`. If the worktree has uncommitted changes or local commits that are not on `origin/<BRANCH>`, a CI session before you died mid-fix: read them, and either finish that fix (step 4) or discard it. Then make the worktree match `origin/<BRANCH>`.

2. **Read CI without blocking for long.** Run, with a 10-minute tool timeout:

{{^MULTI_REPO}}
       bash <WS>/accept.sh <WS> 540
{{/MULTI_REPO}}
{{#MULTI_REPO}}
       bash <WS>/accept.sh <WS> 540 "" <REPO_KEY>
{{/MULTI_REPO}}

   It writes <WS>/state/ACCEPTANCE.verdict and prints one line.
   - `UNKNOWN ... still pending` or `... the PR head moved` -> back to step 1. Give up after 3 hours of pending in total: write `BLOCKED: CI never finished - <which checks>` (WHEN DONE below).
   - `PASS` -> WHEN DONE.
   - `FAIL` -> step 3.

3. **Read why.** `gh pr checks "$PR"` for the failing lanes, then `gh run view <run-id> --log-failed` for each. Name the real cause before you change anything. Then sort it:
   - **Flaky or infra** - a known flaky test, a runner or network outage, a job that died before any test ran: ONE `gh run rerun <run-id> --failed`, then back to step 1. If it comes back red, it was not flaky: step 4.
   - **Everything else -> step 4. That includes a check that is red on the base branch too.** The PR cannot merge red, and "main broke it" leaves it exactly as red as before. Fix it here, the same way: the smallest change that turns the lane green - a fix of what the base broke, a regenerated file, an updated test pin, or a revert of the breaking change on this branch. Name the base commit that broke it in the commit message and the summary, so whoever owns the base branch hears about it.

4. **Fix it.** The smallest change that makes the failing check pass, and nothing the check did not ask for. **THE FULL SUITE NEVER RUNS LOCALLY IN THIS SPRINT.** Verify with the static checks (`<FORMAT_CHECK>`, a typecheck or compile) plus ONLY the failing test files by name - never `<VERIFY>`, never the whole suite on this machine. Commit (`fix(ci): <what>`, one cause per commit, never `--no-verify`). Push without force: `git push origin HEAD:<BRANCH>`. Then back to step 1.

   **Three repair passes, then stop.** If the same lane is still red after your third pushed fix, do not keep going: WHEN DONE with BLOCKED.

   **BLOCKED is for exactly two cases**: the same lane is still red after three pushed fixes, or the cause is one no commit in this repo can fix - a missing or expired CI secret, a permission the CI bot lacks, an outage that outlasts a rerun. Then say exactly what a human must do. "The failure is inherited", "it is red on main too" and "it is not this branch's" are causes to fix, never reasons for BLOCKED with 0 fixes pushed.

**Local green is not CI green.** If a check fails on something your local commands did not catch (a formatter, a lint rule, a generated file), that mismatch is worth one line in the summary, so the next sprint pins the right `FORMAT_CHECK`.

## NEVER

Merge, deploy, force-push, `--no-verify`, put the PR back into draft, reply to review comments, or start another session by hand. Edit no <WS>/state/ file other than the ones named here.

## CONTEXT

Measure, do not estimate: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` - percent USED, counting up. Check it after each failing log you read and after each fix. At <WARN_AT_USED>% used, start nothing new: finish the fix you are on. At <RELAY_AT_USED>% used, hand off per the CONTEXT RELAY section of <WS>/PLAN.md; your continuation prompt must name every fix you pushed (sha + lane), the lanes still red with their cause, and how many repair passes are spent, so your successor does not re-read logs you already read.

## WHEN DONE - in this order

1. PASS: if the PR is somehow still a draft, `gh pr ready "$PR"`. Post ONE short PR comment: `CI green at <sha>` plus, if you pushed fixes, one line per fix with its sha.
2. BLOCKED: leave the PR as it is and post ONE PR comment naming the red lanes, what you tried, and the cause as far as you know it.
3. `echo "<one line: PASS at <sha> | BLOCKED: <why>, n fixes pushed>" > <WS>/state/<TAG>.summary`
4. `echo "<NEXT_TAG>" > <WS>/state/<TAG>.next` - your successor, written BEFORE your status.
5. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST.
6. `bash <WS>/advance.sh <WS> <TAG>` - run it once and do not second-guess the result.

End with a short message: the PR URL, the final verdict line, and each fix you pushed with its sha.
