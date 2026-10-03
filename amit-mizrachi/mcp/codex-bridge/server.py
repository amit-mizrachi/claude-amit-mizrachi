#!/usr/bin/env python3
"""codex-bridge - a local stdio MCP server that lets Claude Code drive OpenAI Codex.

Each tool call shells out to `codex exec --json`, which streams JSONL events and
persists a normal Codex session on disk. That means any session started here can
be taken over in a terminal with `codex resume <session_id>`.

Zero dependencies. Python 3.9+.
"""

from __future__ import annotations

import glob
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

# --------------------------------------------------------------------------- #
# paths and constants
# --------------------------------------------------------------------------- #

STATE_DIR = Path(os.environ.get("CODEX_BRIDGE_HOME", Path.home() / ".codex-bridge"))
RUNS_DIR = STATE_DIR / "runs"
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
INSTALL_HINT = ("Install the Codex CLI (`npm install -g @openai/codex` or `brew install --cask codex`), "
                "run `codex login` once in a terminal, then restart Claude Code. "
                "Or set CODEX_BIN to the full path of an existing codex binary.")

# A Claude Code started from the desktop app or an IDE often has a short PATH that misses
# where npm, nvm, Homebrew and bun put `codex`. These are the usual install locations.
CODEX_FALLBACKS = (
    "/opt/homebrew/bin/codex", "/usr/local/bin/codex", "~/.local/bin/codex",
    "~/.npm-global/bin/codex", "~/.bun/bin/codex", "~/.volta/bin/codex",
    "~/.nvm/versions/node/*/bin/codex", "~/Library/pnpm/codex",
)
CODEX_SESSIONS = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"

SANDBOXES = ("read-only", "workspace-write", "danger-full-access")
EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
APPROVALS = ("never", "on-request", "untrusted")

# A blocking call is capped by Claude Code's MCP tool timeout, which is the
# per-server `timeout` field in .claude.json (or MCP_TOOL_TIMEOUT, or its very
# large default). Keep MAX_WAIT below whatever that is set to.
MAX_WAIT = 3600
DEFAULT_WAIT = 240

RUNS_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    """Diagnostics go to stderr; stdout is reserved for the MCP protocol."""
    print(f"[codex-bridge] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# run bookkeeping
# --------------------------------------------------------------------------- #


def new_run_id() -> str:
    return time.strftime("%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def run_dir(run_id: str) -> Path:
    d = RUNS_DIR / run_id
    if not d.is_dir():
        raise ValueError(f"unknown run_id {run_id!r} (use codex_list to see runs)")
    return d


def read_meta(d: Path) -> dict:
    try:
        return json.loads((d / "meta.json").read_text())
    except Exception:
        return {}


def write_meta(d: Path, meta: dict) -> None:
    (d / "meta.json").write_text(json.dumps(meta, indent=2))


def read_events(d: Path) -> list:
    events = []
    f = d / "events.jsonl"
    if not f.exists():
        return events
    for line in f.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue  # codex mixes a little human-readable noise into stdout
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def exit_code(d: Path):
    f = d / "exit_code"
    if not f.exists():
        return None
    try:
        return int(f.read_text().strip())
    except Exception:
        return -1


def is_running(d: Path) -> bool:
    return exit_code(d) is None


def session_id_of(d: Path) -> str | None:
    meta = read_meta(d)
    if meta.get("session_id"):
        return meta["session_id"]
    for ev in read_events(d):
        if ev.get("type") == "thread.started" and ev.get("thread_id"):
            meta["session_id"] = ev["thread_id"]
            write_meta(d, meta)
            return ev["thread_id"]
    return None


# --------------------------------------------------------------------------- #
# launching codex
# --------------------------------------------------------------------------- #


def validate(name: str, value, allowed, default=None):
    if value is None:
        return default
    value = str(value).strip()
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)} (got {value!r})")
    return value


