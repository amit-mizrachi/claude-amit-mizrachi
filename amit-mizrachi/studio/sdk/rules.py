"""Attach rules learned from moves (D5 A): "Always file items like this here".

A rule is (project, signal, pattern). Four signals, strongest first:
- `workspace`   - the run's slug, date suffix as `*`: `claude-project-studio-*`
- `monday`      - a monday item id in a PR's branch or title, in any repo: `13216938828`
- `repo-branch` - repo folder name + branch prefix: `shapes-platform eval/*`
- `cwd`         - a folder; matches it and everything under it
`for_signals` picks the strongest one an item has, so a rule is never weaker than it could be. It
never learns `monday`: a move says where one item goes, not which of its ids is the project's, so a
monday rule is written by hand (`check`).
`match` returns the first rule an item's signals satisfy (strongest signal first, then newest),
skipping rules whose project is archived: an archived project gets nothing new.
A rule written by hand (`check`, then `items.add_rule`) is stored in the same shape, so it ranks
and matches exactly like a learned one.
"""

import fnmatch
import os
import re
import uuid

from .errors import InvalidInput, Refused
from .inventory import MONDAY_ID, monday_ids, rule_pattern_for_slug

SIGNALS = ("workspace", "monday", "repo-branch", "cwd")
RULE_ID = re.compile(r"^r_[0-9a-f]{12}$")
GLOB = re.compile(r"[*?\[\]]")
MAX_PATTERN = 300


def new_rule_id():
    return "r_" + uuid.uuid4().hex[:12]


def _branch_pattern(branch):
    branch = branch.split("--", 1)[0]                 # a per-ticket branch files like its sprint
    return branch.rsplit("/", 1)[0] + "/*" if "/" in branch else branch


def for_signals(signals):
    """(signal, pattern) from an item's strongest signal, or None when it has none."""
    signals = signals or {}
    if signals.get("workspace"):
        return "workspace", rule_pattern_for_slug(signals["workspace"])
    if signals.get("repo") and signals.get("branch"):
        return "repo-branch", "%s %s" % (signals["repo"], _branch_pattern(signals["branch"]))
    if signals.get("cwd") and not _too_wide(signals["cwd"]):
        return "cwd", signals["cwd"].rstrip("/") or "/"
    return None


def _too_wide(cwd):
    """"/", the home folder and any folder above it hold every session: a cwd rule there would catch them all."""
    folder = cwd.rstrip("/") or "/"
    home = os.path.expanduser("~").rstrip("/")
    return folder in ("/", home) or home.startswith(folder + "/")


def check(signal, pattern):
    """A rule written by hand as the stored (signal, pattern), or InvalidInput / Refused saying why.

    - workspace: a glob on the run's slug (`sis-*`); it needs some fixed text, so `*` is refused.
    - monday: one monday item id (`13216938828`); it files a PR whose branch or title holds it, in any repo.
    - repo-branch: "<repo>" or "<repo> <branch>". The repo is matched exactly; a branch with no
      `*` or `?` is a prefix (`eval/` -> `eval/*`); no branch means every branch of the repo.
    - cwd: an absolute folder (`~` allowed); it files that folder and everything under it, so it
      takes no glob. `/` and the home folder hold every session and are refused.
    """
    if signal not in SIGNALS:
        raise InvalidInput("signal must be one of %s." % ", ".join(SIGNALS))
    if not isinstance(pattern, str) or not pattern.strip():
        raise InvalidInput("The pattern is empty: say what the rule matches.")
    pattern = pattern.strip()
    if len(pattern) > MAX_PATTERN or any(ord(c) < 32 or ord(c) == 127 for c in pattern):
        raise InvalidInput("A pattern is 1-%d characters with no control characters." % MAX_PATTERN)
    if signal == "workspace":
        return signal, _workspace_glob(pattern)
    if signal == "monday":
        return signal, _monday(pattern)
    if signal == "repo-branch":
        return signal, _repo_branch(pattern)
    return signal, _folder(pattern)


