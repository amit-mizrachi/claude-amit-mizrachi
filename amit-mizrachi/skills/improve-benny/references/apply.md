# Apply - change live Benny safely

The apply step turns the gap report's proposed fixes into live Machina writes. Every write is
read first, saved, made through the Machina MCP, checked, and written to a ledger, so each one
has an undo. Never wrangler, never the Shapes-account KV namespace (it holds a stale spec).

## Before the first write

1. Pick the fixes: the gap rows whose fix surface is a spec field, a skill body or a skill
   attachment, and whose "Needs a human?" is `no`. A credential value, a merge or a deploy is
   never an apply step: list it in the report for the user.
2. Read every target and save it under `<RUN>/benny-live/` (this is the prior copy):
   - spec field: `read_agent_spec benny`; save the field you change verbatim as
     `spec-<field>.prior.md` (or `.json`), and the `skills[]` list if you attach.
   - skill body: `read_skill_body <id>`; save it as `<id>.SKILL.prior.md` (and each reference
     file you change). A new skill has no prior copy: write `none (new)` in the ledger.
   - `list_spec_archives benny`: note the newest key.
3. Read the live text you are about to change and keep every rule you do not mean to change.
   For Benny's instructions that includes the word limit and the no-code-in-prose rule.

## The writes, in this order

| Change | Tool | Notes |
|---|---|---|
| new skill | `write_skill_body` `mode: create`, `attach_to: ["benny"]`, `load: on-demand` | attaching writes the spec too: it archives |
| skill body | `write_skill_body` `mode: update` | the whole body is replaced; the server copies the old bytes to `skill-archive/<id>/<ts>/` |
| spec field | `write_agent_spec` with one `set-field` op | the superseded spec is archived; the result names `archivedKey` |

Skills before the spec, so the instructions never name a skill that is not attached yet. Never
re-send a write because a turn still shows the old behaviour: the runtime caches the spec for
up to 60 s, and a session that is already awake keeps its spec. Replay on a fresh session.

## After each write

1. A spec write (or an attach): `list_spec_archives benny` shows a new newest key. No new key:
   stop and report it, do not write again.
2. Append to `<RUN>/run-log.md` (kind `write`) and one line to the ledger:

   ```
   <utc> | <run or ticket tag> | <tool> | <target> | <prior copy path or archive key> | <why, one line>
   ```

   The ledger is `<RUN>/live-writes.md`, or the file the user names (`--ledger <path>`). A
   write that is not in the ledger has no undo.
3. Copy a skill body this run CREATED, and the new text of any spec field it changed, to
   `<skill dir>/corpus/_benny-sources/` for review (a skill as `<id>/SKILL.md`, the instructions
   as `benny-spec-instructions.md`).

## Undo

- Spec: `write_agent_spec benny` with the field's value from the prior copy (or read the archive
  key), then check that `list_spec_archives` shows a new key.
- Skill body: `write_skill_body <id> mode: update` with the prior copy.
- New skill: `detach_skill benny <id>`, then `delete_skill_body <id>`.

## Then prove it

Replay the case on a FRESH session (R2-R4) and compare with the last verdict line. A fix that
does not move its rubric items is not done: say so in the report, never write again blind.
