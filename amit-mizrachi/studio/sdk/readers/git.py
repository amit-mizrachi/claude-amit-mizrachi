"""Git readers: the worktrees of a repo, its PRs (two `gh pr list` calls), and which repo a folder is in.

Each reader returns a `Read` with `ok`, the records, and `error`. A failed read is UNKNOWN:
the caller keeps what it knew before and never marks anything gone on it.
"""

import json
import os
import re

from . import commands

# One `gh pr list` with statusCheckRollup over 200 PRs hit GitHub's GraphQL 504 (~11 s) on
# dreamteamapp/shapes-platform. Split, measured there on 2026-10-24: the light list of 100 took
# ~1.7 s, the checks of 30 open PRs ~5.4 s (50 took ~6.8 s).
PR_LIMIT = 100
CHECKS_LIMIT = 30
PR_FIELDS = "number,title,headRefName,state,isDraft,url,updatedAt"
CHECK_FIELDS = "number,statusCheckRollup"
GITHUB_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RETRY_ON = re.compile(r"HTTP 5[0-9][0-9]|timed out")
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


def is_github_slug(repo_slug):
    """True for an `owner/repo` that `gh` can read; False for "local only, no remote" and the like."""
    return bool(GITHUB_SLUG.match(repo_slug or ""))


def gh_pr_list(repo_slug, args):
    """`gh pr list --repo <slug> --author @me <args>` -> (rows, error). A 5xx or a timeout is retried
    once; rows is None when the call failed or did not print a JSON list."""
    argv = ["gh", "pr", "list", "--repo", repo_slug, "--author", "@me"] + args
    ok, out, error = commands.run(argv)
    if not ok and RETRY_ON.search(error):
        ok, out, error = commands.run(argv)
    if not ok:
        return None, error
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        return None, "gh pr list for %s printed something that is not JSON" % repo_slug
    if not isinstance(rows, list):
        return None, "gh pr list for %s did not print a list" % repo_slug
    return [r for r in rows if isinstance(r, dict)], ""


def prs(repo_slug):
    """Amit's PRs in `owner/repo`, open and closed: a light list of the newest PR_LIMIT, then the
    check counts of its open PRs in a second, smaller call. A slug that is not a GitHub `owner/repo`
    (a checkout with no remote) is not read at all: an ok, empty read, so it raises no banner."""
    if not is_github_slug(repo_slug):
        return Read(True, [])
    rows, error = gh_pr_list(repo_slug, ["--state", "all", "--limit", str(PR_LIMIT), "--json", PR_FIELDS])
    if rows is None:
        return Read(False, [], error)
    records = []
    for row in rows:
        if isinstance(row.get("number"), int):
            records.append({
                "repo_slug": repo_slug, "number": row["number"], "title": str(row.get("title") or ""),
                "branch": str(row.get("headRefName") or ""), "state": str(row.get("state") or "").lower(),
                "draft": bool(row.get("isDraft")), "url": str(row.get("url") or ""),
                "updated_at": str(row.get("updatedAt") or ""), "checks": checks_of(None),
            })
    opened = [r for r in records if r["state"] == "open"]
    if opened:
        limit = min(len(opened), CHECKS_LIMIT)
        rows_checks, error = gh_pr_list(repo_slug, ["--state", "open", "--limit", str(limit), "--json", CHECK_FIELDS])
        if rows_checks is None:
            return Read(False, [], error)
        rollups = {r.get("number"): r.get("statusCheckRollup") for r in rows_checks}
        for rec in opened:
            rec["checks"] = checks_of(rollups.get(rec["number"]))
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
