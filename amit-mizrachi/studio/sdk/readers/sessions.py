"""Session readers: background sessions (`claude agents`, `~/.claude/jobs`) and transcripts.

Three sources, merged later by the full session id (`sessionId`, the id that survives a resume):
- `agents()` - `claude agents --json --all`: the live list. A failed call is UNKNOWN, never empty.
- `jobs()` - `<claude home>/jobs/<short id>/state.json`: name, cwd, state of bg jobs, also after
  the session left `claude agents`.
- `transcripts()` - `<claude home>/projects/*/<sessionId>.jsonl`: every session that ever ran.
  Its first rows carry `cwd`, `gitBranch`, `sessionKind` and `entrypoint`. Headless `claude -p`
  runs (`entrypoint: sdk-*`) are never items. A bg job pruned from `jobs/` is still resolved
  from its transcript, so it keeps its cwd and name.

These only READ. They never attach, stop or remove a session.
"""

import glob
import json
import os
import time

from . import commands
from .git import Read

RECENT_DAYS = 14            # a transcript older than this is not read for discovery
HEAD_LINES = 80
HEAD_BYTES = 512 * 1024


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
        records.append({
            "session_id": str(row["sessionId"]), "short": str(row.get("daemonShort") or name),
            "name": str(row.get("name") or ""), "cwd": str(row.get("cwd") or ""),
            "state": str(row.get("state") or ""), "detail": str(row.get("detail") or "")[:200],
            "created_at": str(row.get("createdAt") or ""), "updated_at": str(row.get("updatedAt") or ""),
        })
    return Read(True, records)


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