def _workspace_glob(pattern):
    if " " in pattern:
        raise InvalidInput("A workspace pattern has no spaces: it matches a run's slug, like sis-*.")
    if not re.sub(r"[*?]", "", pattern):
        raise Refused("%s matches every workspace. Give it some fixed text, like sis-*." % pattern)
    return pattern


def _monday(pattern):
    if not MONDAY_ID.fullmatch(pattern):
        raise InvalidInput("A monday rule is one monday item id, 9-13 digits like 13216938828: %s is not one."
                           % pattern)
    return pattern


def _repo_branch(pattern):
    words = pattern.split()
    if len(words) > 2:
        raise InvalidInput("A repo rule is a repo and at most one branch prefix, like shapes-platform eval/.")
    repo, branch = words[0], words[1] if len(words) == 2 else "*"
    if GLOB.search(repo):
        raise InvalidInput("The repo %s is matched exactly, so it takes no * or ?." % repo)
    if not GLOB.search(branch):
        branch += "*"
    return "%s %s" % (repo, "*" if not re.sub(r"[*?]", "", branch) else branch)


def _folder(pattern):
    folder = os.path.expanduser(pattern)
    if not folder.startswith("/"):
        raise InvalidInput("A folder rule takes an absolute folder, like ~/work/shapes: %s is not one." % pattern)
    if GLOB.search(folder):
        raise InvalidInput("A folder rule files the folder and everything under it, so it takes no * or ?.")
    folder = os.path.normpath(folder).rstrip("/") or "/"
    if _too_wide(folder):
        raise Refused("%s holds every session, so a rule there would file them all. Pick a folder under it."
                      % pattern)
    return folder


def parts(signal, pattern):
    """A rule as (word, value) pairs: [["repo", "shapes-platform"], ["branch", "eval/*"]]."""
    if signal == "repo-branch":
        repo, _, branch = pattern.partition(" ")
        return [["repo", repo], ["branch", branch]]
    if signal == "cwd":
        home = os.path.expanduser("~")
        return [["folder", "~" + pattern[len(home):] if pattern.startswith(home + "/") else pattern]]
    if signal == "monday":
        return [["monday", pattern]]
    return [["workspace", pattern]]


def describe(signal, pattern):
    """The words the studio shows for a rule: "repo shapes-platform + branch eval/*"."""
    return " + ".join("%s %s" % (word, value) for word, value in parts(signal, pattern))


def matches(signal, pattern, signals):
    signals = signals or {}
    if signal == "workspace":
        return bool(signals.get("workspace")) and fnmatch.fnmatchcase(signals["workspace"], pattern)
    if signal == "monday":
        return pattern in monday_ids(signals.get("branch")) or pattern in (signals.get("monday") or [])
    if signal == "repo-branch":
        repo, _, branch = pattern.partition(" ")
        return (signals.get("repo") == repo and bool(signals.get("branch"))
                and fnmatch.fnmatchcase(signals["branch"].split("--", 1)[0], branch))
    if signal == "cwd":
        cwd = signals.get("cwd") or ""
        return bool(cwd) and not _too_wide(pattern) and (cwd == pattern or cwd.startswith(pattern.rstrip("/") + "/"))
    return False


def load(conn):
    """Every rule, strongest signal first, newest first within a signal."""
    return rank([dict(r) for r in conn.execute("SELECT rowid AS seq, id, project_id, signal, pattern, created_at "
                                               "FROM rules")])


def rank(rows):
    """Rules in match order: strongest signal first, newest first within a signal. Two rules saved in
    the same second keep the order they were saved in (`seq`); a rule not saved yet is the newest."""
    order = {s: i for i, s in enumerate(SIGNALS)}
    rows.sort(key=lambda r: (r["created_at"], r.get("seq", float("inf"))), reverse=True)
    rows.sort(key=lambda r: order.get(r["signal"], len(SIGNALS)))
    return rows


def match(rules, signals, tree):
    """The first rule (from `load`) that files an item with these signals, or None."""
    for rule in rules:
        if rule["project_id"] in tree.rows and not tree.hidden(rule["project_id"]) \
                and matches(rule["signal"], rule["pattern"], signals):
            return rule
    return None
