---
name: address-review
description: "Walk through every review comment on a PR, fix or skip each one, and reply on EACH comment thread indicating \"Fixed in <sha>\" or \"Skipped: <reason>\". Use when the user says \"address review\", \"address PR comments\", \"respond to review\", \"go through review comments\", or provides a PR URL and wants every comment acknowledged."
argument-hint: "[pr-url-or-number]"
---

# Address Review

Walk through every reviewer comment on a PR. For each one: decide to fix or skip, take the action, then **reply on that exact comment thread** so the reviewer sees an explicit acknowledgement on every comment they made.

**The non-negotiable**: every reviewer comment gets a reply. Either "Fixed in <sha>" with a one-line note on what changed, or "Skipped: <reason>". No silent decisions.

## Inputs

- `$1` (optional): PR URL, `<owner>/<repo>#<number>`, or just `<number>`. If empty, resolve from the current branch's open PR via `gh pr view --json url,number,headRepository,...`.

## Steps

### 1. Resolve the PR

```bash
# If $1 is empty, infer from current branch
gh pr view --json number,url,headRefName,baseRefName,headRepository,headRepositoryOwner

# Otherwise parse $1 into owner/repo + number. If user passes just a number,
# assume the current repo (cwd's `gh repo view`).
```

Record `owner`, `repo`, `pr_number` in scratch state. Verify the PR is open. If closed/merged, ask the user before continuing (headless: stop and report it).

### 2. Fetch ALL comments

Two GitHub APIs hold review feedback. Fetch both:

```bash
# Inline code review comments (the ones anchored to a file/line)
gh api "repos/$owner/$repo/pulls/$pr_number/comments" --paginate \
  --jq '.[] | {id, user: .user.login, body, path, line, in_reply_to_id, commit_id, diff_hunk, created_at}'

# General conversation comments on the PR (not inline)
gh api "repos/$owner/$repo/issues/$pr_number/comments" --paginate \
  --jq '.[] | {id, user: .user.login, body, created_at}'

# Pull request reviews - top-level review summaries (APPROVE/REQUEST_CHANGES/COMMENT)
gh api "repos/$owner/$repo/pulls/$pr_number/reviews" --paginate \
  --jq '.[] | select(.body != "" and .body != null) | {id, user: .user.login, state, body, submitted_at}'
```

**Filter rules** before processing:

- **Skip the PR author's own comments** - they're not review feedback.
- **Skip bot comments by default** (`user.type == "Bot"` or login matches `*-bot`, `dependabot`, `coderabbitai`, etc.) UNLESS the user explicitly asked to address bot feedback. Tell the user which bots are skipped so they can override.
- **Collapse threads**: if a comment has `in_reply_to_id`, treat the root comment as the canonical one. Reply on the root.
- **Deduplicate**: if a reviewer repeats themselves across reviews, address once on the most recent occurrence.

Report the count: "Found N inline + M conversation + K review-body comments to address from reviewers: X, Y, Z."

### 3. For EACH comment: decide -> act -> reply

Process comments in order they appear in the PR (file order for inline, chronological for conversation).

#### 3a. Decide fix vs skip

Apply judgment, biased toward the user's review-handling preference: **fix bugs and security, not style nits; prefer consistency with existing code over aggressive refactors**.

| Kind of comment | Default action |
|---|---|
| Bug / correctness issue | Fix |
| Security concern | Fix |
| Crash / runtime error | Fix |
| Missing error handling at a boundary | Fix |
| Test coverage gap on changed code | Fix (add test) |
| Naming / formatting / style preference | Skip (with reason) - unless the team has a linter rule for it |
| Refactor suggestion outside this PR's scope | Skip (with reason) |
| Question / "did you consider X?" | Answer in the reply; only fix if the answer reveals a real issue |
| Praise / "nit:" / "optional:" | Skip (with reason - usually "Optional; leaving as-is") |
| Already addressed by another change | Skip with link to the commit |
| Wrong (reviewer mistaken) | Skip with a polite explanation |

When in doubt, lean toward fixing if it's small + safe; lean toward skipping with a reason if it's structural.

#### 3b. Make the fix (if fixing)

- Read the file and the diff hunk in the comment to understand exactly what's being asked.
- Make the minimum change to address the comment.
- **Do NOT batch unrelated changes** into the same edit - the comment author should be able to read the resulting diff and see only what they asked for.
- After editing, run any obvious smoke check (typecheck / lint if quick) but don't block the workflow on full CI.