def resolve_codex() -> str | None:
    """Absolute path of the codex binary, or None when it is not installed anywhere we know."""
    if os.sep in CODEX_BIN:
        path = os.path.expanduser(CODEX_BIN)
        return path if os.access(path, os.X_OK) else None
    found = shutil.which(CODEX_BIN)
    if found:
        return found
    for pattern in CODEX_FALLBACKS:
        for path in sorted(glob.glob(os.path.expanduser(pattern)), reverse=True):
            if os.access(path, os.X_OK):
                return path
    return None


def codex_or_raise() -> str:
    path = resolve_codex()
    if not path:
        raise ValueError(f"the Codex CLI (`{CODEX_BIN}`) was not found. {INSTALL_HINT}")
    return path


def build_argv(prompt: str, *, cwd: str, resume_session: str | None, model: str | None,
               effort: str | None, sandbox: str, approval: str | None,
               last_message_file: Path, extra_config: dict | None) -> list:
    argv = [codex_or_raise(), "exec", "--json", "--skip-git-repo-check",
            "-C", cwd, "-s", sandbox,
            "-o", str(last_message_file)]
    if model:
        argv += ["-m", model]
    if effort:
        argv += ["-c", f"model_reasoning_effort={effort}"]
    if approval:
        argv += ["-c", f"approval_policy={json.dumps(approval)}"]
    for key, val in (extra_config or {}).items():
        argv += ["-c", f"{key}={json.dumps(val) if not isinstance(val, str) else val}"]
    if resume_session:
        argv += ["resume", resume_session]
    # a prompt starting with '-' would be read as a flag
    argv.append(" " + prompt if prompt.startswith("-") else prompt)
    return argv


def launch(prompt: str, *, cwd: str, resume_session: str | None = None,
           model: str | None = None, effort: str | None = None,
           sandbox: str = "read-only", approval: str | None = None,
           extra_config: dict | None = None, label: str | None = None) -> Path:
    """Start codex detached. Returns the run directory."""
    cwd = str(Path(cwd).expanduser().resolve())
    if not Path(cwd).is_dir():
        raise ValueError(f"cwd {cwd!r} is not a directory")
    codex = codex_or_raise()

    rid = new_run_id()
    d = RUNS_DIR / rid
    d.mkdir(parents=True)

    argv = build_argv(prompt, cwd=cwd, resume_session=resume_session, model=model,
                      effort=effort, sandbox=sandbox, approval=approval,
                      last_message_file=d / "last.txt", extra_config=extra_config)

    # A shell wrapper records the exit code, so a finished run is detectable even
    # after this MCP server restarts.
    inner = " ".join(shlex.quote(a) for a in argv)
    script = (f"{inner} > {shlex.quote(str(d / 'events.jsonl'))} "
              f"2> {shlex.quote(str(d / 'stderr.log'))}; "
              f"echo $? > {shlex.quote(str(d / 'exit_code'))}")

    # an npm-installed codex is a node script; node usually sits next to it
    env = {**os.environ, "PATH": os.path.dirname(codex) + os.pathsep + os.environ.get("PATH", "")}
    proc = subprocess.Popen(["/bin/sh", "-c", script], cwd=cwd, env=env,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)

    write_meta(d, {
        "run_id": rid, "pid": proc.pid, "cwd": cwd, "prompt": prompt,
        "model": model, "effort": effort, "sandbox": sandbox, "approval": approval,
        "label": label, "resumed_from": resume_session,
        "session_id": resume_session,  # replaced by thread.started for new sessions
        "started_at": time.time(), "argv": argv,
    })
    log(f"launched run {rid}: {inner[:160]}")
    return d


