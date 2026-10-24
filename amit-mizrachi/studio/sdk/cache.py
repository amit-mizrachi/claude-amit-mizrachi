"""The shared refresh cache: what each source said last, kept in the store's `cache` table.

Every process (MCP servers, the studio, hooks) shares it, so a `claude agents` call made by one
answers the others until its TTL runs out. A row is one (source, key) - say ("prs",
"owner/repo"). Its `payload_json` holds the LAST GOOD read and when it was made (`good_at`), so a
failed read keeps the last-good data and only records `ok = 0` and the `error`. Nothing that
reads a failed row may treat its records as complete.
"""

import calendar
import json
import time

from . import store

# Seconds a read stays fresh (spec: state files 2 s for live runs only, discover 60 s,
# `claude agents` 10 s, `gh pr list` 5 min per repo).
TTL = {
    "workspaces": 60,
    "workspace": 2,
    "agents": 10,
    "jobs": 10,
    "transcripts": 60,
    "conductors": 60,
    "worktrees": 60,
    "prs": 300,
}


def epoch(stamp):
    """ISO 8601 UTC (to the second) -> epoch seconds; 0 for '' or junk."""
    try:
        return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return 0


class Entry(object):
    """One cache row, decoded."""

    def __init__(self, row):
        self.source, self.key = row["source"], row["key"]
        self.fetched_at, self.ok, self.error = row["fetched_at"], bool(row["ok"]), row["error"] or ""
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except ValueError:
            payload = {}
        self.good_at = payload.get("good_at") or ""
        self.partial = bool(payload.get("partial"))
        self.data = payload.get("data")
        self.had_good = "data" in payload

    def due(self, now, ttl=None):
        """True when the row is older than its source's TTL."""
        return now - epoch(self.fetched_at) >= (TTL[self.source] if ttl is None else ttl)


def entries(conn):
    """{(source, key): Entry} for every cache row."""
    rows = conn.execute("SELECT source, key, fetched_at, ok, error, payload_json FROM cache")
    return {(r["source"], r["key"]): Entry(r) for r in rows}


def put(conn, source, key, read, previous=None):
    """Record one read. A good read replaces the payload; a failed one keeps the last-good payload."""
    stamp = store.now_iso()
    if read.ok:
        payload = {"good_at": stamp, "partial": bool(getattr(read, "partial", False)), "data": read.records}
    elif previous is not None and previous.had_good:
        payload = {"good_at": previous.good_at, "partial": previous.partial, "data": previous.data}
    else:
        payload = {}
    conn.execute("INSERT OR REPLACE INTO cache (source, key, fetched_at, ok, error, payload_json) "
                 "VALUES (?, ?, ?, ?, ?, ?)",
                 (source, key, stamp, 1 if read.ok else 0, "" if read.ok else (read.error or "read failed"),
                  json.dumps(payload, sort_keys=True)))
