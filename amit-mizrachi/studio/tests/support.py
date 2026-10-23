"""Shared test helpers: a fresh, private PROJECT_STUDIO_HOME per test, with every reader pointed
at empty fixture folders and `claude` / `gh` stubbed on PATH, so no test reads this Mac."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from . import STUDIO

STUBS = os.path.join(STUDIO, "tests", "stubs")
ENV_KEYS = ("PROJECT_STUDIO_HOME", "PROJECT_STUDIO_ROOTS", "PROJECT_STUDIO_CLAUDE_HOME", "STUDIO_STUB", "PATH",
            "NIGHT_WATCH_ROOTS")


class TempHome(unittest.TestCase):
    """Each test gets its own empty data dir, workspace root, Claude home and stub state."""

    def setUp(self):
        super().setUp()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="studio-test-"))   # /var -> /private/var, as git prints it
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {k: os.environ.get(k) for k in ENV_KEYS}
        self.addCleanup(self._restore, saved)
        self.home = self.mkdir("home")
        self.roots = self.mkdir("roots")
        self.claude_home = self.mkdir("claude")
        self.stub = self.mkdir("stub")
        os.environ.update(PROJECT_STUDIO_HOME=self.home, PROJECT_STUDIO_ROOTS=self.roots,
                          PROJECT_STUDIO_CLAUDE_HOME=self.claude_home, STUDIO_STUB=self.stub,
                          PATH=STUBS + os.pathsep + (saved["PATH"] or "/usr/bin:/bin"))
        os.environ.pop("NIGHT_WATCH_ROOTS", None)

    @staticmethod
    def _restore(saved):
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def mkdir(self, *parts):
        path = os.path.join(self.tmp, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def write(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path


class Sources(TempHome):
    """Builders for reader fixtures: agents rows, jobs, transcripts, workspaces, git repos, PRs."""

    def agents(self, rows):
        self.write(os.path.join(self.stub, "agents.json"), json.dumps(rows))

    def agents_fail(self):
        self.write(os.path.join(self.stub, "agents-fail"), "1")

    def agents_ok(self):
        path = os.path.join(self.stub, "agents-fail")
        if os.path.exists(path):
            os.unlink(path)

    def prs(self, slug, rows):
        self.write(os.path.join(self.stub, "prs-%s.json" % slug.replace("/", "_")), json.dumps(rows))

    def job(self, short, sid, name, cwd, state="done"):
        self.write(os.path.join(self.claude_home, "jobs", short, "state.json"),
                   json.dumps({"sessionId": sid, "daemonShort": short, "name": name, "cwd": cwd, "state": state}))

    def transcript(self, sid, cwd, kind="bg", entrypoint="cli", title="", branch="main"):
        rows = []
        if title:
            rows.append({"type": "custom-title", "customTitle": title, "sessionId": sid})
        rows.append({"type": "user", "cwd": cwd, "gitBranch": branch, "sessionKind": kind, "entrypoint": entrypoint,
                     "sessionId": sid, "timestamp": "2026-10-23T10:00:00.000Z"})
        folder = "-" + cwd.strip("/").replace("/", "-")
        return self.write(os.path.join(self.claude_home, "projects", folder, sid + ".jsonl"),
                          "".join(json.dumps(r) + "\n" for r in rows))

    def workspace(self, slug, facts=None, tags=(("T01", "DONE"), ("T02", "")), files=None):
        """A night-sprint workspace under the root: a chain of tags, each with a status line,
        "" for running (a claim dir), or None for pending."""
        ws = self.mkdir("roots", slug)
        env = dict({"SLUG": slug, "MODE": "code"}, **(facts or {}))
        self.write(os.path.join(ws, "facts.env"), "".join("%s=%s\n" % kv for kv in env.items()))
        for i, (tag, status) in enumerate(tags):
            nxt = tags[i + 1][0] if i + 1 < len(tags) else ""
            self.write(os.path.join(ws, "state", tag + ".next"), nxt + "\n")
            if status:
                self.write(os.path.join(ws, "state", tag + ".status"), status + "\n")
            elif status is not None:
                self.mkdir("roots", slug, "state", "claim-" + tag)
        for rel, text in (files or {}).items():
            self.write(os.path.join(ws, rel), text)
        return ws

    def git_repo(self, name, worktrees=()):
        """A real repo with one commit and linked worktrees [(folder name, branch)]."""
        repo = self.mkdir("repos", name)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@t")
        for argv in (["git", "init", "-q", "-b", "main"], ["git", "commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(argv, cwd=repo, env=env, check=True)
        paths = []
        for folder, branch in worktrees:
            path = os.path.join(self.tmp, "repos", folder)
            subprocess.run(["git", "worktree", "add", "-q", "-b", branch, path], cwd=repo, env=env, check=True)
            paths.append(os.path.realpath(path))
        return os.path.realpath(repo), paths


def validate(instance, schema, where="$"):
    """A small JSON Schema check (type, required, properties, items, enum, pattern-free) for the
    tools' outputSchemas. Returns a list of problems; empty means valid."""
    problems = []
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        py = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
        ok = any((n == "integer" and isinstance(instance, int) and not isinstance(instance, bool))
                 or (n == "number" and isinstance(instance, (int, float)) and not isinstance(instance, bool))
                 or (n in py and isinstance(instance, py[n])) for n in names)
        if not ok:
            return ["%s: %r is not %s" % (where, instance, types)]
    if "enum" in schema and instance not in schema["enum"]:
        problems.append("%s: %r not in %s" % (where, instance, schema["enum"]))
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                problems.append("%s: missing %s" % (where, key))
        for key, sub in schema.get("properties", {}).items():
            if key in instance:
                problems += validate(instance[key], sub, where + "." + key)
    if isinstance(instance, list) and "items" in schema:
        for i, value in enumerate(instance):
            problems += validate(value, schema["items"], "%s[%d]" % (where, i))
    return problems
