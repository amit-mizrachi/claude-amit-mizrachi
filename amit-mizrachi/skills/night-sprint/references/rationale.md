# Night sprint - why the rules are the rules

**This file is for whoever changes the skill. It is deliberately NOT loaded at runtime.**

`SKILL.md` and the prompt templates are read by sessions, and every word in them is context a
session pays for. So they carry rules and procedures. The incidents that produced those rules
live here, where they cost nothing until somebody is deciding whether a rule can go.

Read this before deleting or relaxing anything. Most of these rules look like over-engineering
right up to the night they save.

---

## The 2026-09-19 audit, and what came out of it

Two completed workflows were measured end to end, deduplicated by `(message.id, requestId)`
across streaming records and inherited resumed-session history, with nested agents counted once.

| Run | Overnight tokens | Wall clock | ccusage estimate |
|---|---:|---|---:|
| `external-mcp-bugfix`, 7 stacked PRs, 21 tags | 410,471,400 | 10h38m | $297.42 |
| `studio-local-deploy` | 184,368,186 | ~4h18m | $158.86 |

Where the larger run's tokens went:

| Stage | Tokens | Share |
|---|---:|---:|
| Seven implementations | 132,500,690 | 32.1% |
| Seven reviews, incl. nested reviewers and one revival | 138,679,348 | 33.6% |
| Seven review-fix sessions | 103,029,691 | 25.0% |
| Conductor | 38,237,928 | 9.3% |

96.7% of the volume was cache reads - repeated context processing, not newly generated text.
That is not the same as 96.7% waste, and it is not the same as 96.7% of cost. **Review plus fixes
was 58.6% of tokens**, which is the pool worth optimising, not a claim that all of it was wasted.

Six changes came out of it, in the order they were worth doing. Each one maps to code:

1. **Classify failures before recovering from them** - `classify-error.sh`, and the quota branch
   in `revive.sh`.
2. **Select review lanes by risk** - the lane table in `review-find-prompt.md`.
3. **Stop paying for a fresh window to fix small things** - `handback.sh`.
4. **Let a script own the routine** - `advance.sh`, and `watch.sh` as a runner.
5. **Render prompts instead of writing them** - `render.sh` and `facts.env`.
6. **Make verification decide completion** - `accept.sh`, `ACCEPTANCE.verdict`, `GOLDEN.verdict`.

Two things the audit explicitly said **not** to change, and they were not changed:

- **The 20 / 30 / 60 context ladder stays as it is.** Neither completed run showed a single
  compaction or a context-triggered relay. Their extra sessions were reviews, fixes and
  revivals. The ladder is worth simplifying one day, but it was **not** a demonstrated cause of
  either run's cost, and replacing one arbitrary percentage with another arbitrary percentage
  without measuring is not an improvement. Test a new threshold before choosing it.
- **Independent review stays.** It caught a UTF-16-versus-UTF-8 byte-budget bug and a new
  20-second deadline that violated an existing 25/30-second ordering. Both were real. The
  expensive part was never the reviewing, it was running six lanes on every tip.

A 25-40% reduction in total token volume is the **experiment target** here, not a measured
saving. The improvements overlap, and much of the review pool was useful work.

---

## Failure recovery

### The spending cap that looked like a permission problem

Two review conversations in `external-mcp-bugfix` stopped on explicit organisation monthly
spend-limit errors:

| Stage | Last error to continuation (UTC) | Gap |
|---|---|---:|
| REVIEW-01 | Sep 18 19:03:49 -> 20:36:09 | 1h32m20s |
| REVIEW-04 | Sep 18 23:40:24 -> Sep 19 01:40:23 | 1h59m58s |

**3h32m together, about a third of the overnight elapsed time.** The operational log recorded
REVIEW-04 as a one-hour permission stall. The raw transcript says two hours and a spending limit.
The recovery misclassified it, and the reviver spent its resume ladder against a wall no retry
could climb.

The root cause was that both `watch.sh` and `revive.sh` sniffed the transcript with
`grep -q isApiErrorMessage`, which answers "was there an error" and not "which kind". A dropped
socket and a spending cap produced the same `api-error` verdict and the same response.

Hence `classify-error.sh`: one classifier, two callers, and the class is named. The strings it
matches are the harness's own, taken from real transcripts on this machine:

    476  API Error: Connection closed mid-response. The response above may be incomplete.
    102  API Error: Unable to connect to API (ENOTFOUND)
     52  You've hit your session limit - resets 4:20pm (Asia/Jerusalem)
     47  API Error: Response stalled mid-stream. The response above may be incomplete.
     42  You've hit your org's monthly spend limit - run /usage-credits to raise it, ...
     20  API Error: 529 Overloaded. ...
     14  Not logged in - Please run /login
      2  Your organization has disabled Claude subscription access for Claude Code - ...
      1  Please run /login - API Error: 401 OAuth access token has expired. ...

