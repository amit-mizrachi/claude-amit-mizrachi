"""The inventory: every source's cached read merged into one list of found items.

Input is the cache (`cache.entries`), never a live command, so the merge is pure and the same
for every process. Output:
- `found` - one `Found` per item, workspaces first. Each knows its kind, stable key, title,
  data, the signals rules match on, and its `link` to a workspace (with the rung that made
  it: `title` for a session named `ns-<slug>-<TAG>` or listed in `state/<TAG>.session`, `cwd` for
  a cwd, worktree, branch or artifact inside the run).
- `ok_scopes` / `present` - which scopes were read completely and which keys they hold. Only an
  item whose scope is in `ok_scopes` and whose key is not in `present` may be marked gone. A
  failed or partial read leaves its scope out, so nothing is retired on a bad read.
- `agents_ok` - False when `claude agents` failed: bg sessions are UNKNOWN, not idle or gone.

A run with no `CONDUCTOR.session` file gets its conductor from the conductor scan
(`sessions.conductor_scan`): the newest session that ran `runner.sh start <WS>`,
`bash <WS>/launch.sh` or `schedule.sh <WS>` and is not one of its ticket sessions (listed in a
`state/<TAG>.session`, or named `ns-<slug>-<TAG>`). It joins the run's `sessions`, so it attaches
by title like them.

A run's conductor whose transcript is older than the transcripts reader's window
(`sessions.RECENT_DAYS`) has no head in that read, so its head is read here from the index: the
conductor gets its session item (attached to the run by title) however old it is. A conductor
with no transcript on disk gets no item.
"""

import os
import re
import time

from .readers.git import repo_of_path
from .readers.sessions import iso, session_kind, transcript_head

ACTIVE_SECONDS = 300        # an interactive transcript touched this recently may still be open
DATE_SUFFIX = re.compile(r"-\d{8}(-\d+)?$")
TITLE_PREFIXES = ("ns-", "nm-")


class Found(object):
    def __init__(self, kind, key, title, data, scope, signals, link=None):
        self.kind, self.key, self.title = kind, key, title
        self.data, self.scope, self.signals = data, scope, signals
        self.link = link            # (workspace key, rung) or None


def _under(path, folder):
    return bool(path and folder) and (path == folder or path.startswith(folder.rstrip("/") + "/"))


class Joins(object):
    """Lookups from a child's facts to the workspace it belongs to."""

    def __init__(self, workspaces):
        self.slugs, self.sids, self.paths, self.branches = {}, {}, [], {}
        for ws in workspaces:
            for slug in ws.get("slugs", []):
                self.slugs.setdefault(slug, ws["path"])
            for sid in ws.get("sessions", []):
                self.sids.setdefault(sid, ws["path"])
                self.sids.setdefault(sid[:8], ws["path"])
            for tree in ws.get("worktrees", []) + [ws["path"]]:
                if tree:
                    self.paths.append((tree, ws["path"]))
            for branch in ws.get("branches", []):
                for repo in ws.get("repo_slugs", []) + [ws.get("repo_path", ""), ws.get("repo_slug", "")]:
                    if repo:
                        self.branches.setdefault((repo, branch), ws["path"])
        self.paths.sort(key=lambda pair: -len(pair[0]))      # the deepest folder wins

    def by_title(self, title):
        if not title or not title.startswith(TITLE_PREFIXES):
            return None
        rest = title[3:]
        hits = [s for s in self.slugs if rest.startswith(s + "-") or rest == s]
        return self.slugs[max(hits, key=len)] if hits else None

    def by_session(self, sid, short, title):
        ws = self.sids.get(sid) or self.sids.get(short) or self.by_title(title)
        return (ws, "title") if ws else None

    def by_path(self, path):
        for tree, ws in self.paths:
            if _under(path, tree):
                return ws
        return None

    def by_branch(self, repo, branch):
        return self.branches.get((repo, branch)) if repo and branch else None


def session_title(name, cwd, short):
    """A session's name, else "<cwd folder> session <short id>"."""
    return name or "%s session %s" % (os.path.basename(cwd.rstrip("/")) or "a", short)


def rule_pattern_for_slug(slug):
    """claude-project-studio-20261023 -> claude-project-studio-*: the same work, any date."""
    return DATE_SUFFIX.sub("-*", slug) if DATE_SUFFIX.search(slug) else slug


MONDAY_ID = re.compile(r"(?<![0-9])[0-9]{9,13}(?![0-9])")    # a monday item id: 13216938828


def monday_ids(*texts):
    """The monday item ids in `texts` (a branch, a title), sorted, each once. An 8-digit date is not one."""
    return sorted({m for text in texts for m in MONDAY_ID.findall(text or "")})


