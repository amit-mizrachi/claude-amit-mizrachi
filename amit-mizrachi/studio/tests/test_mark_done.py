"""Ticket 04: mark a run done by hand (its state files froze on a word that is no longer true).
Through `sdk.api`, the CLI as a subprocess, the MCP server over stdin/stdout, and home; the
v4 -> v5 store migration. Fixture homes only: nothing here reads or writes ~/.project-studio."""

import json
import os
import subprocess
import sys
import time
from unittest import mock

from sdk import api, store
from sdk.errors import Refused

from . import PLUGIN
from . import test_mcp_server as mcp_tests
from .support import Sources, TempHome, validate
from .test_readers import SID_A, agent

STUCK = "decision-units-20261024"      # BLOCKED from before a hand merge, like the real store's
LIVE = "turns-20261024"                # still running
BIN = os.path.join(PLUGIN, "bin", "project-studio")
MARKED = "marked done by you"


class Marking(Sources):
    """A blocked night run and a running one, both in Alpha, and a loose session in the Inbox. The
    state files are two minutes old, as a run's files are when someone comes to mark it."""

    def setUp(self):
        super().setUp()
        self.stuck_ws = self.workspace(STUCK, facts={"TOTAL": "2"},
                                       tags=(("T01", "DONE"), ("T02", "BLOCKED: tests red after the merge")))
        self.live_ws = self.workspace(LIVE, facts={"TOTAL": "2"}, tags=(("T01", "DONE"), ("T02", "")))
        for ws in (self.stuck_ws, self.live_ws):
            self.touch_state(ws, time.time() - 120)
        self.agents([agent(SID_A, "loose work", "/w/loose")])
        found = self.items()
        self.alpha = api.create_project("Alpha")
        self.stuck, self.live, self.session = found[self.stuck_ws], found[self.live_ws], found[SID_A]
        api.move_item(self.stuck.id, self.alpha.id)
        api.move_item(self.live.id, self.alpha.id)

    def touch_state(self, ws, when):
        state = os.path.join(ws, "state")
        for name in os.listdir(state):
            os.utime(os.path.join(state, name), (when, when))

    def items(self):
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}

    def card(self):
        return next(c for c in api.home().cards if c.project.id == self.alpha.id)

    def run_of(self, item_id):
        return next(r for r in api.project_status(self.alpha.id, refresh=False).runs if r.item_id == item_id)

    def panel_of(self, item_id):
        return next(r for r in api.project_view(self.alpha.id).runs if r.item_id == item_id)


class MarkThroughTheSdk(Marking):
    def test_a_marked_run_is_done_everywhere_with_its_stage_bar_as_the_files_say(self):
        before = self.card()
        self.assertEqual((before.attention, before.runs[0].item_id), ("blocked", self.stuck.id))
        bar = before.runs[0].bar
        lines = api.list_projects(with_runs=True).run_lines
        self.assertEqual(lines[self.alpha.id], "blocked - 2 runs, 2 active")
        self.assertTrue(self.panel_of(self.stuck.id).can_mark_done)
        self.assertFalse(self.panel_of(self.live.id).can_mark_done)

        done = api.mark_done(self.stuck.id)
        self.assertEqual((done.kind, done.message), ("mark-done", "Marked %s done" % self.stuck.title))
        self.assertIsNotNone(done.move_id)
        self.assertTrue(done.item.done_marked_at)

        card = self.card()
        self.assertEqual(card.attention, "")
        self.assertEqual([r.item_id for r in card.runs], [self.live.id, self.stuck.id])   # ranked by the new word
        line = card.runs[1]
        self.assertEqual((line.status, line.word, line.reason), ("done", "Done", MARKED))
        self.assertEqual(line.bar, bar)
        run = self.run_of(self.stuck.id)
        self.assertEqual((run.status, run.reason, run.marked_done), ("done", MARKED, True))
        panel = self.panel_of(self.stuck.id)
        self.assertEqual((panel.word, panel.can_mark_done), ("Done", False))
        self.assertIn(MARKED, panel.detail)
        self.assertEqual(api.list_projects(with_runs=True).run_lines[self.alpha.id], "running - 2 runs, 1 active")
        self.assertTrue(os.path.isfile(os.path.join(self.stuck_ws, "state", "T02.status")))   # no file touched

    def test_a_refresh_keeps_the_mark_while_the_files_hold_still(self):
        api.mark_done(self.stuck.id)
        api.refresh(force=True)
        self.assertEqual(self.run_of(self.stuck.id).reason, MARKED)

    def test_undo_restores_the_files_word_and_a_stale_undo_is_refused(self):
        done = api.mark_done(self.stuck.id)
        back = api.undo_move(done.move_id)
        self.assertEqual((back.kind, back.message), ("unmark-done", "%s is no longer marked done" % self.stuck.title))
        self.assertIsNone(back.item.done_marked_at)
        run = self.run_of(self.stuck.id)
        self.assertEqual((run.status, run.reason, run.marked_done), ("blocked", "tests red after the merge", False))
        self.assertEqual(self.card().attention, "blocked")
        with self.assertRaises(Refused) as caught:
            api.undo_move(done.move_id)
        self.assertEqual(str(caught.exception), "Can't undo: %s was changed again since." % self.stuck.title)
        again = api.undo_move(back.move_id)                               # undo the undo: marked again
        self.assertEqual(again.kind, "mark-done")
        self.assertEqual(self.run_of(self.stuck.id).reason, MARKED)

    def test_a_later_change_in_the_runs_files_drops_the_mark(self):
        api.mark_done(self.stuck.id)
        later = time.time() + 120
        with open(os.path.join(self.stuck_ws, "state", "EVENTS.log"), "a") as out:
            out.write("T02 retried\n")
        os.utime(os.path.join(self.stuck_ws, "state", "EVENTS.log"), (later, later))
        api.refresh(force=True)
        run = self.run_of(self.stuck.id)
        self.assertEqual((run.status, run.marked_done), ("blocked", False))
        self.assertNotIn(MARKED, run.reason)
        self.assertEqual(self.card().attention, "blocked")
        self.assertIsNotNone(api.mark_done(self.stuck.id).move_id)       # a new mark is taken again

    def test_a_status_file_rewritten_after_the_mark_drops_it_too(self):
        api.mark_done(self.stuck.id)
        later = time.time() + 120
        self.write(os.path.join(self.stuck_ws, "state", "T02.status"), "BLOCKED: still red\n")
        os.utime(os.path.join(self.stuck_ws, "state", "T02.status"), (later, later))
        api.refresh(force=True)
        run = self.run_of(self.stuck.id)
        self.assertEqual((run.status, run.reason), ("blocked", "still red"))

    def test_only_night_runs_can_be_marked(self):
        with self.assertRaises(Refused) as caught:
            api.mark_done(self.session.id)
        self.assertEqual(str(caught.exception), "Only a night run can be marked done; loose work is a session.")

    def test_twice_or_on_a_run_already_done_changes_nothing(self):
        api.mark_done(self.stuck.id)
        self.assertIsNone(api.mark_done(self.stuck.id).move_id)
        finished = self.workspace("finished-20261024", tags=(("T01", "DONE"),))
        item = self.items()[finished]
        again = api.mark_done(item.id)
        self.assertEqual((again.move_id, again.message), (None, "%s is already done" % item.title))

    def test_a_mark_teaches_no_rule(self):
        done = api.mark_done(self.stuck.id)
        with self.assertRaises(Refused):
            api.save_rule_from_move(done.move_id)


