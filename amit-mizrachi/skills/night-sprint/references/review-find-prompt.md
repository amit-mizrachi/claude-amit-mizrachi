<REPO> - night sprint <SLUG>: <CHECKPOINT> - FIND

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - judge each finding yourself and record it. Never run `rm` or `mv` as a shell command: some org policies make them ask for confirmation even in auto mode, and nobody is there to answer. Use `git rm` / `git mv` for files in a repo, and the workspace scripts for the run's own state. ASCII only, no em/en dashes.

Repo: <REPO_PATH> (<REPO_SLUG>). Toolchain: <TOOLCHAIN>.
Workspace: <WS>. You are tag <TAG>. Every finding of this sprint is fixed once, at the end, by <FIX_TAG>.

DO NOT RUN TESTS. THE FULL SUITE NEVER RUNS LOCALLY IN THIS SPRINT - PR CI RUNS IT, ASYNC, OUTSIDE THE SPRINT. A finder never runs any test, at any checkpoint. Find by reading the diff.

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
{{#MULTI_REPO}}

THIS SPRINT SPANS SEVERAL REPOS, AND YOU REVIEW ONE: <REPO_KEY> (<REPO_SLUG>) - its branch <BRANCH>, its PR, its tickets (the ones whose <WS>/state/T<NN>.repo says <REPO_KEY>). <WS>/REPOS.md lists the others. A defect inside another repo is that repo's reviewer's. The contract BETWEEN repos is yours from this side: where this repo calls, or is called by, code another repo's tickets built, read that side in its worktree (read only) and post a mismatch here as a finding. Name those sibling worktrees, and which calls cross between them, in the DESCRIPTION you give deep-review, so its one reviewer reads both sides of the contract. Two names change for you below:
- the checkpoint manifests REVIEW-FINAL carries forward are `<WS>/state/REVIEW-C*-<REPO_KEY>.findings.md`, never another repo's;
- the setup verdict is `<WS>/state/SETUP-<REPO_KEY>.verdict`, never `SETUP.verdict`, and it covers the <WS>/state/*.manual blocks for this repo: `REPO: <REPO_KEY>` or `all`, or, with no REPO line, a block written by a tag whose <WS>/state/<TAG>.repo is <REPO_KEY>.
On the SKIP route, the PR description you bring up to date carries the multi-repo sections the Repos section of <WS>/PLAN.md lists (sibling PRs, merge order, manual steps after merge).
{{/MULTI_REPO}}

## STEP 1 - REVIEW WITH THE `deep-review` SKILL: ONE REVIEWER, READING DEEPLY

Run the `deep-review` skill (it ships with this plugin as `amit-mizrachi:deep-review`; a user-level `deep-review` is the same skill). It is ONE reviewer - Opus at high effort, a single `Agent` call - covering design, functionality, security and privacy, complexity, tests, naming and production readiness in one pass. Never run `code-review`, `squad-review` or a set of specialist lanes beside it or as a fallback: if deep-review cannot finish, say the review is incomplete in your summary and write the manifest from what you have.

Feed it this sprint's inputs, not the ones its Step 1 would pick for an interactive session:
- **BASE_SHA / HEAD_SHA** - from SCOPE above: the range's two ends, resolved to full shas. HEAD_SHA is `git rev-parse HEAD` here (the snapshot, for a checkpoint). No working-tree snapshot: a finder's tree has nothing uncommitted.
- **REPO** - this worktree's path (the `cd` above).
- **REQUIREMENTS** - verbatim, never summarised: the Goal section of <WS>/PLAN.md, then the full text of every ticket in <WS>/tickets/ that SCOPE covers (REVIEW-FINAL: every ticket). deep-review explains why: a summary written by someone who knows the problems steers the reviewer toward them.
- **DESCRIPTION** - one paragraph: "night sprint <SLUG>, <TAG>, tickets <list> as landed on <BRANCH>", plus the LOG.md lines that defer something on purpose, so the reviewer does not re-raise a conscious deferral.

A big diff takes a while (about 10 minutes typical, 35 for a 300-file one). That is expected: the runner counts the reviewer's own transcript as your activity, so wait for it and do not start a second one.

Take its report as the raw input to STEP 2. Keep every issue it scored at confidence 50 or more - deep-review is explicit that the 50-79 band holds real bugs (a reproduced crash once scored 55) - and keep its "Declined to judge" list for your summary. deep-review's own Step 5 (fix, then review the fix) is not yours: you never fix, and <FIX_TAG> works your manifest.

## STEP 2 - TRIAGE. You are the deciding engineer, not a stenographer.

Before you bucket an issue, open the code at the reviewed head and check it yourself: confirmed, partly, or wrong. The reviewer's confidence is its evidence, not your verdict. Then every finding goes in exactly one bucket, and be hard about it. A finding you pass on becomes work for a session at 3am, so a padded list costs real hours.

Severity: a deep-review Critical is BLOCKER or HIGH, an Important is HIGH or MEDIUM, a Minor is LOW and is usually a FOLLOW-UP or a REJECT. Judge by the consequence, never by the confidence score.

- **FIX** - correctness, security, data integrity, permissions, or a real bug in what this sprint built.
- **FOLLOW-UP** - real, but out of scope. One line to <WS>/state/FOLLOWUPS.md: `<severity> | <file> | <what is wrong> | <why out of scope>`. The morning report turns it into a ticket.
- **REJECT** - wrong, or a style preference fighting this repo's conventions. Record it with the reason in your summary.

For a hand-copied library, check the sprint rules before choosing FIX. If adding it is explicitly forbidden, record or preserve a high FOLLOW-UP for <USER> instead of instructing the fixer to add it. Still report concrete bugs or unmet acceptance criteria in the fallback.

Permissions or access-control changes always need a human (charter #9). Never queue one as a fix - it is a manual step, STEP 5.

## STEP 3 - WRITE THE MANIFEST. This file is the deliverable.

REVIEW-FINAL: do the CARRY step at the top of STEP 6 first, so this manifest holds the whole night's open findings - it is the only thing <FIX_TAG> reads.

  <WS>/state/<TAG>.findings.md

One block per FIX finding, in severity order, exactly these fields:

    ID:        F<n>
    AT:        <the short sha you reviewed - `git rev-parse --short HEAD`>
    SEVERITY:  BLOCKER | HIGH | MEDIUM | LOW
    CONFIDENCE: <deep-review's 0-100 score, after your own check - lower it if you found the evidence thinner>
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
       "body": "**[HIGH, confidence 85]** - <what is wrong>. <failure path>. Fix: <concrete change>."}
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
- **Do NOT take the PR out of draft** unless you route SKIP below. <FIX_TAG> does it after its fixes are pushed.
- **SWEEP THE DIFF FOR SETUP AND WRITE THE VERDICT.** You already have the whole diff loaded, so this is nearly free here. Over `git diff <BASE>...HEAD`: new env or config reads and whether `.env.example` documents them; new `secrets.*` or `vars.*` in `.github/workflows/*`; new terraform / terragrunt units; new migrations; new infrastructure a deploy will not create; a new third-party integration or OAuth client; anything a ticket's acceptance criteria assume exists but no code creates. Then check what is ALREADY set: `gh secret list`, `gh variable list`, `.env.example`, the repo's own store. **A FAILED READ IS NOT AN EMPTY ANSWER** - if a listing errors, say the read failed; never record it as "not configured".

  Apply BOTH TESTS from STEP 5 to every <WS>/state/*.manual block and to everything the sweep turned up, then write one word:

      echo NEEDED > <WS>/state/SETUP.verdict     # at least one thing passes BOTH tests
      echo NONE   > <WS>/state/SETUP.verdict     # nothing does

  Say which it is, and what you swept to reach it, in your summary. NONE is a finding, not a silence.

## CONTEXT

Measure, do not estimate: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` - percent USED, counting up.

Check it after the deep-review report returns; that is where the number jumps. You do no fixing, so you should finish inside your window comfortably. If you somehow reach <RELAY_AT_USED>% before posting, WRITE THE MANIFEST AND POST IT FIRST - a review that dies holding un-posted findings has produced nothing - then relay per the CONTEXT RELAY section of <WS>/PLAN.md, carrying the un-triaged findings so your successor does not re-run the review.

## WHEN DONE - in this order, and the order matters

1. `echo "<n findings, n deferred, n rejected, deep-review verdict>" > <WS>/state/<TAG>.summary`

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
     No fixer will take the PR out of draft, so you do it: make sure the PR description reflects everything the sprint delivered, then `gh pr ready "$PR"`. Never wait for CI and never read it: CI runs async, outside the sprint. <NEXT_AFTER_FIX> is the tester, or empty when no test session was chosen.

   - **Anything to fix** - always a fresh fixer, because its rendered prompt carries the acceptance gate:
       echo "<FIX_TAG>" > <WS>/state/<TAG>.next
       bash <WS>/launch.sh <WS> <FIX_TAG>

3. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST. Never `RELAYED` unless you actually relayed.

Post a summary as your last message: findings by severity, deep-review's ready-to-merge verdict and its "Declined to judge" list, which of its issues you confirmed and which you found wrong, what you deferred, what you rejected and why, what you carried forward and what later work had already resolved (REVIEW-FINAL), what runs next, and anything needing a human decision in the morning.