def wait_for(d: Path, seconds: float) -> bool:
    """Block until the run finishes or the budget runs out. True if finished."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not is_running(d):
            return True
        time.sleep(0.4)
    return not is_running(d)


def cancel(d: Path) -> str:
    if not is_running(d):
        return "already finished"
    pid = read_meta(d).get("pid")
    if not pid:
        return "no pid recorded"
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        return "process already gone"
    if not wait_for(d, 5):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    (d / "exit_code").write_text("-15\n")
    return "cancelled"


# --------------------------------------------------------------------------- #
# rendering codex events
# --------------------------------------------------------------------------- #


def clip(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [{len(text) - limit} more chars]"


# Codex reports these as `error` items, but they are informational and would
# otherwise make every single run look like it failed.
BENIGN_NOTICES = ("Skill descriptions were shortened",)


def is_benign_notice(item: dict) -> bool:
    if item.get("type") != "error":
        return False
    message = item.get("message", "")
    return any(message.startswith(prefix) for prefix in BENIGN_NOTICES)


def item_line(item: dict, verbose: bool) -> str | None:
    kind = item.get("type")
    if kind == "agent_message":
        return "ASSISTANT:\n" + clip(item.get("text", ""), 8000 if verbose else 4000)
    if kind == "reasoning":
        if not verbose:
            return None
        text = item.get("text") or item.get("summary") or ""
        return "thinking: " + clip(text, 1500) if text else None
    if kind == "command_execution":
        cmd = clip(item.get("command", ""), 300)
        status = item.get("exit_code")
        head = f"$ {cmd}" + (f"  (exit {status})" if status is not None else "")
        if verbose and item.get("aggregated_output"):
            return head + "\n" + clip(item["aggregated_output"], 2000)
        return head
    if kind == "file_change":
        changes = item.get("changes") or item.get("files") or []
        names = [c.get("path", str(c)) if isinstance(c, dict) else str(c) for c in changes]
        return "edited: " + ", ".join(names[:20]) if names else "edited files"
    if kind == "mcp_tool_call":
        return f"mcp: {item.get('server', '?')}.{item.get('tool', '?')}"
    if kind == "web_search":
        return f"search: {item.get('query', '')}"
    if kind == "todo_list":
        items = item.get("items") or []
        return "plan: " + "; ".join(str(i.get("text", i)) for i in items[:10])
    if kind == "error":
        return "ERROR: " + clip(item.get("message", ""), 1500)
    return f"{kind}: " + clip(json.dumps(item, ensure_ascii=False), 400) if verbose else None


def summarize(d: Path, verbose: bool = False) -> str:
    meta = read_meta(d)
    events = read_events(d)
    sid = session_id_of(d)
    running = is_running(d)
    code = exit_code(d)

    messages, lines, usage, errors = [], [], None, []
    for ev in events:
        etype = ev.get("type")
        if etype == "item.completed":
            item = ev.get("item", {})
            if is_benign_notice(item):
                continue
            if item.get("type") == "agent_message":
                messages.append(item.get("text", ""))
            if item.get("type") == "error":
                errors.append(item.get("message", ""))
            rendered = item_line(item, verbose)
            if rendered:
                lines.append(rendered)
        elif etype == "turn.completed":
            usage = ev.get("usage")
        elif etype in ("turn.failed", "error"):
            errors.append(json.dumps(ev.get("error") or ev, ensure_ascii=False)[:800])

    elapsed = int(time.time() - meta.get("started_at", time.time()))
    if running:
        state = f"RUNNING ({elapsed}s so far)"
    elif code == 0:
        state = f"DONE in {elapsed}s"
    else:
        state = f"EXITED code {code} after {elapsed}s"

    out = [
        f"run_id:    {meta.get('run_id')}   [{state}]",
        f"session:   {sid or '(not started yet)'}",
        f"model:     {meta.get('model') or 'codex default'}"
        f"   effort: {meta.get('effort') or 'codex default'}"
        f"   sandbox: {meta.get('sandbox')}",
        f"cwd:       {meta.get('cwd')}",
    ]
    if meta.get("label"):
        out.insert(1, f"label:     {meta['label']}")
    if sid:
        out.append(f"take over: cd {shlex.quote(meta.get('cwd', '.'))} && codex resume {sid}")
    out.append("")

    if verbose and lines:
        out.append("--- transcript ---")
        out.extend(lines)
        out.append("")
    elif lines:
        activity = [l for l in lines if not l.startswith("ASSISTANT:")]
        if activity:
            out.append(f"activity ({len(activity)} steps), last few:")
            out.extend("  " + l.splitlines()[0] for l in activity[-6:])
            out.append("")

    if messages:
        out.append("--- codex says ---" if verbose else "--- latest answer ---")
        chosen = messages if verbose else messages[-1:]
        out.append("\n\n".join(clip(m, 12000 if verbose else 6000) for m in chosen))
    elif running:
        out.append("(no answer yet - still working)")

    if errors:
        out.append("")
        out.append("--- errors ---")
        out.extend("  " + e.splitlines()[0] for e in errors[-5:])

    stderr_file = d / "stderr.log"
    if not running and code not in (0, None) and stderr_file.exists():
        tail = stderr_file.read_text(errors="replace").splitlines()
        tail = [l for l in tail if "rmcp::transport" not in l and "codex_rmcp_client" not in l]
        if tail:
            out.append("")
            out.append("--- stderr tail ---")
            out.extend("  " + l for l in tail[-15:])

    if usage:
        out.append("")
        out.append(f"tokens: in={usage.get('input_tokens')} "
                   f"cached={usage.get('cached_input_tokens')} "
                   f"out={usage.get('output_tokens')} "
                   f"reasoning={usage.get('reasoning_output_tokens')}")

    if running:
        out.append("")
        out.append(f"Still running. Poll with codex_check(run_id=\"{meta.get('run_id')}\") "
                   "or stop it with codex_cancel.")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# listing sessions
# --------------------------------------------------------------------------- #


def list_runs(limit: int) -> str:
    dirs = sorted((p for p in RUNS_DIR.iterdir() if p.is_dir()),
                  key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    if not dirs:
        return "No bridge runs yet."
    rows = ["Runs launched through this bridge (newest first):", ""]
    for d in dirs:
        meta = read_meta(d)
        sid = session_id_of(d)
        state = "running" if is_running(d) else (
            "done" if exit_code(d) == 0 else f"exit {exit_code(d)}")
        prompt = (meta.get("label") or meta.get("prompt") or "").replace("\n", " ")[:70]
        rows.append(f"  {meta.get('run_id')}  [{state:>8}]  {meta.get('model') or 'default'}"
                    f"/{meta.get('effort') or 'default'}  {prompt}")
        if sid:
            rows.append(f"      resume: cd {shlex.quote(meta.get('cwd', '.'))} && codex resume {sid}")
    return "\n".join(rows)


def list_codex_sessions(limit: int) -> str:
    if not CODEX_SESSIONS.is_dir():
        return "No ~/.codex/sessions directory found."
    files = sorted(CODEX_SESSIONS.rglob("rollout-*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    rows = ["Recent Codex sessions on this machine (any origin, newest first):", ""]
    for f in files:
        sid, cwd, source, first = None, "?", "?", ""
        try:
            with f.open(errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i > 60:
                        break
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = rec.get("payload", {})
                    if rec.get("type") == "session_meta":
                        sid = payload.get("session_id")
                        cwd = payload.get("cwd", "?")
                        source = payload.get("source", "?")
                    if not first:
                        text = json.dumps(payload, ensure_ascii=False)
                        if '"role": "user"' in text or '"role":"user"' in text:
                            first = text[:120]
        except OSError:
            continue
        if not sid:
            continue
        when = time.strftime("%m-%d %H:%M", time.localtime(f.stat().st_mtime))
        rows.append(f"  {when}  [{source}]  {sid}")
        rows.append(f"      cwd: {cwd}")
        rows.append(f"      resume: cd {shlex.quote(cwd)} && codex resume {sid}")
    return "\n".join(rows)


# --------------------------------------------------------------------------- #
# tool definitions
# --------------------------------------------------------------------------- #

MODEL_HINT = ("Codex model slug, e.g. gpt-6-astra, gpt-5.6-luna, gpt-5.6-terra, gpt-5.6-pro, "
              "gpt-5.5, gpt-5.3-codex. Omit to use whatever ~/.codex/config.toml sets.")
EFFORT_HINT = "Reasoning effort: minimal, low, medium, high, xhigh, max. Omit for the Codex default."
SANDBOX_HINT = ("Permission mode. read-only = can read and run read-only commands, cannot write. "
                "workspace-write = can edit files under cwd. danger-full-access = no sandbox at all "
                "(implies bypassing approvals; only for throwaway or already-isolated dirs).")
CWD_HINT = ("Absolute path Codex should treat as its workspace root. Always pass the repo you mean; "
            "it defaults to this server's working directory otherwise.")

COMMON_PROPS = {
    "model": {"type": "string", "description": MODEL_HINT},
    "effort": {"type": "string", "enum": list(EFFORTS), "description": EFFORT_HINT},
    "sandbox": {"type": "string", "enum": list(SANDBOXES), "description": SANDBOX_HINT},
    "cwd": {"type": "string", "description": CWD_HINT},
    "approval": {"type": "string", "enum": list(APPROVALS),
                 "description": "Approval policy. Headless runs cannot answer prompts, so this "
                                "defaults to never; on-request will simply refuse risky steps."},
    "config": {"type": "object", "additionalProperties": True,
               "description": "Extra ~/.codex/config.toml overrides, e.g. {\"model_verbosity\": \"low\"}."},
}

TOOLS = [
    {
        "name": "codex_ask",
        "description": (
            "Ask OpenAI Codex a question and wait for the answer. Use this to get a second "
            "opinion, a deep review, or a hard reasoning call from a non-Claude model. "
            "Read-only by default, so it can inspect the repo but not change it. If the answer "
            "takes longer than wait_seconds the session keeps running in the background and you "
            "get a run_id to poll with codex_check - no work is lost. Every result includes a "
            "`codex resume <session_id>` command the user can paste into a terminal to take the "
            "session over themselves."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["prompt"],
            "additionalProperties": False,
            "properties": {
                "prompt": {"type": "string", "description": "The question or task for Codex."},
                "wait_seconds": {"type": "integer",
                                 "description": f"How long to block, default {DEFAULT_WAIT}, max {MAX_WAIT}."},
                "verbose": {"type": "boolean",
                            "description": "Include the full transcript (commands, reasoning) not just the answer."},
                **COMMON_PROPS,
            },
        },
    },
    {
        "name": "codex_start",
        "description": (
            "Launch a Codex session in the background and return immediately with a run_id and "
            "session_id. Use this for real work that takes minutes - implementing something, a "
            "long investigation, a big refactor. Defaults to workspace-write so Codex can edit "
            "files under cwd. Poll with codex_check, continue with codex_reply, stop with "
            "codex_cancel, or hand the user `codex resume <session_id>` to take over live."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["prompt"],
            "additionalProperties": False,
            "properties": {
                "prompt": {"type": "string", "description": "The task for Codex."},
                "label": {"type": "string", "description": "Short name to recognise this run later."},
                **COMMON_PROPS,
            },
        },
    },
    {
        "name": "codex_check",
        "description": (
            "Check a Codex run: state, what it has done so far, its latest answer, token usage, "
            "and the takeover command. Omit run_id to get the most recent run. Set wait_seconds "
            "to block until the run finishes instead of returning right away."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "run_id": {"type": "string", "description": "Run to inspect. Defaults to the newest."},
                "verbose": {"type": "boolean",
                            "description": "Full transcript: every command, file change, and message."},
                "wait_seconds": {"type": "integer",
                                 "description": f"Block up to this long waiting for the run to finish (max {MAX_WAIT})."},
            },
        },
    },
    {
        "name": "codex_reply",
        "description": (
            "Send a follow-up turn into an existing Codex session, keeping its full context. "
            "Identify it by run_id or by session_id (a raw Codex session works too, including "
            "one the user started in their own terminal). Blocks like codex_ask and falls back "
            "to background on timeout."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["prompt"],
            "additionalProperties": False,
            "properties": {
                "prompt": {"type": "string", "description": "The follow-up message."},
                "run_id": {"type": "string", "description": "Bridge run to continue."},
                "session_id": {"type": "string",
                               "description": "Codex session UUID to continue (alternative to run_id)."},
                "wait_seconds": {"type": "integer", "description": f"Default {DEFAULT_WAIT}, max {MAX_WAIT}."},
                "verbose": {"type": "boolean", "description": "Include the full transcript."},
                **COMMON_PROPS,
            },
        },
    },
    {
        "name": "codex_list",
        "description": (
            "List Codex sessions with their takeover commands - runs launched through this bridge, "
            "and optionally every recent Codex session on the machine including ones started by "
            "hand in a terminal."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "limit": {"type": "integer", "description": "How many to list, default 15."},
                "include_all_codex_sessions": {
                    "type": "boolean",
                    "description": "Also list sessions from ~/.codex/sessions, not just bridge runs."},
            },
        },
    },
    {
        "name": "codex_cancel",
        "description": "Stop a running Codex session. The session stays on disk and is still resumable.",
        "inputSchema": {
            "type": "object",
            "required": ["run_id"],
            "additionalProperties": False,
            "properties": {"run_id": {"type": "string"}},
        },
    },
    {
        "name": "codex_status",
        "description": ("Check that Codex is usable before relying on it: whether the codex CLI is "
                        "installed, its version, and whether it is logged in. Fast and free - it "
                        "starts no Codex session. `ready: yes` means codex_ask will work."),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
]


# --------------------------------------------------------------------------- #
# tool implementations
# --------------------------------------------------------------------------- #


def newest_run() -> Path:
    dirs = sorted((p for p in RUNS_DIR.iterdir() if p.is_dir()),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if not dirs:
        raise ValueError("no Codex runs yet")
    return dirs[0]


def common_args(args: dict, default_sandbox: str) -> dict:
    return {
        "model": args.get("model") or None,
        "effort": validate("effort", args.get("effort"), EFFORTS),
        "sandbox": validate("sandbox", args.get("sandbox"), SANDBOXES, default_sandbox),
        "approval": validate("approval", args.get("approval"), APPROVALS, "never"),
        "cwd": args.get("cwd") or os.getcwd(),
        "extra_config": args.get("config") or None,
    }


def clamp_wait(args: dict) -> int:
    return max(5, min(int(args.get("wait_seconds") or DEFAULT_WAIT), MAX_WAIT))


def tool_ask(args: dict) -> str:
    d = launch(args["prompt"], **common_args(args, "read-only"), label=args.get("label"))
    wait_for(d, clamp_wait(args))
    return summarize(d, verbose=bool(args.get("verbose")))


def tool_start(args: dict) -> str:
    d = launch(args["prompt"], **common_args(args, "workspace-write"), label=args.get("label"))
    wait_for(d, 6)  # just long enough to capture the session id
    return summarize(d)


def tool_reply(args: dict) -> str:
    sid = args.get("session_id")
    cwd = args.get("cwd")
    if not sid:
        if not args.get("run_id"):
            raise ValueError("pass run_id or session_id")
        src = run_dir(args["run_id"])
        if is_running(src):
            raise ValueError("that run is still working - wait for it or cancel it first")
        sid = session_id_of(src)
        if not sid:
            raise ValueError("that run never started a session; check codex_check for errors")
        cwd = cwd or read_meta(src).get("cwd")
        args = {**args, "model": args.get("model") or read_meta(src).get("model"),
                "effort": args.get("effort") or read_meta(src).get("effort"),
                "sandbox": args.get("sandbox") or read_meta(src).get("sandbox")}
    base = common_args({**args, "cwd": cwd or args.get("cwd")}, "workspace-write")
    d = launch(args["prompt"], resume_session=sid, **base, label=args.get("label"))
    wait_for(d, clamp_wait(args))
    return summarize(d, verbose=bool(args.get("verbose")))


def tool_check(args: dict) -> str:
    d = run_dir(args["run_id"]) if args.get("run_id") else newest_run()
    if args.get("wait_seconds"):
        wait_for(d, clamp_wait(args))
    return summarize(d, verbose=bool(args.get("verbose")))


def tool_list(args: dict) -> str:
    limit = int(args.get("limit") or 15)
    out = [list_runs(limit)]
    if args.get("include_all_codex_sessions"):
        out.append("")
        out.append(list_codex_sessions(limit))
    return "\n".join(out)


def tool_status(args: dict) -> str:
    path = resolve_codex()
    if not path:
        return f"ready: no\ncodex: not found\nfix: {INSTALL_HINT}"
    env = {**os.environ, "PATH": os.path.dirname(path) + os.pathsep + os.environ.get("PATH", "")}

    def run(*argv):
        try:
            p = subprocess.run([path, *argv], capture_output=True, text=True, timeout=20,
                               stdin=subprocess.DEVNULL, env=env)
            return p.returncode, (p.stdout + p.stderr).strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, str(exc)

    _, version = run("--version")
    code, login = run("login", "status")
    lines = [f"ready: {'yes' if code == 0 else 'no'}", f"codex: {path} ({version})",
             f"login: {login or 'unknown'}"]
    if code != 0:
        lines.append("fix: run `codex login` once in a terminal, then try again.")
    return "\n".join(lines)


def tool_cancel(args: dict) -> str:
    d = run_dir(args["run_id"])
    result = cancel(d)
    return f"{args['run_id']}: {result}\n\n" + summarize(d)


HANDLERS = {
    "codex_ask": tool_ask,
    "codex_start": tool_start,
    "codex_check": tool_check,
    "codex_reply": tool_reply,
    "codex_list": tool_list,
    "codex_cancel": tool_cancel,
    "codex_status": tool_status,
}


# --------------------------------------------------------------------------- #
# MCP plumbing (JSON-RPC 2.0 over stdio, line delimited)
# --------------------------------------------------------------------------- #


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(req: dict):
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "codex-bridge", "version": "1.1.0"},
            "instructions": (
                "Drives OpenAI Codex locally. codex_status to check Codex is installed and logged in, "
                "codex_ask for a blocking question, codex_start for background work, codex_check to poll, codex_reply to continue a session. Always "
                "show the user the `codex resume <session_id>` line so they can take over."
            ),
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if not fn:
            raise ValueError(f"unknown tool {name!r}")
        try:
            text = fn(args)
        except Exception as exc:  # surface as a tool error, not a protocol error
            log(f"tool {name} failed: {exc!r}")
            return {"content": [{"type": "text", "text": f"codex-bridge error: {exc}"}],
                    "isError": True}
        return {"content": [{"type": "text", "text": text}]}
    if rid is None:
        return None
    raise LookupError(f"method not found: {method}")


def main() -> None:
    log(f"ready - state in {STATE_DIR}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        try:
            result = handle(req)
        except LookupError as exc:
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": str(exc)}})
            continue
        except Exception as exc:
            log(f"request failed: {exc!r}")
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid,
                      "error": {"code": -32603, "message": str(exc)}})
            continue
        if rid is not None and result is not None:
            send({"jsonrpc": "2.0", "id": rid, "result": result})


CLI_USAGE = """codex-bridge

  server.py                       run as an MCP server on stdio (what Claude Code does)
  server.py runs [N]              list recent runs
  server.py show <run_id> [-v]    print a run's status and answer
  server.py wait <run_id> [-v]    block until the run finishes, then print it
  server.py cancel <run_id>       stop a run

