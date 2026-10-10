<REPO> - night sprint <SLUG>: <CHECKPOINT> - FIND

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - judge each finding yourself and record it. ASCII only, no em/en dashes.

Repo: <REPO_PATH> (<REPO_SLUG>). Toolchain: <TOOLCHAIN>.
Workspace: <WS>. You are tag <TAG>. Every finding of this sprint is fixed once, at the end, by <FIX_TAG>.

DO NOT RUN TESTS. THE FULL SUITE NEVER RUNS LOCALLY IN THIS SPRINT - PR CI RUNS IT, AND THE CI WATCHER FIXES WHAT IS RED. A finder never runs any test, at any checkpoint. Find by reading the diff.

YOU FIND. YOU DO NOT FIX - not one file, not the verify command, not a commit, even when a fix looks like a one-liner. The fixing is a separate step because a session that consolidates reviews AND edits code spends its window twice and dies mid-triage, losing the triage.

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd "$(cat <WS>/state/<TAG>.cwd 2>/dev/null || echo <WORKTREE>)"

REVIEWS IN THIS SPRINT ARE ASYNC. A checkpoint review (REVIEW-C<n>) does not stop the sprint: you
were launched in a read-only SNAPSHOT worktree, detached at the tip of <BRANCH> as it stood when
you started, while the next tickets keep building elsewhere. Review that snapshot as it is -
never pull, check out, commit or push in it. Nothing you find is fixed now; you write it down,
REVIEW-FINAL carries what is still true forward, and <FIX_TAG> fixes all of it at the end. That
is what lets nobody wait on a review. REVIEW-FINAL itself runs in <WORKTREE> on <BRANCH>, after
every ticket and every checkpoint review has ended, and only reads it too. Never rebase,
force-push, or merge.

THE PR NUMBER IS NOT IN THIS PROMPT, because the draft PR does not exist at kickoff when this
prompt is written. Discover it once, at the start, and use it everywhere below. Name the branch:
a snapshot worktree is detached, and a bare `gh pr view` there finds nothing:

  PR="$(gh pr view <BRANCH> --json number -q .number)"

If that comes back empty the PR has not been opened yet. Say so in your summary, write the
manifest anyway, and skip only the posting step - the manifest is the deliverable.

READ FIRST: <WS>/PLAN.md (goal + tickets), <WS>/LOG.md (what landed, and what the sprint already deferred on purpose - never re-raise a conscious deferral), and `git log --oneline` on the branch.

SCOPE: <SCOPE>. Review it as one body of work.

## STEP 1 - REVIEW, WITH THE LANES THIS DIFF ACTUALLY NEEDS

Run the `code-review` skill. **Correctness is always on.** Then add a lane only if the diff gives it something to find:

| Lane | Add it when the diff |
|---|---|
| correctness / code quality | ALWAYS. Bugs, races, type holes, test quality |
| security | touches authn or authz, parses untrusted input, handles a secret or token, crosses a network or process boundary, builds a query or a path from user data, changes CORS or origin checks |
| architecture | changes a contract, schema, public interface, deployment topology or cross-service call - anything later code has to build on |
| observability | adds or changes logging, spans, metrics, alerts, or an error-handling path |
| reuse / extraction | adds general-purpose logic that looks like it belongs in a shared package, or reimplements something a shared package already exports |
| simplification | is the FINAL review, or is large enough that its shape is in question |
| prompt-reviewer (separate, not part of the squad) | changes a prompt, skill, agent definition or template |

Lanes selected at kickoff for this review: <REVIEW_LANES>. Add one the kickoff missed if the diff clearly calls for it, and say so in your summary. **Do not run the full set out of habit.** Six lanes on a two-file diff is five reviewers reading the same code to report nothing, and one night spent 44 specialist invocations across seven reviews to get there.

ASK EACH LANE FOR DEMONSTRABLE PROBLEMS: a regression with a failure path, or an acceptance criterion this sprint did not meet. Elective hygiene is a follow-up, not a finding.

## STEP 2 - TRIAGE. You are the deciding engineer, not a stenographer.

Every finding goes in exactly one bucket, and be hard about it. A finding you pass on becomes work for a session at 3am, so a padded list costs real hours.

- **FIX** - correctness, security, data integrity, permissions, or a real bug in what this sprint built.
- **FOLLOW-UP** - real, but out of scope. One line to <WS>/state/FOLLOWUPS.md: `<severity> | <file> | <what is wrong> | <why out of scope>`. The morning report turns it into a ticket.
- **REJECT** - wrong, or a style preference fighting this repo's conventions. Record it with the reason in your summary.

