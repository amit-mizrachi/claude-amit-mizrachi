"""Attach rules learned from moves (D5 A): "Always file items like this here".

A rule is (project, signal, pattern). Three signals, strongest first:
- `workspace`   - the run's slug, date suffix as `*`: `claude-project-studio-*`
- `repo-branch` - repo folder name + branch prefix: `shapes-platform eval/*`
- `cwd`         - a folder; matches it and everything under it
`for_signals` picks the strongest one an item has, so a rule is never weaker than it could be.
`match` returns the first rule an item's signals satisfy (strongest signal first, then newest),
skipping rules whose project is archived: an archived project gets nothing new.
"""

import fnmatch
import os
import re
import uuid

from .inventory import rule_pattern_for_slug

SIGNALS = ("workspace", "repo-branch", "cwd")
RULE_ID = re.compile(r"^r_[0-9a-f]{12}$")


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
    if signals.get("cwd"):
        return "cwd", signals["cwd"].rstrip("/") or "/"
    return None


def parts(signal, pattern):
    """A rule as (word, value) pairs: [["repo", "shapes-platform"], ["branch", "eval/*"]]."""
    if signal == "repo-branch":
        repo, _, branch = pattern.partition(" ")
        return [["repo", repo], ["branch", branch]]
    if signal == "cwd":
        home = os.path.expanduser("~")
        return [["folder", "~" + pattern[len(home):] if pattern.startswith(home + "/") else pattern]]
    return [["workspace", pattern]]


def describe(signal, pattern):
    """The words the studio shows for a rule: "repo shapes-platform + branch eval/*"."""
    return " + ".join("%s %s" % (word, value) for word, value in parts(signal, pattern))


def matches(signal, pattern, signals):
    signals = signals or {}
    if signal == "workspace":
        return bool(signals.get("workspace")) and fnmatch.fnmatchcase(signals["workspace"], pattern)
    if signal == "repo-branch":
        repo, _, branch = pattern.partition(" ")
        return (signals.get("repo") == repo and bool(signals.get("branch"))
                and fnmatch.fnmatchcase(signals["branch"].split("--", 1)[0], branch))
    if signal == "cwd":
        cwd = signals.get("cwd") or ""
        return bool(cwd) and (cwd == pattern or cwd.startswith(pattern.rstrip("/") + "/"))
    return False


def load(conn):
    """Every rule, strongest signal first, newest first within a signal."""
    rows = [dict(r) for r in conn.execute("SELECT id, project_id, signal, pattern, created_at FROM rules")]
    rank = {s: i for i, s in enumerate(SIGNALS)}
    rows.sort(key=lambda r: r["id"])
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    rows.sort(key=lambda r: rank.get(r["signal"], len(SIGNALS)))
    return rows


def match(rules, signals, tree):
    """The first rule (from `load`) that files an item with these signals, or None."""
    for rule in rules:
        if rule["project_id"] in tree.rows and not tree.hidden(rule["project_id"]) \
                and matches(rule["signal"], rule["pattern"], signals):
            return rule
    return None