Three design points fall straight out of that list:

- **The session limit names its own reset time.** That is the most useful thing in the whole
  list: the sprint can wait exactly as long as the limit lasts instead of guessing or giving up.
  `classify-error.sh` parses it against the error's own timestamp, so the answer is still right
  when something reads the file hours later.
- **The org spend cap names no reset time**, because a human has to raise it. There is no probe
  cheaper than the work itself, so the backoff is 20 / 40 / 60 minutes and the next resume IS
  the probe. Eight waits is most of a night; past that, say so plainly.
- **Auth failures must never reach the ladder.** Retrying a logged-out CLI cannot succeed, and
  every attempt is one more refused request.

**Nothing sleeps.** A reviver that blocked for two hours would take the monitor loop down with
it. It parks the tag in `state/PAUSED` with a retry time and exits; the poll interval is the
wait. A two-hour outage therefore costs one file read per poll and no context at all.

**And nothing new launches while paused.** `launch.sh` and `advance.sh` both refuse. Starting a
fresh session against a cap that is already refusing requests does not get the work done; it
spends one more refused request and leaves a dead tag for the reviver to clean up.

### Two local repairs that never reached the skill

The audit found both, and their real lesson is the second sentence of each.

- **`revive.sh:201` read `${ACTIVE_WITHIN_MIN}`, a name defined nowhere** - the variable is
  `ACTIVE_STALL_MIN`. Under `set -u` that branch aborted instead of refusing, which means the one
  guard standing between the sprint and two agents in one worktree failed open. One sprint
  patched it in its own workspace copy and the fix never came back to the skill, so it kept
  shipping. `tests/run.sh` now asserts no script reads a name nothing defines.
- **`claude agents --json --all --cwd "$WT"` has been observed returning `[]`** for a worktree
  whose sessions are demonstrably running under exactly that cwd. Every caller drew the same
  wrong conclusion - no rows, so the session is gone - and the watcher reported healthy sessions
  as DIED. `agents.sh` now asks with the filter and falls back to the unfiltered list when the
  answer is empty. The filter is an optimisation; it is not allowed to be the source of truth.

Anything patched in a workspace copy at 3am is a fix the skill does not have. The workspace
copies exist so that editing the skill cannot change a running sprint - which is correct, and
which also means every local repair has to be walked back upstream deliberately.

---

## Review

### Why six lanes became "correctness, plus what the diff earns"

Seven tickets launched **44 specialist invocations** - seven each of six standard review roles,
plus two extras. `review-find-prompt.md` required all six, every time.

The seven reviews posted 58 findings: 23 LOW, 24 MEDIUM, 10 HIGH, one BLOCKER, with 36 more
rejected and 26 deferred in triage. That is substantial work, and LOW does not automatically mean
useless. But six lanes on a two-file diff is five reviewers reading the same code to report
nothing.

Two honest caveats, both worth keeping in mind before claiming a saving:

- Reviewing each stacked PR's tip before creating the next branch was correct here, and it was
  the user's explicit request. The expensive choice was the lane count, not the cadence.
- **Going from six lanes to two cuts specialist invocations by two thirds, NOT total tokens by
  two thirds.** Several of those reviewers already ran Sonnet. Measure across the whole run.

### Why FIND and FIX are separate, and why the fixer may be the implementer

Consolidating several specialist reports is the most expensive single act in a night sprint: it
pulls every review plus the whole diff into one window. A session that did that and then fixed
code spent its window twice over, and the reviews were the sessions that hit the handoff line
most often - **mid-triage, which loses the triage**, the most valuable thing the session had
produced. Splitting turns the expensive read into a durable artefact. The findings then cost the
fixer almost nothing to load, and the fixer starts with a clean window for the only part that
needs one.

That argument justifies separating the two steps. It does **not** justify a brand-new heavyweight
session for every fix set, which is what the skill used to require. Seven fix sessions consumed
**103.0M tokens, roughly a quarter of the run**, including legitimate fixes and CI work - and a
good deal of re-reading code the previous session had just written. For five findings in files an
implementer had open twenty minutes ago, a fresh window is the most expensive possible way to
make the change.

