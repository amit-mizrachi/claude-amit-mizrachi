"""Ticket 07: throw away a night run - the one studio action that removes things, only when confirmed.
Through `sdk.api`, the CLI as a subprocess and the MCP server over stdin/stdout. Fixture homes,
fixture folders and fixture git repos only: nothing here reads or writes ~/.project-studio, and the
Trash step is stubbed (a mock in-process, the `osascript` stub for a subprocess), so no test ever
calls Finder."""

import json
import os
import subprocess
import sys
from unittest import mock

from sdk import api, throw
from sdk.errors import Refused

from . import PLUGIN
from . import test_mcp_server as mcp_tests
from .support import Sources, validate
from .test_readers import SID_A, SID_B, agent

SLUG = "throw-20261024"
BIN = os.path.join(PLUGIN, "bin", "project-studio")


class Throwing(Sources):
    """A stopped night run in Alpha with two worktrees (its branch's and a ticket's), a finished
    session attached by title and a PR; a loose session that is not the run's."""

    def setUp(self):
        super().setUp()
        self.repo, (self.wt, self.ticket_wt) = self.git_repo("r", [("r-thr", "feat/t"), ("r-thr-T02", "feat/t--T02")])
        self.ws = self.workspace(SLUG, facts={"REPO_PATH": self.repo, "REPO_SLUG": "me/r", "BRANCH": "feat/t",
                                              "WORKTREE": self.wt, "TOTAL": "2"},
                                 tags=(("T01", "DONE"), ("T02", "BLOCKED: gave up")), runner=False,
                                 files={"state/T02.cwd": self.ticket_wt + "\n", "state/T02.session": SID_A + "\n"})
        self.prs("me/r", [{"number": 9, "title": "throw", "headRefName": "feat/t", "state": "OPEN", "isDraft": False,
                           "url": "https://github.com/me/r/pull/9", "updatedAt": "2026-10-24T00:00:00Z"}])
        self.agents([agent(SID_A, "ns-%s-T02" % SLUG, self.ticket_wt, state="done"),
                     agent(SID_B, "loose work", "/w/loose")])
        found = self.items()
        self.alpha = api.create_project("Alpha")
        self.run, self.loose = found[self.ws], found[SID_B]
        api.move_item(self.run.id, self.alpha.id)
        self.attached = {i.id for i in found.values() if i.workspace_item_id == self.run.id}
        self.trash_dir = self.mkdir("Trash")
        self.trashed = []

    def items(self):
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}

    def stored(self):
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000,
                                                 include_dismissed=True).items}

    def fake_trash(self, path):
        """What Finder does, in a temp Trash: the folder leaves its place."""
        self.trashed.append(path)
        os.rename(path, os.path.join(self.trash_dir, os.path.basename(path)))
        return True, ""

    def throw(self, confirmed):
        with mock.patch.object(throw, "trash", self.fake_trash):
            return api.throw_away(self.run.id, confirmed=confirmed)

    def branches(self):
        out = subprocess.run(["git", "-C", self.repo, "branch", "--list", "--format=%(refname:short)"],
                             stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout
        return set(out.split())

    def assert_untouched(self):
        self.assertTrue(os.path.isdir(self.ws))
        self.assertTrue(os.path.isdir(self.wt) and os.path.isdir(self.ticket_wt))
        self.assertIn(self.ws, self.stored())
        self.assertEqual(self.trashed, [])


class ThrowThroughTheSdk(Throwing):
    def test_the_plan_lists_the_folder_each_worktree_and_the_item_count_and_changes_nothing(self):
        plan = self.throw(False)
        self.assertEqual((plan.thrown, plan.needs_confirm), (False, True))
        self.assertEqual(plan.folder, self.ws)
        self.assertEqual(sorted(t.path for t in plan.worktrees), sorted([self.wt, self.ticket_wt]))
        self.assertEqual({t.repo_path for t in plan.worktrees}, {self.repo})
        self.assertEqual(plan.items, len(self.attached))
        self.assertGreaterEqual(plan.items, 4)                  # session, PR, two worktrees
        for part in (self.ws, self.wt, self.ticket_wt, "%d attached items" % plan.items, "Trash"):
            self.assertIn(part, plan.message)
        self.assert_untouched()

    def test_confirmed_it_removes_the_worktrees_trashes_the_folder_and_purges_only_the_run_and_its_items(self):
        before = self.stored()
        done = self.throw(True)
        self.assertEqual((done.thrown, done.needs_confirm), (True, False))
        self.assertEqual(self.trashed, [self.ws])
        self.assertTrue(os.path.isdir(os.path.join(self.trash_dir, SLUG)))       # in the Trash, not deleted
        self.assertFalse(os.path.exists(self.ws))
        self.assertFalse(os.path.exists(self.wt) or os.path.exists(self.ticket_wt))
        self.assertTrue({"feat/t", "feat/t--T02"} <= self.branches())             # the commits survive
        after = self.stored()
        gone_ids = {i.id for i in before.values()} - {i.id for i in after.values()}
        self.assertEqual(gone_ids, self.attached | {self.run.id})
        self.assertIn(SID_B, after)
        self.assertEqual(api.get_project(self.alpha.id).name, "Alpha")
        self.assertIn("Threw away", done.message)
        self.assertNotIn(self.ws, self.items())                                   # a refresh does not bring it back

    def test_a_worktree_with_changes_stops_the_throw_before_the_folder_moves_and_names_it(self):
        self.write(os.path.join(self.ticket_wt, "notes.txt"), "not committed\n")
        with self.assertRaises(Refused) as caught:
            self.throw(True)
        message = str(caught.exception)
        self.assertIn(self.ticket_wt, message)
        self.assertIn("Done: removed worktree %s" % self.wt, message)               # what was done
        self.assertIn("Not done: worktree %s" % self.ticket_wt, message)            # and what was not
        self.assertIn(self.ws, message.split("Not done:")[1])
        self.assertEqual(self.trashed, [])
        self.assertTrue(os.path.isdir(self.ws) and os.path.isdir(self.ticket_wt))
        self.assertIn(self.ws, self.stored())

    def test_a_run_whose_runner_is_alive_is_refused(self):
        live = self.workspace("live-20261024", tags=(("T01", ""),))
        run = self.items()[live]
        with mock.patch.object(throw, "trash", self.fake_trash):
            for confirmed in (False, True):
                with self.assertRaises(Refused) as caught:
                    api.throw_away(run.id, confirmed=confirmed)
                self.assertIn("runner is alive", str(caught.exception))
        self.assertTrue(os.path.isdir(live))
        self.assertEqual(self.trashed, [])

    def test_a_run_with_a_live_session_is_refused_and_so_is_one_claude_agents_cannot_answer_for(self):
        self.agents([agent(SID_A, "ns-%s-T02" % SLUG, self.ticket_wt, state="working")])
        with self.assertRaises(Refused) as caught:
            self.throw(True)
        self.assertIn("live session", str(caught.exception))
        self.agents_fail()
        with self.assertRaises(Refused) as caught:
            self.throw(True)
        self.assertIn("Can't tell", str(caught.exception))
        self.assert_untouched()

    def test_only_a_night_run_can_be_thrown_away(self):
        with self.assertRaises(Refused):
            api.throw_away(self.loose.id, confirmed=True)

    def test_only_a_plain_folder_inside_a_run_root_passes(self):
        outside = self.mkdir("elsewhere", "ws")
        self.mkdir("elsewhere", "ws", "state")
        link = os.path.join(self.roots, "link-ws")
        os.symlink(outside, link)
        for bad in (outside, self.roots, os.path.join(self.roots, "..", "elsewhere", "ws"), link, "relative/ws"):
            with self.assertRaises(Refused, msg=bad):
                throw.check_folder(bad)
        self.mkdir("roots", "no-state")
        with self.assertRaises(Refused):
            throw.check_folder(os.path.join(self.roots, "no-state"))
        self.assertEqual(throw.check_folder(self.ws), self.ws)
        self.assertEqual(throw.check_folder(os.path.join(self.roots, "missing")), "")


class ThrowFromTheCli(Throwing):
    def cli(self, *argv):
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def test_without_yes_it_prints_the_plan_and_exits_confirm_needed(self):
        code, out, err = self.cli("throw", self.run.id[:8])
        self.assertEqual(code, 2)
        self.assertIn("confirm_needed", err)
        self.assertIn(self.ws, err)
        self.assertIn("--yes", err)
        code, out, _ = self.cli("throw", self.run.id, "--json")
        self.assertEqual((code, json.loads(out)["error"]["code"]), (2, "confirm_needed"))
        self.assert_untouched()

    def test_a_failed_trash_step_stops_the_rest_and_says_what_was_done(self):
        self.write(os.path.join(self.stub, "osascript-fail"), "1")
        code, out, err = self.cli("throw", self.run.id, "--yes")
        self.assertEqual(code, 1, err)
        self.assertIn("could not move %s to the Trash" % self.ws, err)
        self.assertIn("removed worktree", err)
        self.assertIn("still in the studio", err)
        with open(os.path.join(self.stub, "calls")) as fh:
            calls = fh.read()
        self.assertIn("osascript %s" % self.ws, calls)                  # the stub, given the path as its argument
        self.assertTrue(os.path.isdir(self.ws))
        self.assertIn(self.ws, self.stored())


class ThrowOverMcp(Throwing):
    converse = mcp_tests.McpServer.converse
    call = staticmethod(mcp_tests.McpServer.call)

    def test_the_tool_is_destructive_needs_confirm_and_without_it_changes_nothing(self):
        tool = next(t for t in mcp_tests.mcp_server.TOOLS if t["name"] == "studio_throw_away")
        self.assertTrue(tool["annotations"]["destructiveHint"])
        self.assertIn("confirm", tool["inputSchema"]["required"])
        out = self.converse(self.call(1, "studio_throw_away", {"item_id": self.run.id}),
                            self.call(2, "studio_throw_away", {"item_id": self.run.id, "confirm": False}))
        self.assertTrue(out[1]["result"].get("isError"), out[1])
        result = out[2]["result"]
        self.assertNotIn("isError", result, result)
        self.assertEqual(validate(result["structuredContent"], tool["outputSchema"]), [])
        self.assertEqual((result["structuredContent"]["needs_confirm"], result["structuredContent"]["thrown"]),
                         (True, False))
        self.assert_untouched()
