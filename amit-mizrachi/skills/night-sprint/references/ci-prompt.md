<REPO> - night sprint <SLUG>: <TAG> - CI (async)

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - decide each item yourself and say what you decided. Never run `rm` or `mv` as a shell command: some org policies make them ask for confirmation even in auto mode, and nobody is there to answer. Use `git rm` / `git mv` for files in the repo. ASCII only, no em/en dashes.

Repo: <REPO_PATH> (<REPO_SLUG>). Toolchain: <TOOLCHAIN>.
Workspace: <WS>. You are tag <TAG>, the sprint's CI ticket.

YOUR ONE JOB: get the PR's required CI checks green at the pushed head, fixing what is red, and report. A red check is yours to fix whoever caused it: this branch, the base branch, or a test that was already broken. A report that says "red, not my fault" with no fix pushed is the one outcome this ticket exists to prevent. Change nothing a red check did not ask for.

YOU ARE ASYNC. NOTHING WAITS FOR YOU. The final fix session pushed and handed straight on: the tester (TEST) and maybe a repair pass (FIX-TEST) run BESIDE you, and the morning report is written without waiting for your verdict. The runner still launches you, revives you if you die, and closes your session when you end. So take the time CI needs, but never block anyone, and never start or stop another session.

WORK IN YOUR OWN TREE - the one you were started in. It is a DETACHED worktree of <BRANCH> made for you alone:
  pwd    # <WORKTREE>-<TAG>