Hence `handback.sh`, and hence its three refusals: the implementer's window is past the relay
line, its conversation is gone, or the session is somehow still running. The caller falls back to
a fresh fixer, and does not argue with it.

### Why the manifest is local

The old flow posted every internal finding to GitHub as inline comments and then started a
session whose job was to invoke a general review-addressing skill to read them back. Two network
round trips and a general-purpose skill, in place of reading a local file.

The PR comment still exists, because the PR is where the user and the bots look - but it is
**one** consolidated comment, with inline anchors only where the exact line is the point.

External bot, CI and human threads are genuinely different from internal findings, and the
prompts now say so explicitly. Somebody outside the sprint is waiting on those, so each gets a
reply. The general `address-review` skill's defaults conflict with this skill's treatment of the
PR author's own comments, which is why the fixer is told to use it for external threads only.

---

## Orchestration

### Why a script owns the routine

The conductor of the larger run used **38.2M tokens over 166 recorded response keys**. It
received **28 routine SWEEP heartbeats** alongside 21 DONE events and two STUCK events. Across
the sprint, **102 distinct Bash calls referenced `context-used.sh`**.

A `DONE` event whose only possible answer is a scripted `launch.sh` call is a script's job being
done by a model, with a model's context. So `watch.sh` now does the routine - advance, revive,
pause, resume - and speaks only for the things that need judgement: a real blocker, two agents on
one tag, an auth failure, a budget gap, the first PR, the end of the sprint.

The heartbeat rule follows from the same reasoning: emit one only after a full hour with nothing
else to say. A busy night is silent because the runner is handling it; a quiet night still proves
the watcher is alive.

`state/EVENTS.log` is what makes this safe. Everything the runner does is recorded, timestamped,
and costs the conductor nothing until it reads the file once at report time.

### The transition race

`review-find-prompt.md` had the finder write `DONE` and only **then** work out whether its fixer
had anything to do. `SKILL.md` had the conductor treat `DONE REVIEW-<n>` as "launch the fixer".
Two things deciding the next tag, off two different files, at two different moments.

Locks on individual tags do not help here: the danger is two *different* tags writing the same
worktree.

The fix is ordering plus a single owner. A session writes `state/<TAG>.next` **before**
`state/<TAG>.status`, and `advance.sh` is the only thing that reads the pair. Both the session
and the runner may call it, and they get the same answer because it comes from the same code.
`launch.sh`'s atomic claim remains the backstop.

Keeping the session-side call as well as the runner-side one is deliberate: it means the chain
still moves if the watcher dies, without reintroducing a second decision-maker.

### Why `RELAYED` gets its own branch in `advance.sh`

`RELAYED` read as `DONE` launches the next ticket on top of half of the previous one, with both
sessions committing to the same branch. The continuation tag wins over the wired successor,
always, and `tests/run.sh` asserts it.

---

## Prompts

`SKILL.md` was 757 lines and 10,763 words; the skill plus its references came to 27,741 words.
One kickoff then generated **22 prompts totalling 29,266 words**, plus a 2,965-word plan - mostly
re-typing the same repo path, toolchain line, verify command, branch and thresholds into each
prompt. External kickoff generated 52,030 output tokens before T01 launched; studio's generated
70,979 before its first worker.

Those are word and authoring counts, not billable token counts - the whole skill does not enter
every worker's context. What they establish is duplication at authoring and bootstrap time, and
substitution is the cheapest possible thing to automate.

So `render.sh` fills every slot from `facts.env` plus a small per-tag vars file, and **fails if a
slot is left unfilled**. That check matters as much as the substitution: an unfilled `<VERIFY>` is
a session that wakes at 3am not knowing how to check its own work.

The model still writes what is actually judgement: each ticket's scope, acceptance criteria and
gotchas, the review scope and lanes, the golden path.

For reference, fresh workers in these runs started at roughly 55-60k input-context tokens
(external) and 92-96k (studio). Those baselines include harness and repository instructions and
tool schemas, not only night-sprint - so do not read a prompt-size change straight off them.

---

## Acceptance

All 21 stages of `external-mcp-bugfix` reported completion. **PR #1408 was still red.**

Every one of those stages was telling the truth about itself: each ran the verify command, each
saw green, each wrote `DONE`. `DONE` means "this session finished its work". It has never meant
"the branch is acceptable", and a night that treats the two as the same thing ships a red PR with
a green report on top of it.

The specific mismatch is the common one: **the local check and CI did not check the same things.**
A formatter failure came back from CI and was misdiagnosed as a warning-only lint rule - twice,
in the same night (`external LOG.md:162-215`, and the red PR at `:233`).

