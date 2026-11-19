/amit-mizrachi:retro night sprint <SLUG> - <TAG> (async retro). The session to review is the WHOLE SPRINT: every session of the night, read from the workspace <WS> as described below, not this session.

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - decide each item yourself and say what you decided. Never run `rm` or `mv` as a shell command: some org policies make them ask for confirmation even in auto mode, and nobody is there to answer. Use `git rm` / `git mv` for files in a repo. ASCII only, no em/en dashes.

Workspace: <WS>. You are tag <TAG>, the sprint's RETRO ticket.

IF THE RETRO SKILL'S TEXT IS NOT ABOVE THIS LINE (the slash command did not expand), read it yourself and follow it: `ls ~/.claude/plugins/cache/*/amit-mizrachi/*/skills/retro/SKILL.md | tail -1`. Load `writing-for-agents` as its step 1 says.

YOUR ONE JOB: run the retro skill over the night, then ACT on what it finds. The skill ends by presenting candidates to the user; in this sprint nobody reads them until morning, so you apply the ones worth applying and leave the morning a list of what you changed and what you only propose. A retro that only writes a list is half of this ticket.

YOU ARE ASYNC. NOTHING WAITS FOR YOU. The runner starts you once the blocking chain and the CI ticket have ended, revives you if you die, and closes your session when you end. The morning report is written without you; the conductor adds your line at the end. Never start or stop another session, and never touch the sprint branch.

## THE TREES

