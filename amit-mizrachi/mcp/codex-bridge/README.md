# codex-bridge

A local MCP server that lets Claude Code drive OpenAI Codex. Claude stays your main
coding agent; Codex becomes a tool it can call when a different model suits the job
better.

Every session it starts is a normal Codex session on disk, so you can take any of
them over yourself with `codex resume <session_id>`.

## Install

It ships with the `amit-mizrachi` plugin and registers itself from the plugin's `.mcp.json`
(`python3 ${CLAUDE_PLUGIN_ROOT}/mcp/codex-bridge/server.py`). Install the plugin, start a new
session, and `/mcp` shows `plugin:amit-mizrachi:codex-bridge`.

It needs `python3` (3.9+, no packages - the one macOS ships is enough) and the `codex` CLI,
logged in once:

```
npm install -g @openai/codex    # or: brew install --cask codex
codex login
```

`codex` does not have to be on the `PATH` Claude Code sees. When it is not (common when Claude
Code starts from the desktop app or an IDE), the bridge looks in the usual install folders:
Homebrew, npm global, nvm, volta, pnpm, bun and `~/.local/bin`. Set `CODEX_BIN` to a full path to
override. Without `codex`, the server still starts: `codex_status` says `ready: no` with the
install line, and every other call fails at once with the same line.

Registered it by hand before (`claude mcp add codex-bridge ...`)? Remove that copy, or you get
the same six tools twice: `claude mcp remove codex-bridge --scope user`.

## Tools

| Tool | What it does |
|---|---|
| `codex_ask` | Ask a question and wait for the answer. Read-only by default. |
| `codex_start` | Launch a background session, return a session id at once. Workspace-write by default. |
| `codex_check` | Status, transcript, latest answer, token usage. Can block until done. |
| `codex_reply` | Send a follow-up turn into an existing session, keeping its context. |
| `codex_list` | List sessions and their takeover commands. |
| `codex_cancel` | Stop a running session. It stays resumable. |
| `codex_status` | Is `codex` installed and logged in? Fast and free - it starts no session. |

### Parameters

- `model` - any Codex slug: `gpt-6-astra`, `gpt-5.6-luna`, `gpt-5.6-terra`,
  `gpt-5.6-pro`, `gpt-5.5`, `gpt-5.3-codex`. Omit it to use whatever
  `~/.codex/config.toml` sets .
- `effort` - `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
- `sandbox` - the permission mode:
  - `read-only` - can read files and run read-only commands. Cannot write.
  - `workspace-write` - can edit files under `cwd`.
  - `danger-full-access` - no sandbox.
- `approval` - `never` (default), `on-request`, `untrusted`. A headless run has
  nobody to answer a prompt, so `on-request` makes Codex refuse a risky step
  rather than pause for you.
- `cwd` - the workspace root. Always pass the repo you mean.
- `config` - any other `config.toml` override, for example
  `{"model_verbosity": "low"}`.

## Talking to it

Plain language is enough:

- "Ask Codex with gpt-5.6-pro at max effort whether this migration is safe."
- "Start a background Codex session on ~/Documents/development/shapes-platform to
  refactor the sync worker, workspace-write, high effort."
- "Check on that Codex run."
- "Tell Codex to also update the tests."
- "Show me my Codex sessions."

## Taking over a session

Every result ends with a line like:

```
take over: cd /path/to/repo && codex resume 01a082af-9dd6-7071-baa6-ec13927e3994
```

Paste it into a fresh terminal and you are inside that exact session, with its full
history, in the normal Codex TUI. Ask Claude to "list my Codex sessions" if you lost
the id; `include_all_codex_sessions` also lists sessions you started by hand.

## The same thing from a shell

`server.py` is also a small CLI over the same run state:

```
python3 <plugin root>/mcp/codex-bridge/server.py runs          # list runs
python3 <plugin root>/mcp/codex-bridge/server.py show <run_id> -v
python3 <plugin root>/mcp/codex-bridge/server.py wait <run_id> # block until done
python3 <plugin root>/mcp/codex-bridge/server.py cancel <run_id>
```

`wait` matters for long work. Claude Code can run it as a background shell job, and
the harness then tells Claude the moment Codex finishes. Nothing polls, and no tool
call is held open. The pattern is: `codex_start` to launch, then `wait` in the
background.

## Behaviour worth knowing

- **Nothing is ever lost to a timeout.** `codex_ask` and `codex_reply` block for
  `wait_seconds` (default 240, max 3600). If the session is still working when that
  runs out, it keeps running in the background and you get a `run_id` to poll.
- **There is no practical MCP timeout to work around.** Measured on Claude Code
  2.1.220: a stdio tool call returning after 320s succeeded with default settings.
  The default hard wall-clock limit per call is 1e8 ms, about 27.7 hours. So do
  **not** set `MCP_TOOL_TIMEOUT` or the per-server `timeout` field here - both only
  *lower* that ceiling. The 60s value in the build is the HTTP request budget and
  does not apply to a stdio server like this one.
- **Progress notifications cannot extend a timeout.** Claude Code states this
  outright, so a heartbeat design would not have helped anyway.
- **Blocking is still the wrong tool for long work**, not because it breaks but
  because it freezes Claude's turn and shows you nothing until it ends. Use
  `codex_start`, then either `codex_check` or the background `wait` job.
- **State lives in `~/.codex-bridge/runs/<run_id>/`**: the raw JSONL event stream,
  stderr, the final message, and the launch metadata. Safe to delete any time.
- **Codex sessions themselves live in `~/.codex/sessions/`** as usual.

## Cost note

Every MCP server and skill your `~/.codex/config.toml` loads is paid for at the start of
each new Codex session - with a heavy config, around 22k input tokens before it reads a single file.
Follow-ups in the same session are mostly cached. Trimming unused MCP servers or
plugins from that config is the lever if that matters.

## Troubleshooting

- Not sure it works? Ask Claude to "check codex status": `codex_status` answers `ready: yes`,
  or what to fix.
- `/mcp` shows it failed: run
  `python3 <plugin root>/mcp/codex-bridge/server.py` directly -
  it should sit there waiting on stdin and print `[codex-bridge] ready` to stderr.
- A run exits non-zero: `codex_check` prints the stderr tail. Usually it is Codex
  auth (`codex login`) or an unsupported model slug.
- Nothing happens for a long time: `codex_check(verbose=true)` shows every command
  Codex has run so far.

## Alternative

Codex ships its own MCP server (`codex mcp-server`, tools `codex` and `codex-reply`).
It is one line to register, but it blocks for the whole session, lists nothing, and
surfaces no session ids, so there is no way to poll a long run or take one over.
This bridge exists for those parts.
