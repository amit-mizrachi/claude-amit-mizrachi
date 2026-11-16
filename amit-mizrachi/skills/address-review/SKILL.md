---
name: address-review
description: "Address the review comments on a GitHub pull request: read every unresolved inline thread, review body and PR comment, verify each against the code, apply the fixes that are needed, push, and reply on every comment saying what happened (Fixed in <sha> / Applied in <sha> / Skipped / Needs a human) with the reasoning. Use when the user runs /address-review, asks to address, answer or respond to PR review comments, or when night-sprint hands over external bot and human threads."
argument-hint: "[PR number or URL; defaults to the current branch's PR]"
---

# address-review

Every comment someone left on the PR gets an answer on GitHub, and every comment that is right gets fixed. A reasoned "skipped" is a fine outcome. Leaving a comment unanswered is not.

## Step 1 - Resolve the PR and get onto its branch

- PR = the argument (number or URL), or else `gh pr view --json number` for the current branch. If there is none, say so and stop.
- `gh pr view <n> --json number,url,state,headRefName,baseRefName,headRepositoryOwner,headRepository,isCrossRepository`. If the PR is merged or closed, ask before going on.
- Work on the PR's head branch, up to date with its remote (`git fetch` then `git status`). If this checkout is on a different branch, or has unrelated uncommitted changes, add a worktree for the head branch (`git worktree add <dir> <headRefName>`). Never stash or switch branches under the user.
- A cross-repo (fork) PR may not accept pushes. If the push in Step 4 is refused, still reply on every comment, and say that the fixes are local only.

## Step 2 - Collect every comment to address

Replace `OWNER`, `REPO` and `N` with real values, and get your login with `gh api user --jq .login`.

**Inline review threads** (page with `after:` if `hasNextPage`):

```bash
gh api graphql -f query='
query { repository(owner:"OWNER", name:"REPO") { pullRequest(number:N) {
  reviewThreads(first:100) { pageInfo { hasNextPage endCursor } nodes {
    id isResolved isOutdated path line
    comments(first:50) { nodes { databaseId author { login } body url createdAt } } } } } } }'
```

**Review bodies**: `gh api repos/OWNER/REPO/pulls/N/reviews --paginate`, keeping reviews whose `body` is not empty.

**PR conversation comments**: `gh api repos/OWNER/REPO/issues/N/comments --paginate`.

Then filter:

- Skip resolved threads.
- Skip anything whose newest comment is already yours, or that a later comment of yours quotes or links. It has been answered.
- Skip your own comments.
- Comments from status-only bots (deploy previews, coverage summaries with no failure, changelog bots) are not addressed. List them in the report, but do not reply.
- Everything else is addressed: every human comment, and every bot comment that asks for a change or reports a problem, including CI and lint bots and AI reviewers.

If nothing is left, report that and stop.

## Step 3 - Decide each one

Read the code each comment points at, as it is **now** on the head branch. An outdated thread may already be fixed. Decide one outcome per comment:

| Outcome | When |
|---|---|
| **Fixed** | A real bug, security, data-integrity or correctness problem, and you fixed it. |
| **Applied** | A valid suggestion (naming, clarity, structure, a test, docs) that you made. |
| **Already fixed** | The code at head already resolves it. Cite the commit. |
| **Skipped** | The claim is wrong, it is a preference that conflicts with this repo's conventions, or it is out of this PR's scope. Give the concrete reason. |
| **Needs a human** | Permissions, access control or visibility rules, a product decision, or a secret or setting no agent can change. Never apply these yourself. |
| **Answered** | It is a question. Answer it from the code. |

Do not apply a suggestion just because a reviewer wrote it, and do not dismiss one just because a bot wrote it. Verify the claim first. When several comments raise the same issue, fix it once and answer each of them.

## Step 4 - Apply, check, push

- Make the fixes in severity order, each as small as it can be while still resolving the comment.
- Check: the repo's formatter or lint check, its typecheck, and the tests that cover what you changed. If a caller such as night-sprint gave its own check rules, follow those instead. If one fix cannot be made green, revert it and change its outcome to Skipped with the failure text.
- Commit. One commit is fine, or one per logical fix when that makes the replies clearer. Name the addressed comments in the message, then push to the PR's head branch.
- Never force-push, never use `--no-verify`, never push to the base branch, and never rewrite commits that are already pushed.

Post replies only **after** the push succeeds, so every `<sha>` you cite exists on GitHub.

## Step 5 - Reply on every comment

Reply format: the outcome, then the reasoning in one to three sentences, saying what changed and why or why not.

- `Fixed in <short-sha>: <what was wrong and what changed>.`
- `Applied in <short-sha>: <what changed>.`
- `Already fixed in <short-sha>: <where>.`
- `Skipped: <reason>.`
- `Needs a human: <what decision or action, and why an agent should not do it>.`
- `<answer>` for questions.

Where to post each reply:

- **Inline thread**: reply in the thread, on its first comment:
  `gh api -X POST repos/OWNER/REPO/pulls/N/comments/<first comment databaseId>/replies -f body="..."`
- **Review body or PR conversation comment**: there is no thread to reply in. Post one PR comment per addressed comment. Start it with `> ` and the first line of the original, plus a link to it, then the reply: `gh pr comment N --body-file <file>`.

Do not resolve threads; the reviewer resolves them. Do not edit or delete anyone else's comments.

## Step 6 - Report

One table row per addressed comment: author, location (file:line, or "review" / "conversation"), outcome, `<sha>`, and the reply link. Then list:

- the bot comments you left without a reply;
- the checks you ran and their results;
- the "Needs a human" items.