`wait` is the one worth knowing: run it as a background shell job and the harness
tells you the moment Codex is done, so nothing has to poll.
"""


def cli(argv: list) -> int:
    cmd = argv[0]
    verbose = "-v" in argv or "--verbose" in argv
    rest = [a for a in argv[1:] if not a.startswith("-")]
    if cmd in ("-h", "--help", "help"):
        print(CLI_USAGE)
        return 0
    if cmd == "runs":
        print(list_runs(int(rest[0]) if rest else 15))
        return 0
    if not rest:
        print(f"{cmd} needs a run_id\n\n{CLI_USAGE}", file=sys.stderr)
        return 2
    d = run_dir(rest[0])
    if cmd == "wait":
        wait_for(d, MAX_WAIT)
    elif cmd == "cancel":
        print(cancel(d))
    elif cmd != "show":
        print(f"unknown command {cmd!r}\n\n{CLI_USAGE}", file=sys.stderr)
        return 2
    print(summarize(d, verbose=verbose))
    return 0 if not is_running(d) else 1


if __name__ == "__main__":
    try:
        sys.exit(cli(sys.argv[1:]) if len(sys.argv) > 1 else (main() or 0))
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    except (ValueError, LookupError) as exc:
        print(f"codex-bridge: {exc}", file=sys.stderr)
        sys.exit(2)
