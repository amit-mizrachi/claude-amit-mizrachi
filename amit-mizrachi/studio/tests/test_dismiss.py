"""Ticket 03: dismiss an item (hide it, delete nothing, undo it). Through `sdk.api`, the CLI as a
subprocess, the MCP server over stdin/stdout, and home; the v3 -> v4 store migration. Fixture
homes only: nothing here reads or writes ~/.project-studio."""

import json
import os
import sqlite3
import subprocess
import sys
from unittest import mock

from sdk import api, store
from sdk.errors import Refused

from . import PLUGIN
from . import test_mcp_server as mcp_tests
from .support import Sources, TempHome, validate
from .test_readers import SID_A, SID_B, agent

SLUG = "dismiss-20261024"
BIN = os.path.join(PLUGIN, "bin", "project-studio")


class Dismissing(Sources):
    """A night run with an auto-attached session (by title), a ticket worktree and a PR, filed in Alpha."""

    def setUp(self):
        super().setUp()
        self.repo, (self.wt, self.ticket_wt) = self.git_repo("r", [("r-dis", "feat/d"), ("r-dis-T02", "feat/d--T02")])
        self.ws = self.workspace(SLUG, facts={"REPO_PATH": self.repo, "REPO_SLUG": "me/r", "BRANCH": "feat/d",
                                              "WORKTREE": self.wt, "TOTAL": "2"},
                                 tags=(("T01", "DONE"), ("T02", "")), files={"state/T02.cwd": self.ticket_wt + "\n"})
        self.prs("me/r", [{"number": 7, "title": "dismiss", "headRefName": "feat/d", "state": "OPEN", "isDraft": False,
                           "url": "https://github.com/me/r/pull/7", "updatedAt": "2026-10-24T00:00:00Z"}])
        self.agents([agent(SID_A, "ns-%s-T02" % SLUG, "/x"), agent(SID_B, "loose work", "/w/loose")])
        found = self.items()
        self.alpha = api.create_project("Alpha")
        self.run, self.session, self.loose = found[self.ws], found[SID_A], found[SID_B]
        self.pr = next(i for i in found.values() if i.kind == "pr")
        self.worktree = found[self.ticket_wt]
        api.move_item(self.run.id, self.alpha.id)

    def items(self, **kw):
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000, **kw).items}

    def card(self):
        return next(c for c in api.home().cards if c.project.id == self.alpha.id)