You start in a DETACHED worktree of the sprint branch made for you alone:
{{^MULTI_REPO}}
  pwd    # <WORKTREE>-<TAG>
{{/MULTI_REPO}}
{{#MULTI_REPO}}
  pwd    # a tree beside the first repo's worktree. <WS>/REPOS.md lists every repo.
{{/MULTI_REPO}}
Never `cd` into the sprint's own worktree, and never commit to the sprint branch or push it: the sprint PR is reviewed as it stands. Your changes go on a NEW branch off the base, in a new draft PR:
{{^MULTI_REPO}}

    git fetch origin <BASE> && git switch -c night-sprint-retro/<SLUG> origin/<BASE>

A change that only makes sense with the sprint's code (a lint rule over a file the sprint added) goes on a branch off `origin/<BRANCH>` instead, and its PR body says "merge after" the sprint PR.
{{/MULTI_REPO}}
{{#MULTI_REPO}}

    git fetch origin <base> && git switch -c night-sprint-retro/<SLUG> origin/<base>

per repo you change, with that repo's base from `<WS>/repos/<key>.env`. For a repo other than the one you started in, make a detached tree beside its worktree first: `git -C <its WORKTREE> worktree add --detach <its WORKTREE>-<TAG>`, then switch it to the new branch. Never edit a repo's sprint worktree.
{{/MULTI_REPO}}

## STEP 1 - the primary sources (instead of the skill's "current session")

Read cheapest first, and stop reading when you have the candidates:

1. `bash <WS>/retro-digest.sh <WS>` - one block per session of the night: tool calls by name, the largest tool results, files read three times or more, failed calls with their text. It reads the transcripts so you do not have to.
2. `<WS>/LOG.md` (the conductor's `Decided without asking` and ledger) and `<WS>/state/EVENTS.log` (every launch, revive, relay and budget wait).
3. `<WS>/state/*.status`, `*.summary` and `*.revivals`. A `BLOCKED`, an abandoned ticket, or a relay from `CEILING_USED` is an incident.
4. `<WS>/state/*.findings.md` - what the reviewers caught. A finding is a mistake the implementer made: the coding-standards and automated-checks categories start here.
5. `<WS>/state/CI*.summary` and the CI ticket's PR comment: every lane CI found red that the sessions' local checks passed is a local-vs-CI gap, so a guardrail is missing.
6. `<WS>/state/TEST-REPORT.md`, `GOLDEN.verdict`, `FOLLOWUPS.md`, `*.manual`.
7. Only for an incident named above: the transcript itself (its path is in the digest). Never read one whole: `grep -n` it, or `python3` over its JSON lines, for the window that matters.

Then the steering files every session loaded: the repo's AGENTS.md / CLAUDE.md, its CODING_STANDARDS.md if it has one, `<WS>/PLAN.md`, and the rendered prompts `<WS>/prompt-*.txt`.

## STEP 2 - the candidates

Use the retro skill's categories and its rules (mechanical rule -> a deterministic check; `CODING_STANDARDS.md` only for judgement calls; AGENTS.md only for navigation pointers). Every candidate needs EVIDENCE from the night: a tag, a finding id, a log line, a failed call. A candidate with no incident behind it is not a candidate. Rate each one High / Medium / Low by what it cost this night or will cost the next.

Then sort each candidate into exactly one place:

| Where it lives | What you do |
|---|---|
| the sprint's repo (AGENTS.md, CLAUDE.md, CODING_STANDARDS.md, a lint rule, a pre-commit hook, a CI job, a docs page) | ACT: a commit on your retro branch in that repo |
| the plugin's skills (night-sprint's templates and scripts, deep-review, to-tickets, any `amit-mizrachi:` skill whose instructions misled a session) | ACT: a commit on a retro branch in the plugin's repo (below) |
| the user's own files (`~/.claude/CLAUDE.md`, `~/AGENTS.md`, memory) or another team's repo | PROPOSE only: they steer every session on the machine, so the user decides. Write the exact text you would add or remove |
| a new tool, credential or MCP access | PROPOSE only, as a line in `<WS>/state/FOLLOWUPS.md` too |

## STEP 3 - act

Apply the High and Medium candidates whose fix is small and clear, most severe first, at most six changes in all. A Low, or a fix that needs a design decision, stays a proposal. One cause per commit (`chore(retro): <what>`, never `--no-verify`), its body naming the incident: `<tag>: <what happened>`.

- **Check what you change, cheaply.** Run the repo's format/lint gate on the files you touched (`FORMAT_CHECK` in `<WS>/facts.env`, or in `<WS>/repos/<key>.env` for a multi-repo sprint). A new lint rule must pass on the base branch: run it over the repo once; if it flags existing code, fix those sites in the same commit or narrow the rule, and say which. Never run the full test suite.
- **The plugin's repo.** Find it from the installed plugin: `python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["repository"])' "$(ls ~/.claude/plugins/cache/*/amit-mizrachi/*/.claude-plugin/plugin.json | tail -1)"`. Clone it into `<WS>/retro-plugin` (`gh repo clone <owner/repo> <WS>/retro-plugin`), branch `night-sprint-retro/<SLUG>` off its default branch, and follow its own AGENTS.md / README rules (a version bump in `plugin.json` when a skill changes, its offline tests by path when it has them). If the clone or the push is refused, write `git diff` to `<WS>/state/RETRO.plugin.patch` and list it as a proposal.
- **Open one DRAFT PR per repo you changed**, never more, never ready, never merged. Title `chore: night-sprint <SLUG> retro`. The body: one row per change (`incident | change | why it prevents a repeat`), then the proposals you did not apply, and the tracker item the sprint PR's body links, if it links one. Push with `git push -u origin night-sprint-retro/<SLUG>`, never with force.
- **Post ONE comment on the sprint PR** (`gh pr view <BRANCH> --json number -q .number`; multi-repo: the first repo's PR): the retro PR link(s) and the three most severe candidates in one line each.

## NEVER

Merge, deploy, force-push, `--no-verify`, edit the sprint branch or its worktree, edit the user's global files or another team's repo, reply to review threads, or start or stop another session. Edit no <WS>/state/ file other than the ones named here.

## CONTEXT

Measure, do not estimate: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` - percent USED, counting up. Check it after STEP 1 and after each change. At <WARN_AT_USED>% used, read nothing new: finish with the candidates you have. At <RELAY_AT_USED>% used, hand off per the CONTEXT RELAY section of <WS>/PLAN.md; your continuation prompt must carry the whole candidate table with each row's evidence and state (applied with sha, proposed, still to do) and the retro branch and PR of each repo, so your successor reads no source again.

## WHEN DONE - in this order

1. Write `<WS>/state/RETRO.md`: the candidate table, most severe first - `severity | category | evidence | change or proposal | where (PR link + sha, or "proposed")`.
2. `echo "<one line: n changes in <PR links>, n proposals | BLOCKED: <why>>" > <WS>/state/<TAG>.summary`
3. `: > <WS>/state/<TAG>.next` - EMPTY. Nothing comes after an async tag; written BEFORE your status.
4. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST.
5. `bash <WS>/advance.sh <WS> <TAG>` - run it once and do not second-guess the result.

End with a short message: each retro PR URL, the changes in it, and the proposals left for the user.