Two template defects fed the same problem, and both are fixed:

- `test-prompt.md` let the tester mark `DONE` after failed tests and proceed to reporting.
- `review-fix-prompt.md` let the fixer run `gh pr ready` before anything tested the branch.

Hence three separate files - `<TAG>.status`, `ACCEPTANCE.verdict`, `GOLDEN.verdict` - and hence
`accept.sh` comparing local HEAD to the **pushed** head before it reads a single check result. A
green check on a commit nobody pushed proves nothing.

`FORMAT_CHECK` is a pinned fact for the same reason. A session that discovers a gate CI runs
which `VERIFY` misses should say so: that finding is worth more to the next sprint than the
ticket it was working on.

---

## The rules that predate this audit, and still hold

### Nothing interrupts a working session

There is no way to send a message into a running background session. The sprint used to pretend
otherwise: `remind.sh` and `relay.sh` ran `claude stop` and then `claude --bg --resume` with a
new instruction.

`claude stop` matches only the **short 8-character id**. Handed the full `sessionId` that
`state/<TAG>.session` holds, it prints `No job matching ...` and exits 1 **having stopped
nothing**. Both scripts discarded the message and the exit status, so the stop was a silent no-op
and the resume **forked** the conversation: the original session kept working while the watcher
was repointed at the fork, and both committed to the same branch.

It happened on three separate sprints. It was twice diagnosed and patched in one workspace only,
so it kept shipping. Both scripts were deleted, which removes the failure rather than guarding
it. `claude stop "$(cat state/<TAG>.session)"` is the exact bug: wrong id form, no check.

The trade is explicit and worth restating: **an agent you cannot steer is strictly better than
two agents in one worktree**, and the lever was never reliable anyway.

### Why a narrow rung exists at all

The expensive mistake is not running out of window, it is running out *halfway through
something*. A session that opens a new front at 22% used arrives at the handoff line holding work
nobody can pick up, and its successor inherits a half-finished thing plus a description of it.
Told at 20% to start nothing new, that same session arrives at 30% holding a completed unit, and
the handoff is a paragraph instead of an archaeology report.

### Why the handoff has a floor

At 30% used, the handoff line sits close to a session's startup cost - `PLAN.md`, the ticket,
`LOG.md`, `git log`, the two or three files whose pattern it must mirror - especially on a 200k
window. Handing off at that point gives the successor nothing but a list of files, which it then
reads again. Do that twice and the ticket never gets built. So: **if you have not changed a single
file, do not hand off.** Past `CEILING_USED` the guard expires, and the fact that it expired is
itself something the morning report should carry.

### Why the gauge counts up

It used to be `context-left.sh` and counted DOWN - percent still free - so the same two rungs read
80 and 70. That polarity is easy to get backwards and expensive when you do: a sprint configured
the wrong way round either relays every session at birth or never relays one at all. Nothing in
the sprint speaks "free" any more, and a stale caller reaching for `context-left.sh` now fails
loudly instead of silently inverting.

### Why the wizard contains only actions

A nine-stage wizard that applies a unit, sets a secret, runs a migration, **and** checks `gh` is
logged in, prints what is currently configured and verifies the result afterwards is nine screens
of the user's morning spent on an agent's chores. Six of those stages are work an agent can do,
and the `WIZARD` session is an agent, doing it at authoring time.

The worse failure is a stage asking the user to do something an agent could have done. **It reads
as a requirement when it is really a chore that got handed over.** Ten seconds of the user's
reading, as a follow-up line, instead of a morning of their doing.

And the reason `.manual` blocks are written per session rather than reconstructed from the diff at
the end: the diff shows a new `process.env.FOO`. It does not show that FOO's key lives behind a
dashboard toggle that T04 spent an hour finding at 02:00. That knowledge exists in one session's
window and dies with it.

---

## The review of the audit fixes, and what it caught

The change set above was itself reviewed before it landed, and eight findings came back. They are
worth recording because six of them are the same shape: **a fix that created a new coupling and
did not follow it through to the other end.**

1. **The FIX-TEST prompt was never rendered.** The tester routes an in-scope failure to a
   `FIX-TEST` tag and `launch.sh` refuses a tag with no prompt file, so the whole repair route
   ended at `launch: no prompt file`. The edit that was meant to add it to the kickoff contract
   silently matched nothing - a `replace` with no assertion on a string that had already changed.
   **Assert every mechanical edit.** An unasserted `s.replace` is a no-op waiting to be believed.
