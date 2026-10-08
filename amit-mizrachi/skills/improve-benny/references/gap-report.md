# Gap report

A gap is a reason Benny could not give the gold answer. Find gaps by comparing three things:
the gold answer's fact table, what Benny can reach today, and what Benny actually did on the
case (his trace). Fix causes, not symptoms: "no SQL" is one gap even if it hides five facts.

## Read Benny live first (Machina reads only)

| Read | Tool | Look for |
|---|---|---|
| Spec | `read_agent_spec benny` | `instructions` (reply shape, rules), `maxToolSteps`, `history`, channel `thread_context` and `accept_mentions_from_agents`, declared connections and skills |
| Tools | `list_effective_tools benny` | which tool names are `registered`; dormant or refused ones |
| Credentials | `get_connection_status benny` | per connection `agent`/`default`/`missing`; `mcpServers[].tools` (what an MCP server really exposes) |
| Channels | `check_agent_channels benny` | whether the chat door answers (replays need it) |
| Skills | `read_skill_body <id>` | the body of every skill the case touches or Benny activated |
| His turn | Logfire, project `shapes-internal`, service `agent`, conversation id = thread ts | each `execute_tool <connection>.<tool>` span: name, status, error class; `activate_skill` calls; step count vs `maxToolSteps` |

Save each read under `<RUN>/benny-live/` (a file per read). These are the prior copies a later
apply step needs anyway.

## Classes

| Class | The gap is | Typical fix surface |
|---|---|---|
| `access` | Benny has no tool that reaches the source (not declared, not registered, not exposed by the MCP server, registry row not offered to `benny`) | registry row `agents`, spec `connections`/`tools` |
| `credential` | the tool exists but its credential is missing, wrong or expired (401/403 in the trace) | `set_connection_credential` - usually a human mints the value |
| `config` | a spec field blocks him (`thread_context: false`, `accept_mentions_from_agents`, channel settings) | `write_agent_spec` |
| `skill-knowledge` | a skill or reference lacks the rule, or states a wrong one, so he cannot reason to the answer even with the data | `write_skill_body`, a new reference or skill |
| `reply-style` | the facts were reachable but the reply shape is wrong: no confidence label, no named setting, too long, no draft offer, no escalation tag | spec `instructions`, `clear-speech`, a new skill |
| `judgement` | he had the facts and the rule but concluded wrong, or claimed something he did not check | instructions rule, a rubric item on every case |
| `budget` | he ran out of tool steps or history (`maxToolSteps`, `context_token_budget`, `tool_result_horizon`) | spec `maxToolSteps` / `history` |

One gap can need two fixes (a skill rule AND an access change); class it by the cause, and
list both fixes.

## Format - `<RUN>/gap-report.md`

```
# Gap report - <case id>

Benny live read at <utc>: spec <serving state>, <n> registered tools, maxToolSteps <n>.
Benny's turn (<conversation id>): <n> tool calls, <n> errored, skills activated: <ids>.

| # | Gap | Class | Evidence (live read or trace) | Gold facts it blocks | Proposed fix | Needs a human? |
|---|---|---|---|---|---|---|

## Reply-style diff
<the gold reply's shape vs Benny's: line 1, label, named setting, side effect, length,
evidence, draft offer, escalation tag - one line each>

## Not gaps
<facts Benny could reach and did; facts he could reach and did not (that is judgement or
skill-knowledge, so it is a row above, not here)>
```

"Proposed fix" names the exact surface: a spec field path, a skill id plus the section to
change, a registry row, a credential slot. "Needs a human?" is `yes` only when no agent can do
it (a merge, a deploy, a credential value only a person can mint); say which.
