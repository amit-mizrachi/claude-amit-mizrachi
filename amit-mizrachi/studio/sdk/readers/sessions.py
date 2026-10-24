"""Session readers: background sessions (`claude agents`, `~/.claude/jobs`) and transcripts.

Three sources, merged later by the full session id (`sessionId`, the id that survives a resume):
- `agents()` - `claude agents --json --all`: the live list. A failed call is UNKNOWN, never empty.
- `jobs()` - `<claude home>/jobs/<short id>/state.json`: name, cwd, state of bg jobs, also after
  the session left `claude agents`.
- `transcripts()` - `<claude home>/projects/*/<sessionId>.jsonl`: every session that ever ran.
  Its first rows carry `cwd`, `gitBranch`, `sessionKind` and `entrypoint`. Headless `claude -p`
  runs (`entrypoint: sdk-*`) are never items. A bg job pruned from `jobs/` is still resolved
  from its transcript, so it keeps its cwd and name.
- `conductor_scan()` - which sessions ran a run's conductor commands (`runner.sh start <WS>`,
  `bash <WS>/launch.sh`, `schedule.sh <WS>`): the conductor of a run that has no
  `state/CONDUCTOR.session`. It reads each recent transcript once, from where the last scan
  stopped (transcripts only grow), at most SCAN_BUDGET bytes a scan, newest transcripts first.

These only READ. They never attach, stop or remove a session.
"""

import glob
import json
import os
import re
import time

from . import commands
from .git import Read

RECENT_DAYS = 14            # a transcript older than this is not read for discovery
HEAD_LINES = 80
HEAD_BYTES = 512 * 1024
SCAN_BUDGET = 128 * 1024 * 1024     # transcript bytes one conductor scan reads at most
SCAN_CHUNK = 4 * 1024 * 1024
CONDUCTOR_MARKS = (b"runner.sh", b"launch.sh", b"schedule.sh")
CONDUCTOR_COMMANDS = (re.compile(r"runner\.sh\s+start\s+(\S+)"), re.compile(r"(\S+)/launch\.sh\b"),
                      re.compile(r"schedule\.sh\s+(\S+)"))


def iso(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds)) if seconds else ""


def _ms_iso(value):
    return iso(value / 1000.0) if isinstance(value, (int, float)) and value > 0 else ""


def agents():
    """Every row `claude agents --json --all` lists, as {short, session_id, name, cwd, state, ...}."""
    ok, out, error = commands.run(["claude", "agents", "--json", "--all"])
    if not ok:
        return Read(False, [], error or "claude agents failed")
    try:
        rows = json.loads(out)
    except ValueError:
        return Read(False, [], "claude agents printed something that is not JSON")
    if not isinstance(rows, list):
        return Read(False, [], "claude agents did not print a list")
    records = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("sessionId"):
            continue
        records.append({
            "session_id": str(row["sessionId"]), "short": str(row.get("id") or row["sessionId"][:8]),
            "name": str(row.get("name") or ""), "cwd": str(row.get("cwd") or ""),
            "state": str(row.get("state") or ""), "activity": str(row.get("status") or ""),
            "waiting_for": str(row.get("waitingFor") or ""), "started_at": _ms_iso(row.get("startedAt")),
            "agent_kind": str(row.get("kind") or ""),
        })
    return Read(True, records)


def jobs():
    """Every `jobs/<short>/state.json` that parses, as {short, session_id, name, cwd, state, ...}."""
    folder = os.path.join(commands.claude_home(), "jobs")
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return Read(True, [])
    except OSError as exc:
        return Read(False, [], "could not list %s: %s" % (folder, exc))
    records = []
    for name in names:
        try:
            with open(os.path.join(folder, name, "state.json")) as fh:
                row = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(row, dict) or not row.get("sessionId"):
            continue
        records.append(_job_record(row, name))
    return Read(True, records)


def _job_record(row, short):
    return {
        "session_id": str(row["sessionId"]), "short": str(row.get("daemonShort") or short),
        "name": str(row.get("name") or ""), "cwd": str(row.get("cwd") or ""),
        "state": str(row.get("state") or ""), "detail": str(row.get("detail") or "")[:200],
        "created_at": str(row.get("createdAt") or ""), "updated_at": str(row.get("updatedAt") or ""),
    }


def job_state(job_dir):
    """One bg job's `state.json` (the `$CLAUDE_JOB_DIR` a bg session runs in) as a jobs() record,
    or None when it is missing or unreadable."""
    try:
        with open(os.path.join(job_dir, "state.json")) as fh:
            row = json.load(fh)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(row, dict) or not row.get("sessionId"):
        return None
    return _job_record(row, os.path.basename(job_dir.rstrip("/")))


def transcript_head(path):
    """What a transcript's first rows say: {title, cwd, git_branch, session_kind, entrypoint, started_at}."""
    meta = {"title": "", "cwd": "", "git_branch": "", "session_kind": "", "entrypoint": "", "started_at": ""}
    try:
        with open(path, "r", errors="replace") as fh:
            read = 0
            for _ in range(HEAD_LINES):
                line = fh.readline(HEAD_BYTES)
                if not line:
                    break
                read += len(line)
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("type") == "custom-title" and row.get("customTitle"):
                    meta["title"] = str(row["customTitle"])
                if row.get("cwd") and not meta["cwd"]:
                    meta.update(cwd=str(row["cwd"]), git_branch=str(row.get("gitBranch") or ""),
                                session_kind=str(row.get("sessionKind") or ""),
                                entrypoint=str(row.get("entrypoint") or ""),
                                started_at=str(row.get("timestamp") or ""))
                if meta["cwd"] and meta["title"] or read > HEAD_BYTES:
                    break
    except OSError:
        return None
    return meta