class DismissThroughTheSdk(Dismissing):
    def test_a_dismissed_run_leaves_home_status_list_and_find_with_its_attached_items(self):
        before = api.list_projects().projects
        done = api.dismiss_item(self.run.id)
        self.assertEqual((done.kind, done.message), ("dismiss", "Dismissed %s" % self.run.title))
        self.assertTrue(done.item.dismissed and done.item.dismissed_at)
        self.assertEqual(done.item.project_id, self.alpha.id)            # it keeps its home
        self.assertTrue({self.session.id, self.worktree.id, self.pr.id} <= set(done.followed), done.followed)
        self.assertNotIn(self.loose.id, done.followed)
        self.assertEqual((self.card().runs, self.card().empty), ([], "No night runs yet"))
        status = api.project_status(self.alpha.id, refresh=False)
        self.assertEqual((status.runs, status.sessions, status.prs), ([], [], []))
        count = {p.id: p.item_count for p in api.list_projects().projects}
        was = {p.id: p.item_count for p in before}
        self.assertEqual(count[self.alpha.id], was[self.alpha.id] - 1 - len(done.followed))
        self.assertNotIn(self.ws, {i.key for i in api.find_items(refresh=False, limit=1000).items})
        found = api.find_items(query=SLUG, refresh=False, include_dismissed=True).items
        self.assertEqual([(i.key, i.dismissed) for i in found if i.kind == "night-sprint"], [(self.ws, True)])
        self.assertTrue(os.path.isdir(self.ws))                           # nothing on disk is touched

    def test_a_refresh_never_clears_a_dismissal_and_a_gone_item_stays_dismissed(self):
        api.dismiss_item(self.run.id)
        self.agents([agent(SID_B, "loose work", "/w/loose")])           # the run's session is gone now
        after = self.items(include_dismissed=True)
        self.assertTrue(after[self.ws].dismissed)
        self.assertTrue(after[SID_A].gone and after[SID_A].dismissed)
        self.assertEqual(self.card().runs, [])

    def test_undo_of_a_dismissal_brings_back_the_run_and_its_attached_items(self):
        done = api.dismiss_item(self.run.id)
        back = api.undo_move(done.move_id)
        self.assertEqual((back.kind, back.message), ("restore", "Restored %s" % self.run.title))
        self.assertEqual(sorted(back.followed), sorted(done.followed))
        self.assertEqual([r.item_id for r in self.card().runs], [self.run.id])
        self.assertIn(self.session.id, [s.id for s in api.project_status(self.alpha.id, refresh=False).sessions])
        again = api.undo_move(back.move_id)                               # undo the restore: dismissed again
        self.assertEqual((again.kind, sorted(again.followed)), ("dismiss", sorted(done.followed)))
        self.assertEqual(self.card().runs, [])

    def test_a_stale_undo_is_refused(self):
        done = api.dismiss_item(self.run.id)
        api.restore_item(self.run.id)
        with self.assertRaises(Refused) as caught:
            api.undo_move(done.move_id)
        self.assertEqual(str(caught.exception), "Can't undo: %s was changed again since." % self.run.title)

    def test_restore_takes_back_what_the_dismissal_took_and_twice_changes_nothing(self):
        api.dismiss_item(self.session.id)                                 # dismissed on its own first
        done = api.dismiss_item(self.run.id)
        self.assertNotIn(self.session.id, done.followed)
        self.assertIsNone(api.dismiss_item(self.run.id).move_id)
        back = api.restore_item(self.run.id)
        self.assertEqual(sorted(back.followed), sorted(done.followed))
        self.assertTrue(self.items(include_dismissed=True)[SID_A].dismissed)   # it stays as it was dismissed
        self.assertIsNone(api.restore_item(self.run.id).move_id)

    def test_a_dismissed_inbox_item_leaves_the_inbox_and_its_count(self):
        before = api.home().inbox_count
        self.assertIn(self.loose.id, [e.item.id for e in api.inbox(refresh=False).entries])
        api.dismiss_item(self.loose.id)
        self.assertNotIn(self.loose.id, [e.item.id for e in api.inbox(refresh=False).entries])
        self.assertNotIn(self.loose.id, [r.item_id for r in api.inbox_view().rows])
        self.assertEqual(api.home().inbox_count, before - 1)
        self.assertEqual(api.get_project(store.INBOX_ID).item_count, before - 1)

    def test_the_project_view_folds_dismissed_items_with_restore(self):
        api.dismiss_item(self.run.id)
        view = api.project_view(self.alpha.id)
        self.assertEqual(view.runs, [])
        fold = view.dismissed
        self.assertEqual((fold.kind, fold.label), ("dismissed", "Dismissed"))
        self.assertIn("1 night run", fold.summary)
        self.assertEqual({r.action for r in fold.rows}, {"Restore"})
        self.assertIn(self.run.id, [r.item_id for r in fold.rows])
        self.assertTrue(fold.rows[0].text.split(" - ")[-1].startswith("dismissed"))
        api.restore_item(self.run.id)
        self.assertIsNone(api.project_view(self.alpha.id).dismissed)

    def test_a_dismissal_teaches_no_rule_and_a_project_holding_one_is_not_empty(self):
        done = api.dismiss_item(self.run.id)
        with self.assertRaises(Refused):
            api.save_rule_from_move(done.move_id)
        with self.assertRaises(Refused):
            api.delete_project(self.alpha.id)