class Inventory(object):
    def __init__(self, entries, now=None):
        self.now = now or time.time()
        self.entries = entries
        self.ok_scopes, self.present, self.errors = set(), {}, []
        for entry in entries.values():
            if not entry.ok:
                self.errors.append(entry)
        self.workspaces = self._workspaces()
        self.joins = Joins(self.workspaces)
        self.agents_ok = self._ok("agents", "all")
        self._repo_cache = {}

    def _ok(self, source, key):
        entry = self.entries.get((source, key))
        return bool(entry and entry.ok and not entry.partial)

    def _data(self, source, key, default):
        entry = self.entries.get((source, key))
        return entry.data if entry is not None and entry.data is not None else default

    def _mark(self, scope, ok, keys):
        if ok:
            self.ok_scopes.add(scope)
        self.present.setdefault(scope, set()).update(keys)

    def _workspaces(self):
        """The discover read, with any newer single-workspace (2 s) read laid over it."""
        base = self.entries.get(("workspaces", "discover"))
        merged = {ws["path"]: ws for ws in (base.data or [] if base else [])}
        for (source, key), entry in self.entries.items():
            if source == "workspace" and entry.data and (base is None or entry.fetched_at >= base.fetched_at):
                merged[key] = entry.data[0]
        self._mark("workspaces", self._ok("workspaces", "discover"), merged)
        scan = (self._data("conductors", "all", {}) or {}).get("files") or {}
        for path, ws in merged.items():
            if not ws.get("conductor_session_id"):
                merged[path] = self._with_conductor(ws, scan)
        return sorted(merged.values(), key=lambda ws: ws["path"])

    def _names(self):
        names = {r["session_id"]: r.get("name", "") for r in self._data("jobs", "all", []) + self._data("agents", "all", [])
                 if r.get("name")}
        meta = (self._data("transcripts", "all", {}) or {}).get("meta") or {}
        return dict({sid: m.get("title", "") for sid, m in meta.items() if m.get("title")}, **names)

    def _with_conductor(self, ws, scan):
        """`ws` with the newest non-ticket session that ran its conductor commands, if any."""
        if not hasattr(self, "_name_of"):
            self._name_of = self._names()
        tickets = set(ws.get("sessions") or [])
        prefixes = tuple(p + slug + "-" for slug in ws.get("slugs") or [] for p in TITLE_PREFIXES)
        best = ("", "")
        for sid, entry in scan.items():
            stamp = (entry[2] if isinstance(entry, list) and len(entry) == 3 else {}).get(ws["path"])
            if not stamp or sid in tickets or (prefixes and self._name_of.get(sid, "").startswith(prefixes)):
                continue
            best = max(best, (stamp, sid))
        if not best[1]:
            return ws
        return dict(ws, conductor_session_id=best[1], conductor_session_ids=[best[1]],
                    sessions=list(ws.get("sessions") or []) + [best[1]])

    def repo(self, path):
        if path not in self._repo_cache:
            self._repo_cache[path] = repo_of_path(path)
        return self._repo_cache[path]

    # ------------------------------------------------------------ per kind

    def found(self):
        return (self._found_workspaces() + self._found_artifacts() + self._found_sessions()
                + self._found_worktrees() + self._found_prs())

    def _found_workspaces(self):
        out = []
        for ws in self.workspaces:
            signals = {"workspace": ws["slug"], "repo": ws.get("repo", ""), "branch": ws.get("branch", ""),
                       "cwd": ws.get("worktree") or ws["path"]}
            out.append(Found(ws["kind"], ws["path"], ws["slug"], dict(ws), "workspaces", signals))
        return out

    def _found_artifacts(self):
        out = []
        for ws in self.workspaces:
            for art in ws.get("artifacts", []):
                title = "%s %s" % (ws["slug"], "plan page" if art.get("plan") else "artifact")
                signals = {"workspace": ws["slug"], "repo": ws.get("repo", ""), "branch": "", "cwd": ws["path"]}
                out.append(Found("artifact", art["key"], title, dict(art), "workspaces", signals, (ws["path"], "cwd")))
        return out

    def _found_sessions(self):
        agents = {r["session_id"]: r for r in self._data("agents", "all", [])}
        jobs = {r["session_id"]: r for r in self._data("jobs", "all", [])}
        trans = self._data("transcripts", "all", {}) or {}
        index, meta = trans.get("index") or {}, self._with_old_conductors(trans, agents, jobs)
        ok = self.agents_ok and self._ok("jobs", "all") and self._ok("transcripts", "all")
        out = []
        for sid in sorted(set(agents) | set(jobs) | set(meta)):
            rec = self._session(sid, agents.get(sid), jobs.get(sid), meta.get(sid), index.get(sid))
            if rec is not None:
                out.append(rec)
        self._mark("sessions", ok, [f.key for f in out] + list(index))
        return out

    def _with_old_conductors(self, trans, agents, jobs):
        """The transcripts read's heads, plus the head of each run's conductor that is on disk
        (in the index) but too old to have one, so an old conductor still gets its item."""
        index, meta = trans.get("index") or {}, dict(trans.get("meta") or {})
        for ws in self.workspaces:
            sid = ws.get("conductor_session_id") or ""
            if sid in index and sid not in meta and sid not in agents and sid not in jobs:
                head = transcript_head(index[sid][0])
                if head is not None:
                    meta[sid] = head
        return meta

    def _session(self, sid, agent, job, head, where):
        kind = session_kind(head)
        if agent or job:
            kind = "session-interactive" if agent and agent.get("agent_kind") not in ("", "background") else "session-bg"
        if kind is None:
            return None                      # headless `claude -p`, or nothing to show
        head = head or {}
        name = (agent or {}).get("name") or (job or {}).get("name") or head.get("title", "")
        cwd = (agent or {}).get("cwd") or (job or {}).get("cwd") or head.get("cwd", "")
        short = (agent or {}).get("short") or (job or {}).get("short") or sid[:8]
        touched = where[1] if where else 0
        if kind == "session-bg":
            if not self.agents_ok:
                status = "unknown"
            elif agent:
                status = agent.get("state") or "listed"
            else:
                status = "removed"           # left `claude agents`: resume only, no attach
        else:
            status = "active" if touched and self.now - touched < ACTIVE_SECONDS else "idle"
        data = {
            "session_id": sid, "short": short, "name": name, "cwd": cwd,
            "git_branch": head.get("git_branch", ""), "status": status,
            "listed": bool(agent), "activity": (agent or {}).get("activity", ""),
            "waiting_for": (agent or {}).get("waiting_for", ""), "detail": (job or {}).get("detail", ""),
            "started_at": (agent or {}).get("started_at") or (job or {}).get("created_at") or head.get("started_at", ""),
            "last_active": iso(touched), "transcript": where[0] if where else "",
            "recently_active": bool(touched and self.now - touched < ACTIVE_SECONDS),
        }
        repo = self.repo(cwd) if cwd else {}
        signals = {"workspace": "", "repo": repo.get("repo", ""), "branch": data["git_branch"], "cwd": cwd}
        link = self.joins.by_session(sid, short, name)
        if link is None and cwd:
            ws = self.joins.by_path(cwd)
            link = (ws, "cwd") if ws else None
        if link:
            signals["workspace"] = os.path.basename(link[0])
        return Found(kind, sid, session_title(name, cwd, short), data, "sessions", signals, link)

    def _found_worktrees(self):
        out = []
        for (source, key), entry in sorted(self.entries.items()):
            if source != "worktrees":
                continue
            scope = "worktrees:" + key
            keys = []
            for tree in entry.data or []:
                ws = self.joins.by_path(tree["path"]) or self.joins.by_branch(key, tree.get("branch", ""))
                data = dict(tree, repo_path=key, repo=os.path.basename(key))
                signals = {"workspace": os.path.basename(ws) if ws else "", "repo": data["repo"],
                           "branch": tree.get("branch", ""), "cwd": tree["path"]}
                title = "%s (%s)" % (os.path.basename(tree["path"]), tree.get("branch") or "detached")
                out.append(Found("worktree", tree["path"], title, data, scope, signals, (ws, "cwd") if ws else None))
                keys.append(tree["path"])
            self._mark(scope, self._ok(source, key), keys)
        return out

    def _found_prs(self):
        out = []
        for (source, key), entry in sorted(self.entries.items()):
            if source != "prs":
                continue
            scope = "prs:" + key
            keys = []
            for pr in entry.data or []:
                ws = self.joins.by_branch(key, pr["branch"])
                repo = key.split("/", 1)[-1]
                signals = {"workspace": os.path.basename(ws) if ws else "", "repo": repo,
                           "branch": pr["branch"], "cwd": "", "monday": monday_ids(pr["branch"], pr["title"])}
                pkey = "%s#%d" % (key, pr["number"])
                title = "%s#%d %s" % (repo, pr["number"], pr["title"])
                out.append(Found("pr", pkey, title[:200], dict(pr, good_at=entry.good_at), scope, signals,
                                 (ws, "cwd") if ws else None))
                keys.append(pkey)
            self._mark(scope, self._ok(source, key), keys)
        return out