class MarkFromTheCli(Marking):
    def cli(self, *argv):
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def test_mark_done_prints_the_move_and_status_and_list_say_done(self):
        code, out, err = self.cli("mark-done", self.stuck.id[:8])
        self.assertEqual((code, err), (0, ""))
        move_id = int(out.split("Move ")[1].split(".")[0])
        self.assertIn("Marked %s done" % self.stuck.title, out)
        self.assertIn("Move %d. Undo: project-studio undo %d" % (move_id, move_id), out)
        code, out, _ = self.cli("status", self.alpha.id, "--no-refresh")
        self.assertEqual(code, 0)
        self.assertIn(MARKED, out)
        code, out, _ = self.cli("list")
        self.assertEqual(code, 0)
        self.assertIn("running - 2 runs, 1 active", out)
        code, out, _ = self.cli("undo", str(move_id), "--json")
        self.assertEqual((code, json.loads(out)["kind"]), (0, "unmark-done"))

    def test_a_session_is_refused_with_exit_1(self):
        code, out, _ = self.cli("mark-done", self.session.id, "--json")
        self.assertEqual(code, 1)
        error = json.loads(out)["error"]
        self.assertEqual(error["code"], "refused")
        self.assertIn("Only a night run can be marked done", error["message"])

    def test_help_names_the_command(self):
        code, out, _ = self.cli("help")
        self.assertEqual(code, 0)
        self.assertIn("mark-done", out)


class MarkOverMcp(Marking):
    converse = mcp_tests.McpServer.converse
    call = staticmethod(mcp_tests.McpServer.call)

    def test_the_tool_returns_a_schema_valid_move_and_status_shows_the_mark(self):
        schemas = {t["name"]: t["outputSchema"] for t in mcp_tests.mcp_server.TOOLS}
        tools = {t["name"]: t for t in mcp_tests.mcp_server.TOOLS}
        self.assertFalse(tools["studio_mark_done"]["annotations"]["destructiveHint"])
        out = self.converse(self.call(1, "studio_mark_done", {"item_id": self.stuck.id}),
                            self.call(2, "studio_status", {"project_id": self.alpha.id}),
                            self.call(3, "studio_mark_done", {"item_id": self.session.id}))
        for rid, name in ((1, "studio_mark_done"), (2, "studio_status")):
            result = out[rid]["result"]
            self.assertNotIn("isError", result, (name, result))
            self.assertEqual(validate(result["structuredContent"], schemas[name]), [], name)
        self.assertEqual(out[1]["result"]["structuredContent"]["kind"], "mark-done")
        runs = {r["item_id"]: r for r in out[2]["result"]["structuredContent"]["runs"]}
        self.assertEqual((runs[self.stuck.id]["status"], runs[self.stuck.id]["reason"],
                          runs[self.stuck.id]["marked_done"]), ("done", MARKED, True))
        self.assertTrue(out[3]["result"]["isError"])
        self.assertIn("Only a night run", json.dumps(out[3]["result"]))


class MarkDoneMigration(TempHome):
    def test_a_v4_store_is_backed_up_and_gains_the_mark_column(self):
        with mock.patch.object(store, "SCHEMA_VERSION", 4):
            with store.write() as conn:
                conn.execute("INSERT INTO items (id, kind, key, title, project_id, placed_by) "
                             "VALUES ('i_aaaaaaaaaaaa', 'night-sprint', '/w/run', 'run', 'inbox', 'inbox')")
        opened = store.open_store()
        try:
            self.assertEqual(opened.version, 5)
            self.assertTrue(opened.backup_path and os.path.isfile(opened.backup_path))
            item = dict(opened.conn.execute("SELECT * FROM items").fetchone())
        finally:
            opened.close()
        self.assertIsNone(item["done_marked_at"])
        self.assertEqual(api.mark_done("i_aaaaaaaaaaaa").kind, "mark-done")