class DismissFromTheCli(Dismissing):
    def cli(self, *argv):
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def test_dismiss_and_restore_print_the_move_and_its_undo(self):
        code, out, err = self.cli("dismiss", self.run.id[:8])
        self.assertEqual((code, err), (0, ""))
        move_id = int(out.split("Move ")[1].split(".")[0])
        self.assertIn("Dismissed %s" % self.run.title, out)
        self.assertIn("attached items dismissed with it.", out)
        self.assertIn("Move %d. Undo: project-studio undo %d" % (move_id, move_id), out)
        code, out, _ = self.cli("find", "--no-refresh", "--dismissed", SLUG)
        self.assertEqual(code, 0)
        self.assertIn("(dismissed)", out)
        code, out, _ = self.cli("restore", self.run.id, "--json")
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual((result["kind"], result["item"]["dismissed"]), ("restore", False))

    def test_an_unknown_item_exits_1_with_the_sdk_error(self):
        code, out, err = self.cli("dismiss", "i_000000000000", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["error"]["code"], "not_found")

    def test_help_names_both_commands(self):
        code, out, _ = self.cli("help")
        self.assertEqual(code, 0)
        self.assertIn("dismiss", out)
        self.assertIn("restore", out)


class DismissOverMcp(Dismissing):
    converse = mcp_tests.McpServer.converse
    call = staticmethod(mcp_tests.McpServer.call)

    def test_dismiss_and_restore_tools_return_schema_valid_moves(self):
        schemas = {t["name"]: t["outputSchema"] for t in mcp_tests.mcp_server.TOOLS}
        tools = {t["name"]: t for t in mcp_tests.mcp_server.TOOLS}
        for name in ("studio_dismiss", "studio_restore"):
            self.assertFalse(tools[name]["annotations"]["destructiveHint"], name)
        out = self.converse(self.call(1, "studio_dismiss", {"item_id": self.run.id}),
                            self.call(2, "studio_find", {"query": SLUG, "include_dismissed": True}),
                            self.call(3, "studio_restore", {"item_id": self.run.id}))
        for rid, name in ((1, "studio_dismiss"), (2, "studio_find"), (3, "studio_restore")):
            result = out[rid]["result"]
            self.assertNotIn("isError", result, (name, result))
            self.assertEqual(validate(result["structuredContent"], schemas[name]), [], name)
        self.assertEqual(out[1]["result"]["structuredContent"]["kind"], "dismiss")
        self.assertTrue(any(i["dismissed"] for i in out[2]["result"]["structuredContent"]["items"]))
        self.assertFalse(out[3]["result"]["structuredContent"]["item"]["dismissed"])


class DismissalMigration(TempHome):
    def test_a_v3_store_is_backed_up_and_gains_dismissals_and_move_kinds_in_one_step(self):
        with mock.patch.object(store, "SCHEMA_VERSION", 3):
            with store.write() as conn:
                conn.execute("INSERT INTO items (id, kind, key, title, project_id, placed_by) "
                             "VALUES ('i_aaaaaaaaaaaa', 'pr', 'o/r#1', 'PR 1', 'inbox', 'inbox')")
                conn.execute("INSERT INTO moves (item_id, from_project, to_project, revision, at) "
                             "VALUES ('i_aaaaaaaaaaaa', 'inbox', 'inbox', 1, 't')")
        opened = store.open_store()
        try:
            self.assertEqual(opened.version, store.SCHEMA_VERSION)
            self.assertTrue(opened.backup_path and os.path.isfile(opened.backup_path))
            move = dict(opened.conn.execute("SELECT * FROM moves").fetchone())
            item = dict(opened.conn.execute("SELECT * FROM items").fetchone())
        finally:
            opened.close()
        self.assertEqual((move["kind"], move["data_json"], item["dismissed_at"]), ("move", "{}", None))
        backup = sqlite3.connect(opened.backup_path)
        try:
            self.assertEqual(backup.execute("SELECT version FROM schema_version").fetchone()[0], 3)
        finally:
            backup.close()
        self.assertEqual(api.dismiss_item("i_aaaaaaaaaaaa").kind, "dismiss")