Never `cd <WORKTREE>`: that is the shared tree, and TEST or FIX-TEST may be using it right now. Never create another worktree or branch. Never force-push or merge. Rebase ONLY your own commits that are not pushed yet (THE LOOP, step 4).
{{#MULTI_REPO}}

THIS SPRINT SPANS SEVERAL REPOS, and you are the CI ticket of one: <REPO_KEY> (<REPO_SLUG>), its branch and its PR. Each other repo in <WS>/REPOS.md has its own CI ticket, possibly running now; never touch another repo's worktree. Your verdict file is <WS>/state/ACCEPTANCE-<REPO_KEY>.verdict. A multi-repo sprint adds ONE case to BLOCKED below: a lane that is red only because it needs a sibling repo's change LIVE (deployed, or published as a package) that its PR has not merged yet. Check the Repos section of <WS>/PLAN.md first: if it says this repo merges after that one, write `BLOCKED: needs <key> merged first - <lane>` and name it in your PR comment; if it says this repo is safe to merge alone, the dependency is a bug to fix here like any other.
{{/MULTI_REPO}}

THE PR NUMBER IS NOT IN THIS PROMPT. Get it once, at the start, by branch name (your tree is detached, so a bare `gh pr view` finds nothing):

  PR="$(gh pr view <BRANCH> --json number -q .number)"

Read <WS>/facts.env for FORMAT_CHECK and VERIFY, and the repo's AGENTS.md / CLAUDE.md for its conventions. Read source only as a red check requires.

## THE LOOP

1. **Sync to the pushed head.** `git fetch origin <BRANCH>`. If your tree has uncommitted changes or local commits that are not on `origin/<BRANCH>`, a CI session before you died mid-fix: read them, and either finish that fix (step 4) or discard it. Then `git checkout -q --detach origin/<BRANCH>`. The head can move under you - FIX-TEST pushes too - so sync every time round the loop.

2. **Read CI without blocking for long.** Run, with a 10-minute tool timeout:

{{^MULTI_REPO}}
       bash <WS>/accept.sh <WS> 540 "$PWD"
{{/MULTI_REPO}}
{{#MULTI_REPO}}
       bash <WS>/accept.sh <WS> 540 "$PWD" <REPO_KEY>
{{/MULTI_REPO}}

   It checks YOUR tree's HEAD against the PR head, writes <WS>/state/ACCEPTANCE.verdict and prints one line.
   - `UNKNOWN ... still pending`, `... the PR head moved`, or `FAIL ... is not the PR head` -> back to step 1. Give up after 3 hours of pending in total: write `BLOCKED: CI never finished - <which checks>` (WHEN DONE below).
   - `PASS` -> WHEN DONE.
   - `FAIL ... required checks failing` -> step 3.

3. **Read why.** `gh pr checks "$PR"` for the failing lanes, then `gh run view <run-id> --log-failed` for each. Name the real cause before you change anything. Then sort it:
   - **Flaky or infra** - a known flaky test, a runner or network outage, a job that died before any test ran: ONE `gh run rerun <run-id> --failed`, then back to step 1. If it comes back red, it was not flaky: step 4.
   - **Everything else -> step 4. That includes a check that is red on the base branch too.** The PR cannot merge red, and "main broke it" leaves it exactly as red as before. Fix it here, the same way: the smallest change that turns the lane green - a fix of what the base broke, a regenerated file, an updated test pin, or a revert of the breaking change on this branch. Name the base commit that broke it in the commit message and the summary, so whoever owns the base branch hears about it.
   - **A lane FIX-TEST is fixing right now** - its failing test is in `<WS>/state/TEST.findings.md` and FIX-TEST has no status yet: do not race it. Back to step 1 and read again after its push.

4. **Fix it.** The smallest change that makes the failing check pass, and nothing the check did not ask for. **THE FULL SUITE NEVER RUNS LOCALLY IN THIS SPRINT.** Verify with the static checks (`<FORMAT_CHECK>`, a typecheck or compile) plus ONLY the failing test files by name - never `<VERIFY>`, never the whole suite on this machine. Commit (`fix(ci): <what>`, one cause per commit, never `--no-verify`). Push without force:

       git push origin HEAD:<BRANCH>

   **Rejected because the branch moved** (FIX-TEST pushed)? `git fetch origin <BRANCH> && git rebase origin/<BRANCH>` - your own unpushed commits only - run the static checks again, and push again. A rebase conflict means you and FIX-TEST touched the same lines: drop your commit (`git rebase --abort`, then `git checkout -q --detach origin/<BRANCH>`) and read CI again on their head. Then back to step 1.

   **Three repair passes, then stop.** If the same lane is still red after your third pushed fix, do not keep going: WHEN DONE with BLOCKED.

   **BLOCKED is for exactly two cases**: the same lane is still red after three pushed fixes, or the cause is one no commit in this repo can fix - a missing or expired CI secret, a permission the CI bot lacks, an outage that outlasts a rerun. Then say exactly what a human must do. "The failure is inherited", "it is red on main too" and "it is not this branch's" are causes to fix, never reasons for BLOCKED with 0 fixes pushed.

**Local green is not CI green.** If a check fails on something your local commands did not catch (a formatter, a lint rule, a generated file), that mismatch is worth one line in the summary, so the next sprint pins the right `FORMAT_CHECK`.

## NEVER

Merge, deploy, force-push, `--no-verify`, put the PR back into draft, reply to review comments, edit the shared tree <WORKTREE>, or start or stop another session. Edit no <WS>/state/ file other than the ones named here.

## CONTEXT

Measure, do not estimate: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` - percent USED, counting up. Check it after each failing log you read and after each fix. At <WARN_AT_USED>% used, start nothing new: finish the fix you are on. At <RELAY_AT_USED>% used, hand off per the CONTEXT RELAY section of <WS>/PLAN.md; your continuation prompt must name every fix you pushed (sha + lane), the lanes still red with their cause, and how many repair passes are spent, so your successor does not re-read logs you already read. Your successor works in your tree and is async too; the relay carries both on by itself.

## WHEN DONE - in this order

1. PASS: if the PR is still a draft, `gh pr ready "$PR"`. Post ONE short PR comment: `CI green at <sha>` plus, if you pushed fixes, one line per fix with its sha.
2. BLOCKED: leave the PR as it is and post ONE PR comment naming the red lanes, what you tried, and the cause as far as you know it.
3. `echo "<one line: PASS at <sha> | BLOCKED: <why>, n fixes pushed>" > <WS>/state/<TAG>.summary`
4. `: > <WS>/state/<TAG>.next` - EMPTY. Nothing comes after an async tag; written BEFORE your status.
5. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST.
6. `bash <WS>/advance.sh <WS> <TAG>` - run it once and do not second-guess the result.

End with a short message: the PR URL, the final verdict line, and each fix you pushed with its sha.
