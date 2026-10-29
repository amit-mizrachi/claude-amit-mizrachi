# Coding standards

## Root cause
- Fix the root cause; the fix is permanent.
- A fix that feels hacky: rewrite it as the elegant solution, knowing what you know now.
- Non-trivial change: ask "is there a simpler way?" before presenting it. Skip for simple, obvious fixes.
- Smallest change that solves the problem.

## Bugs and red CI
- Bug report, failing test, red CI run: reproduce from the logs, error or failing test, then fix. Work autonomously.

## Verification
Done means proven.
- Local proof is tight: the named test files for the change (a handful, or a `-t`/`-k` filter), plus lint, typecheck, build.
- Full suites never run on this Mac. CI runs them after the push.
- Behaviour change: diff against main by running the same named test or command on both.
- After the push, report the PR URL and stop. Nobody waits on CI or polls it.

## Delivery
- Commit, push, open a PR. On the default branch, branch first.
- Merging and deploying stay with Amit.

## Reviewing
- Use the review skill of the harness (Codex: `squad-review`, see its AGENTS block).
- Judge the change against the sections above.