2. **`<PR>` cannot be filled at kickoff.** Both review templates carried the slot and `render.sh`
   exits 2 on an unfilled one, but the draft PR opens only after `T01` lands. The prompts now
   discover the number themselves. The test suite had not caught it because it asserted each slot
   was *known*, which is not the same as *resolvable at the moment it is needed*.
3. **A `FIX-FINAL` handback dropped the acceptance gate.** `handback.sh` builds a generic
   "fix, verify, push, advance" prompt. The rendered `FIX-FINAL` contract also runs `accept.sh`,
   takes one bounded repair pass on red, and only leaves draft on PASS. Resuming an implementer
   with the generic prompt silently discarded all of it, so a one-line final fix could end the
   sprint without anything checking CI. It now refuses any tag whose rendered prompt mentions
   `accept.sh` - a mechanical test, so it keeps holding if the gate moves to another tag.
4. **The wizard gate overwrote the pending repair.** The tester set `TEST.next=FIX-TEST`, then ran
   the gate unconditionally and overwrote it with `WIZARD` or empty. The repair pass was dropped
   at exactly the moment it was needed. The gate is now conditional, and `FIX-TEST` owns it.
5. **A skipped recovery consumed the death that justified it.** `did_once "$tag:DIED"` marked the
   death reported *before* `do_revive` checked its five-minute cooldown. With 120-second polls, a
   resumed session that fails immediately hits the second death inside the cooldown: the revive
   was declined, the marker was spent, and every later sweep failed the `did_once` check. The tag
   sat unfinished until morning. **Never consume the reason for an action before the action
   succeeds.**
6. **`@{upstream}` is a cached answer.** `accept.sh` compared HEAD against the local
   remote-tracking ref, which is whatever the last fetch left there - not the PR as GitHub sees
   it. Another checkout advancing the branch leaves both local refs at A while the checks report
   on B, and the verdict then says "A passed" on B's evidence. It now reads `headRefOid` from the
   PR and re-reads it after the wait, because the head can move while the checks run.
7. **The launch generation was the ladder budget.** `attempt` was `resumes + restarts + 1`, and
   budget retries deliberately do not increment those - so every quota resume in a night was named
   `ns-<slug>-<tag>-r1`, and `resolve_sid` matched the *previous* retry's finished session. The
   real process ran untracked. Two things were conflated because they happened to be the same
   number once. The generation now counts every ledger line, and `resolve_sid` additionally
   excludes every session id that existed before the launch.
8. **The auth recovery could not run.** The auth branch wrote a terminal `<TAG>.status` while its
   own message told the user to log in and revive the tag - but the status guard at the top of
   `revive.sh` exits 0 the moment a status file exists, so the documented procedure was a no-op.
   A tag held up by a logged-out CLI is not a blocked ticket: nothing about the work is wrong. It
   now writes no status, marks the hold, and `revive.sh <WS> <TAG> auth-retry` is a real path that
   clears both markers and resumes. The runner idles while the hold stands rather than spending
   revives against it.

The suite grew from 81 to 105 assertions, including a `claude` mock (`tests/mock-claude.sh`) so
the recovery and session-tracking paths can be driven offline. Findings 5, 7 and 8 were all
invisible to a reading of the diff and only showed up when someone ran the path in isolation.

## What to measure next time

On comparable 3-7 ticket runs, track: total / cache / output tokens; wall time **excluding quota
downtime**; metered requests by role; reviewer findings accepted versus rejected; repeat CI
failures; manual interventions; escaped defects.

Two things not implemented from the audit, deliberately left for a separate change:

- **Model routing by role.** The launcher pins neither model nor effort. One sprint added a local
  `MODEL` option that never came back upstream. Actual estimates for the larger run were Opus
  $261.98 and Sonnet $35.43, with specialist reviewers already mostly on Sonnet. Piloting Sonnet
  for routine implementation and reporting is worth doing, but changing the model affects speed
  and cost and does **not** by itself reduce the amount of context sent. Verify the installed
  CLI's supported controls before wiring it into both the launch and revive paths.
- **Cheaper verification.** `nx affected` is already in use in the runs measured, so check cache
  hit rates and timings before promising large test savings. Targeted checks against the ticket's
  starting SHA, with broad checks at contract checkpoints and final acceptance, is the shape -
  but the parity problem above was the urgent half, and that is what got fixed.

Artifacts behind all of the above: `~/Documents/night-sprint-audit-2026-09-19/` - `report.md`,
`report.html`, `sessions.csv`, `summary.json`.