Permissions or access-control changes always need a human (charter #9). Never queue one as a fix - it is a manual step, STEP 5.

## STEP 3 - WRITE THE MANIFEST. This file is the deliverable.

REVIEW-FINAL: do the CARRY step at the top of STEP 6 first, so this manifest holds the whole night's open findings - it is the only thing <FIX_TAG> reads.

  <WS>/state/<TAG>.findings.md

One block per FIX finding, in severity order, exactly these fields:

    ID:        F<n>
    AT:        <the short sha you reviewed - `git rev-parse --short HEAD`>
    SEVERITY:  BLOCKER | HIGH | MEDIUM | LOW
    LANE:      correctness | security | architecture | observability | reuse | simplification
    WHERE:     <file>:<line>
    ISSUE:     <what is wrong, in one sentence>
    EVIDENCE:  <the failure path, or the unmet acceptance criterion - why this is real>
    ACTION:    <the concrete change required>

Concrete enough that a session which never saw the review can act on it without re-running anything - hours later, after more tickets have landed on top of the code you read. That is why AT names the commit: WHERE is a line in THAT commit. EVIDENCE is not optional: a finding with no failure path is a finding that has not been triaged.

## STEP 4 - PUT IT ON THE PR, ONCE

Post **one** consolidated comment. Not one comment per finding.

REVIEW-FINAL posts only the findings it raised itself; the carried ones were posted by their checkpoint review when they were found.

  gh pr comment "$PR" --body-file <WS>/state/<TAG>.findings.md

Add inline anchors ONLY for BLOCKER and HIGH findings, where the exact line is the point:

  cat > "$TMPDIR/ns-<TAG>-review.json" <<'JSON'
  {
    "body": "Night sprint <TAG>: <n> to fix, <n> deferred, <n> rejected. Manifest in state/<TAG>.findings.md.",
    "event": "COMMENT",
    "comments": [
      {"path": "src/foo.ts", "line": 42, "side": "RIGHT",
       "body": "**[HIGH] correctness** - <what is wrong>. <failure path>. Fix: <concrete change>."}
    ]
  }
  JSON
  gh api --method POST repos/<REPO_SLUG>/pulls/"$PR"/reviews --input "$TMPDIR/ns-<TAG>-review.json"

Three things about that call, each of which has cost a night:
1. `event` is `COMMENT`. `APPROVE` and `REQUEST_CHANGES` are both refused on your own PR and fail the whole request.
2. `line` must be a line the diff touches, counted on the RIGHT side. One line outside the diff rejects the ENTIRE review with a 422. For a range use `start_line` plus `line`.
3. If it fails, do not retry blind: the consolidated comment above is already posted, so say in your summary that inline anchoring failed and move on.

**The manifest, not the PR, is what the fixer reads.** Posting every internal finding to GitHub so another session can fetch it back is two round trips to replace reading a local file. The PR comment exists for <USER> and the bots, which is why it is one comment and not twenty.

## STEP 5 - ANYTHING A FINDING HANDS TO A HUMAN

A permissions change you refused to queue, a secret the diff now reads but nothing sets, a rotation the review says is needed. Append a block per item to <WS>/state/<TAG>.manual:

    STEP:     <one line: what a human must do>
    WHY:      <what breaks without it - the concrete failure>
    WHERE:    <URL, dashboard path or command, as concretely as you know it>
    VALUE:    <ENV_VAR_NAME, or "none" for a pure action>
    LANDS:    <.env | github secret | terraform var | a service | nowhere>
    SECRET:   <yes|no>
    BLOCKING: <yes = the feature does not work at all without it | no>

BOTH TESTS OR IT IS NOT A BLOCK: (1) the shipped feature does not work until a human acts, AND (2) no agent could have done it. A judgement call <USER> may want to reverse is a line in your summary. Something an agent could have done is a FOLLOWUPS.md line. Names and paths only, never a real secret value.

## STEP 6 - FINAL REVIEW ONLY

DELETE THIS WHOLE SECTION when rendering a checkpoint review. It applies only to REVIEW-FINAL.

- **CARRY THE CHECKPOINT FINDINGS FORWARD - this comes first.** The checkpoint reviews were async, so nobody fixed what they found: by design, every finding of the night is fixed once, by <FIX_TAG>, from YOUR manifest alone. Read every `<WS>/state/REVIEW-C*.findings.md`. Check each finding against HEAD now; later tickets may have fixed it, moved it or made it moot. Still real: copy it into your manifest with a new ID, today's WHERE and AT, and one more field, `ORIGIN: REVIEW-C<n> F<k>`. Gone: one line in your summary, `REVIEW-C<n> F<k> resolved by later work (<sha or ticket>)`. Do not post carried findings to the PR again; they were posted when they were found.
- **Re-read every ticket in <WS>/tickets/ against what actually landed.** Post any UNMET acceptance criterion as a finding like any other. This is the last honest check before <USER> sees it.
- **Do NOT take the PR out of draft.** The CI watcher does that, and only once the required checks are green at the pushed head.
- **SWEEP THE DIFF FOR SETUP AND WRITE THE VERDICT.** You already have the whole diff loaded, so this is nearly free here. Over `git diff <BASE>...HEAD`: new env or config reads and whether `.env.example` documents them; new `secrets.*` or `vars.*` in `.github/workflows/*`; new terraform / terragrunt units; new migrations; new infrastructure a deploy will not create; a new third-party integration or OAuth client; anything a ticket's acceptance criteria assume exists but no code creates. Then check what is ALREADY set: `gh secret list`, `gh variable list`, `.env.example`, the repo's own store. **A FAILED READ IS NOT AN EMPTY ANSWER** - if a listing errors, say the read failed; never record it as "not configured".

  Apply BOTH TESTS from STEP 5 to every <WS>/state/*.manual block and to everything the sweep turned up, then write one word:

      echo NEEDED > <WS>/state/SETUP.verdict     # at least one thing passes BOTH tests
      echo NONE   > <WS>/state/SETUP.verdict     # nothing does

  Say which it is, and what you swept to reach it, in your summary. NONE is a finding, not a silence.

## CONTEXT

Measure, do not estimate: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` - percent USED, counting up.

Check it after the review lanes return; that is where the number jumps. You do no fixing, so you should finish inside your window comfortably. If you somehow reach <RELAY_AT_USED>% before posting, WRITE THE MANIFEST AND POST IT FIRST - a review that dies holding un-posted findings has produced nothing - then relay per the CONTEXT RELAY section of <WS>/PLAN.md, carrying the un-triaged findings so your successor does not re-run the lanes.

## WHEN DONE - in this order, and the order matters

1. `echo "<n findings, n deferred, n rejected, lanes run>" > <WS>/state/<TAG>.summary`

2. **Decide what runs next**, and write it to `<WS>/state/<TAG>.next` BEFORE you write your status. Nothing launches off your status until `.next` is correct; that ordering is the whole reason the two files are separate.

   **A CHECKPOINT review (REVIEW-C<n>) launches nothing.** Your findings wait in your manifest for REVIEW-FINAL to carry forward and for <FIX_TAG> to fix. There is no checkpoint fixer, and you never hand findings to the session that wrote the code: it has moved on to its next ticket, which is the point.
       : > <WS>/state/<TAG>.next

   **REVIEW-FINAL decides whether <FIX_TAG> has anything to do.** It does if your manifest has ANY finding (your own or carried forward), or if the PR carries an unaddressed comment from a bot, CI, or a human:
     gh pr view "$PR" --json comments,reviews

   - **Nothing at all** - no findings, no open comments:
       echo "SKIPPED: nothing to address" > <WS>/state/<FIX_TAG>.status
       echo "<TAG> posted no findings and the PR has no open comments" > <WS>/state/<FIX_TAG>.summary
       echo "<NEXT_AFTER_FIX>" > <WS>/state/<FIX_TAG>.next
       echo "<NEXT_AFTER_FIX>" > <WS>/state/<TAG>.next
     No fixer will hand CI on, so you do it: `bash <WS>/ci-watch.sh <WS>`. It returns at once; do not wait for CI and do not take the PR out of draft yourself - the watcher does that on green.

   - **Anything to fix** - always a fresh fixer, because its rendered prompt carries the acceptance gate:
       echo "<FIX_TAG>" > <WS>/state/<TAG>.next
       bash <WS>/launch.sh <WS> <FIX_TAG>

3. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST. Never `RELAYED` unless you actually relayed.

Post a summary as your last message: findings by severity, which lanes you ran and which you skipped and why, what you deferred, what you rejected and why, what you carried forward and what later work had already resolved (REVIEW-FINAL), what runs next, and anything needing a human decision in the morning.