def session_kind(meta):
    """'session-bg', 'session-interactive', or None for a headless run or an empty transcript."""
    if not meta or not meta.get("cwd") or meta.get("entrypoint", "").startswith("sdk"):
        return None
    return "session-bg" if meta.get("session_kind") == "bg" else "session-interactive"


def transcripts(previous=None, now=None):
    """{"index": {sid: [path, mtime]}, "meta": {sid: head}} over every top-level transcript.

    The index lists every transcript (names and stats only), so a known session is found however
    old it is. Heads are read only for transcripts touched in the last RECENT_DAYS, and a head
    read on an earlier scan (`previous`) is reused, since a transcript's first rows never change.
    """
    now = now or time.time()
    base = os.path.join(commands.claude_home(), "projects")
    if not os.path.isdir(base):
        return Read(True, {"index": {}, "meta": {}})
    old_meta = (previous or {}).get("meta") or {}
    index, meta = {}, {}
    try:
        paths = glob.glob(os.path.join(base, "*", "*.jsonl"))
    except OSError as exc:
        return Read(False, {"index": {}, "meta": {}}, "could not list %s: %s" % (base, exc))
    for path in paths:
        sid = os.path.basename(path)[:-len(".jsonl")]
        try:
            stamp = os.stat(path).st_mtime
        except OSError:
            continue
        if sid in index and index[sid][1] >= stamp:
            continue
        index[sid] = [path, stamp]
    for sid, (path, stamp) in index.items():
        if sid in old_meta:
            meta[sid] = old_meta[sid]
        elif now - stamp <= RECENT_DAYS * 86400:
            head = transcript_head(path)
            if head is not None:
                meta[sid] = head
    return Read(True, {"index": index, "meta": meta})


def _workspaces_run(command):
    """The absolute workspace folders a conductor command names (quotes and a trailing / dropped)."""
    out = []
    for pattern in CONDUCTOR_COMMANDS:
        for found in pattern.findall(command):
            path = os.path.expanduser(found.strip("\"';&|()")).rstrip("/")
            if os.path.isabs(path) and path not in out:
                out.append(path)
    return out


def _bash_commands(line):
    """(timestamp, [command]) of one transcript row's Bash tool calls; [] for any other row."""
    try:
        row = json.loads(line)
    except ValueError:
        return "", []
    message = row.get("message") if isinstance(row, dict) and row.get("type") == "assistant" else None
    content = message.get("content") if isinstance(message, dict) else None
    calls = [c.get("input") or {} for c in content or [] if isinstance(c, dict) and c.get("type") == "tool_use"
             and c.get("name") == "Bash"]
    return str(row.get("timestamp") or ""), [str(c.get("command") or "") for c in calls if isinstance(c, dict)]


def _scan_hits(block, hits):
    """Add {workspace: newest timestamp} for every conductor command in a block of whole lines."""
    if not any(mark in block for mark in CONDUCTOR_MARKS):
        return
    for line in block.split(b"\n"):
        if not any(mark in line for mark in CONDUCTOR_MARKS):
            continue
        stamp, commands_run = _bash_commands(line.decode("utf-8", "replace"))
        for command in commands_run:
            for ws in _workspaces_run(command):
                hits[ws] = max(hits.get(ws, ""), stamp)


def _scan_file(path, offset, hits, budget):
    """Read whole lines of `path` from `offset`, at most `budget` bytes. Returns the new offset."""
    with open(path, "rb") as fh:
        fh.seek(offset)
        while budget > 0:
            block = fh.read(min(SCAN_CHUNK, budget))
            cut = block.rfind(b"\n") + 1
            if not cut and len(block) == SCAN_CHUNK:
                block += fh.readline()               # one line longer than a chunk
                cut = len(block) if block.endswith(b"\n") else 0
            if not cut:
                break                                # the end, or a line still being written
            _scan_hits(block[:cut], hits)
            offset, budget = offset + cut, budget - cut
            fh.seek(offset)
    return offset


def conductor_scan(previous=None, now=None, budget=SCAN_BUDGET):
    """{"files": {sid: [path, offset, {workspace: timestamp}]}}: where each recent transcript ran a
    conductor command. `previous` is the last scan's data; each transcript is read on from its
    offset (from 0 when it shrank). A transcript with hits is kept however old it is. `partial`
    is True while unread bytes are left over the budget."""
    now = now or time.time()
    base = os.path.join(commands.claude_home(), "projects")
    old = ((previous or {}).get("files") or {}) if isinstance(previous, dict) else {}
    if not os.path.isdir(base):
        return Read(True, {"files": {}})
    try:
        paths = glob.glob(os.path.join(base, "*", "*.jsonl"))
    except OSError as exc:
        return Read(False, {"files": old}, "could not list %s: %s" % (base, exc))
    found = []
    for path in paths:
        try:
            st = os.stat(path)
        except OSError:
            continue
        sid = os.path.basename(path)[:-len(".jsonl")]
        before = old.get(sid)
        if now - st.st_mtime <= RECENT_DAYS * 86400 or (before and before[2]):
            found.append((st.st_mtime, st.st_size, sid, path))
    files, left = {}, False
    for _, size, sid, path in sorted(found, reverse=True):
        before = old.get(sid)
        offset, hits = (before[1], dict(before[2])) if before and before[0] == path and before[1] <= size else (0, {})
        if offset < size and budget > 0:
            try:
                new = _scan_file(path, offset, hits, budget)
            except OSError:
                new = offset
            budget -= new - offset
            offset = new
        left = left or size - offset > SCAN_CHUNK
        files[sid] = [path, offset, hits]
    return Read(True, {"files": files}, partial=left)