Stage the change immediately. Don't accumulate - one commit per logical comment cluster is fine, but each comment must be linkable to a SHA.

#### 3c. Reply on the comment

Use the GitHub API to post the reply on the specific comment thread. Different endpoint per comment kind:

```bash
# Inline code review comment - reply in the same thread
gh api -X POST "repos/$owner/$repo/pulls/$pr_number/comments/$comment_id/replies" \
  -f body="<reply text>"

# General PR conversation comment - post a new issue comment that quotes/references it
gh api -X POST "repos/$owner/$repo/issues/$pr_number/comments" \
  -f body="> $original_comment_first_line_truncated...
@$original_author <reply text>"

# Review body (top-level review with a body) - reply as an issue comment that
# references the review id, since GitHub doesn't expose direct review-body replies
gh api -X POST "repos/$owner/$repo/issues/$pr_number/comments" \
  -f body="Re: [review by @$original_author](https://github.com/$owner/$repo/pull/$pr_number#pullrequestreview-$review_id)

<reply text>"
```

**Reply templates** (keep it terse - one short paragraph, no fluff):

- Fixed:
  ```
  Fixed in <sha-7>: <one-line description of what changed>.
  ```
- Fixed (multi-comment cluster):
  ```
  Fixed in <sha-7> along with the other points above.
  ```
- Skipped (out of scope):
  ```
  Skipped - out of scope for this PR (<one-line reason>). Tracking separately / leaving for a follow-up.
  ```
- Skipped (style preference, no team rule):
  ```
  Skipped - leaning toward consistency with the surrounding code, which uses <pattern>. Happy to revisit if the team standardizes on it.
  ```
- Skipped (disagree):
  ```
  Skipped - <reason the comment is incorrect or the current behavior is intentional>. Can elaborate if useful.
  ```
- Skipped (already done):
  ```
  Already handled in <sha-7> (<brief>).
  ```
- Answer to a question:
  ```
  <Short answer.> Not changing the code unless this points at a real issue.
  ```

### 4. Commit and push

After all fixes are made:

```bash
git add <files touched>
git commit -m "$(cat <<'EOF'
Address review comments

- <bullet per substantive change with reviewer alias>
EOF
)"

git push
```

If commits were created during the loop (one per cluster), just `git push` the final state.

Follow the repo's own commit message convention when it has one. Never `--no-verify`: a hook that fails is a problem to fix, not to skip.

### 5. Final summary

Post one issue-level comment at the end so the reviewer has a TL;DR:

```bash
gh api -X POST "repos/$owner/$repo/issues/$pr_number/comments" \
  -f body="Review addressed:

- $fixed_count comments fixed (latest commit: $latest_sha)
- $skipped_count skipped (reasons in-thread)

Ready for re-review."
```

Then return a concise textual report to the user with: PR URL, fixed count, skipped count, list of skipped comments with reasons (so the user can sanity-check before re-requesting review).

## Hard rules

- **Reply to every reviewer comment.** No silent fixes. If the user wants a true silent mode, they can pass `--silent` (not currently supported - add later if needed).
- **Don't @mention the reviewer in every reply** - GitHub auto-notifies the thread participants; @mentions in every reply are noisy.
- **Don't mark threads as resolved** automatically. The reviewer decides what's resolved when they re-review.
- **Don't push unrelated changes** that snuck into the working tree. `git status` before staging; show the user anything unexpected.
- **Stop and ask** if a reviewer comment is ambiguous and the fix could go two clearly different ways - better to ask once than to fix wrong and have to revert. **With no human in the session** (a background or headless run, such as a night-sprint FIX step), never ask: take the smaller, safer reading, and say in the reply which reading you took.

## Error handling

| Situation | Action |
|---|---|
| `gh` not authenticated | Tell user to run `gh auth login`; stop |
| PR has 0 reviewer comments | Tell user there's nothing to address; stop |
| Reply API returns 403/404 | Likely insufficient token scope or wrong endpoint for comment kind. Fall back to a regular issue comment that quotes the original |
| Fix needs more context than the diff hunk shows | Read the file at the line; if still unclear, ask the user (headless: skip it with the reason) |
| Merge conflict between fixes | Pause, surface the conflict to the user, do not auto-resolve destructively. Headless: keep the earlier fix, skip the later comment with the reason |
