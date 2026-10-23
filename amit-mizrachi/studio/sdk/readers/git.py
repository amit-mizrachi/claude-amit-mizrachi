"""Git readers: the worktrees of a repo, its PRs (`gh pr list`), and which repo a folder is in.

Each reader returns a `Read` with `ok`, the records, and `error`. A failed read is UNKNOWN:
the caller keeps what it knew before and never marks anything gone on it.
"""

import json
import os

from . import commands

PR_LIMIT = 200
PR_FIELDS = "number,title,headRefName,state,isDraft,url,updatedAt,statusCheckRollup"
RED_CHECKS = ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE")


class Read(object):
    """One source read: `ok` False means the records are not to be trusted as complete."""

    def __init__(self, ok, records, error="", partial=False):
        self.ok = ok
        self.records = records
        self.error = error
        self.partial = partial     # ok, but cut short (a limit): absent records are not gone


def parse_worktrees(text):
    """`git worktree list --porcelain` -> [{path, branch, head, main, prunable}] in listed order."""
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):], "branch": "", "head": "", "main": not out, "prunable": False}
            out.append(cur)
        elif cur is None:
            continue
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].replace("refs/heads/", "", 1)
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):]
        elif line.startswith("prunable"):
            cur["prunable"] = True
    return out


def worktrees(repo_path):
    """The linked worktrees of the repo at `repo_path` (the main checkout and prunable ones left out)."""
    ok, out, error = commands.run(["git", "-C", repo_path, "worktree", "list", "--porcelain"])
    if not ok:
        return Read(False, [], error)
    return Read(True, [w for w in parse_worktrees(out) if not w["main"] and not w["prunable"]])


def prs(repo_slug):
    """Amit's PRs in `owner/repo`, open and closed, in ONE `gh pr list` call."""
    ok, out, error = commands.run(["gh", "pr", "list", "--repo", repo_slug, "--state", "all", "--author", "@me",
                                   "--limit", str(PR_LIMIT), "--json", PR_FIELDS])
    if not ok:
        return Read(False, [], error)
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        return Read(False, [], "gh pr list for %s printed something that is not JSON" % repo_slug)
    if not isinstance(rows, list):
        return Read(False, [], "gh pr list for %s did not print a list" % repo_slug)
    records = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("number"), int):
            records.append({
                "repo_slug": repo_slug, "number": row["number"], "title": str(row.get("title") or ""),
                "branch": str(row.get("headRefName") or ""), "state": str(row.get("state") or "").lower(),
                "draft": bool(row.get("isDraft")), "url": str(row.get("url") or ""),
                "updated_at": str(row.get("updatedAt") or ""), "checks": checks_of(row.get("statusCheckRollup")),
            })
    return Read(True, records, partial=len(rows) >= PR_LIMIT)


def checks_of(rollup):
    """{"total", "red", "pending"} over a PR's statusCheckRollup (check runs and commit statuses)."""
    rows = [r for r in rollup or [] if isinstance(r, dict)]
    red = sum(1 for r in rows if str(r.get("conclusion") or r.get("state") or "").upper() in RED_CHECKS)
    pending = sum(1 for r in rows if str(r.get("status") or "").upper() not in ("", "COMPLETED")
                  or str(r.get("state") or "").upper() in ("PENDING", "EXPECTED"))
    return {"total": len(rows), "red": red, "pending": pending}


def repo_of_path(path):
    """{"repo": <main checkout's folder name>, "repo_path": <main checkout>} for a folder inside a
    git checkout or linked worktree, else {}. Only stats and one small file read; no git call."""
    cur = os.path.abspath(path or "")
    while cur and cur != os.path.dirname(cur):
        dotgit = os.path.join(cur, ".git")
        if os.path.isdir(dotgit):
            return {"repo": os.path.basename(cur), "repo_path": cur}
        if os.path.isfile(dotgit):
            try:
                with open(dotgit) as fh:
                    line = fh.readline().strip()
            except OSError:
                return {}
            gitdir = line[len("gitdir:"):].strip() if line.startswith("gitdir:") else ""
            # <main>/.git/worktrees/<name> -> <main>
            marker = os.sep + ".git" + os.sep + "worktrees" + os.sep
            if marker in gitdir:
                main = gitdir.split(marker, 1)[0]
                return {"repo": os.path.basename(main), "repo_path": main}
            return {}
        cur = os.path.dirname(cur)
    return {}
