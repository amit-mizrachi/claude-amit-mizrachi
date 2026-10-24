"""The SessionStart hook: a new session files itself by the SDK's rules, silently, and a broken
store, a bad payload or a missing python3 never fails the session start."""

import json
import os
import subprocess
import unittest
from unittest import mock

from sdk import api, reconcile
from sdk.errors import InvalidInput

from . import PLUGIN
from .support import Sources
from .test_readers import SID_A, SID_B, SID_C, SID_D

SLUG = "studio-20261023"
HOOK = os.path.join(PLUGIN, "hooks", "attach-session.sh")


class Hook(Sources):
    def setUp(self):
        super().setUp()
        self.repo, (self.wt,) = self.git_repo("r", [("r-studio", "feat/s")])
        self.ws = self.workspace(SLUG, facts={"REPO_PATH": self.repo, "BRANCH": "feat/s", "WORKTREE": self.wt})
        api.refresh(force=True)
        self.run = self.items()[self.ws]
        self.sprint = api.create_project("Project Studio")
        api.move_item(self.run.id, self.sprint.id)

    def items(self):
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}

    def fire(self, payload, job_dir=None, entrypoint="cli", path=None):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_JOB_DIR", "CLAUDE_CODE_ENTRYPOINT")}
        env.update(CLAUDE_PLUGIN_ROOT=PLUGIN, CLAUDE_CODE_ENTRYPOINT=entrypoint)
        if job_dir:
            env["CLAUDE_JOB_DIR"] = job_dir
        if path is not None:
            env["PATH"] = path
        text = payload if isinstance(payload, str) else json.dumps(payload)
        done = subprocess.run(["/bin/bash", HOOK], input=text, capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
        return done

    def bg_job(self, sid, name, cwd="/somewhere/else"):
        self.job(sid[:8], sid, name, cwd, state="working")
        return os.path.join(self.claude_home, "jobs", sid[:8])

    def start(self, sid, cwd):
        return {"session_id": sid, "cwd": cwd, "hook_event_name": "SessionStart", "source": "startup"}

    def test_a_night_sprint_session_files_under_its_sprint_project(self):
        self.fire(self.start(SID_A, "/somewhere/else"), job_dir=self.bg_job(SID_A, "ns-%s-T02" % SLUG))
        session = self.items()[SID_A]
        self.assertEqual((session.kind, session.project_id, session.placed_by, session.workspace_item_id),
                         ("session-bg", self.sprint.id, "title", self.run.id))
        self.assertEqual(session.title, "ns-%s-T02" % SLUG)

    def test_the_next_scan_keeps_it_there_without_a_second_row(self):
        self.fire(self.start(SID_A, "/somewhere/else"), job_dir=self.bg_job(SID_A, "ns-%s-T02" % SLUG))
        api.refresh(force=True)
        rows = [i for i in self.items().values() if i.key == SID_A]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].project_id, rows[0].placed_by, rows[0].gone), (self.sprint.id, "title", False))

    def test_an_interactive_session_in_the_run_worktree_files_by_cwd(self):
        self.fire(self.start(SID_B, os.path.join(self.wt, "pkg")))
        session = self.items()[SID_B]
        self.assertEqual((session.kind, session.project_id, session.placed_by),
                         ("session-interactive", self.sprint.id, "cwd"))

    def test_an_unknown_session_lands_in_the_inbox(self):
        self.fire(self.start(SID_C, "/somewhere/else"))
        self.assertEqual(self.items()[SID_C].project_id, "inbox")

    def test_a_headless_run_is_never_an_item(self):
        self.fire(self.start(SID_D, self.wt), entrypoint="sdk-cli")
        self.assertNotIn(SID_D, self.items())

    def test_a_resume_leaves_a_known_session_where_it_is(self):
        self.fire(self.start(SID_C, "/somewhere/else"))
        api.move_item(self.items()[SID_C].id, self.sprint.id)
        self.fire(dict(self.start(SID_C, "/somewhere/else"), source="resume"))
        self.assertEqual((self.items()[SID_C].project_id, self.items()[SID_C].placed_by), (self.sprint.id, "manual"))

    def test_a_broken_store_still_exits_0_silently(self):
        os.unlink(os.path.join(self.home, "studio.db"))
        self.write(os.path.join(self.home, "studio.db"), "this is not a sqlite file " * 100)
        self.fire(self.start(SID_A, "/somewhere/else"), job_dir=self.bg_job(SID_A, "ns-%s-T02" % SLUG))

    def test_a_bad_payload_still_exits_0_silently(self):
        for payload in ("not json", "[]", "", {"session_id": "nope", "cwd": "relative"}):
            self.fire(payload)
        self.assertNotIn("nope", self.items())

    def test_no_python3_still_exits_0_silently(self):
        self.fire(self.start(SID_C, "/somewhere/else"), path=self.mkdir("empty-path"))
        self.assertNotIn(SID_C, self.items())

    def test_a_session_no_read_ever_finds_goes_gone_only_after_the_grace(self):
        self.fire(self.start(SID_C, "/somewhere/else"))
        api.refresh(force=True)
        self.assertFalse(self.items()[SID_C].gone)
        with mock.patch.object(reconcile, "ATTACH_GRACE_SECONDS", -60):
            api.refresh(force=True)
        self.assertTrue(self.items()[SID_C].gone)


class AttachApi(Sources):
    def test_input_is_checked(self):
        for args in (("nope", "/x"), (SID_A, "relative"), (SID_A, None)):
            with self.assertRaises(InvalidInput):
                api.attach_session(*args)

    def test_headless_skips_without_opening_the_store(self):
        found = api.attach_session(SID_A, "/x", entrypoint="sdk-ts")
        self.assertEqual((found.item, found.skipped), (None, "headless"))
        self.assertFalse(os.path.exists(os.path.join(self.home, "studio.db")))

    def test_attaching_twice_creates_once(self):
        self.assertTrue(api.attach_session(SID_A, "/x/").created)
        again = api.attach_session(SID_A, "/x")
        self.assertEqual((again.created, again.item.data["cwd"]), (False, "/x"))


class HooksJson(unittest.TestCase):
    def test_existing_hooks_are_unchanged_and_the_attach_hook_is_time_boxed(self):
        with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as fh:
            hooks = json.load(fh)["hooks"]
        start = hooks["SessionStart"][0]["hooks"]
        self.assertEqual(start[:2], [
            {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/caffeinate.sh"},
            {"type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/link-night-watch.sh"}])
        self.assertEqual(start[2], {"type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/attach-session.sh",
                                    "timeout": 5})
        self.assertEqual(hooks["UserPromptSubmit"], [{"hooks": [
            {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/caffeinate.sh"}]}])
