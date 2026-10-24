"""Sprint 2 ticket 01: remove a project that still holds things, and Undo it. Through `sdk.api`, the
CLI as a subprocess, the MCP server over stdin/stdout, and the studio web server's route. Fixture
homes only: nothing here reads or writes ~/.project-studio."""

import http.client
import json
import os
import subprocess
import sys

from sdk import api, server
from sdk.errors import NotFound, Refused

from . import PLUGIN
from . import test_mcp_server as mcp_tests
from .support import TempHome, validate

BIN = os.path.join(PLUGIN, "bin", "project-studio")


class Tree(TempHome):
    """Shapes / Alpha holds a night run, a PR, a dismissed artifact, the sub-projects Docs and Old
    (archived on its own), a rule and a link to Beta."""

    def setUp(self):
        super().setUp()
        self.shapes = api.create_project("Shapes")
        self.alpha = api.create_project("Alpha", self.shapes.id)
        self.docs = api.create_project("Docs", self.alpha.id)
        self.old = api.create_project("Old", self.alpha.id)
        api.archive_project(self.old.id)
        self.beta = api.create_project("Beta")
        api.link_projects(self.alpha.id, self.beta.id)
        self.rule = api.add_rule(self.alpha.id, "workspace", "alpha-*").rule
        self.run = api.add_item("night-sprint", self.mkdir("roots", "alpha-run"), self.alpha.id, "alpha run").item
        self.pr = api.add_item("pr", "acme/alpha#7", self.alpha.id).item
        self.art = api.add_item("artifact", "https://claude.ai/artifact/alpha", self.alpha.id).item
        api.dismiss_item(self.art.id)

    def store(self):
        """The store minus the move ledger, which the remove and its Undo add to."""
        doc = api.export_json().document
        doc.pop("exported_at")
        doc.pop("moves")
        for item in doc["items"]:
            item.pop("revision")
        for project in doc["projects"]:
            project.pop("revision")
            project.pop("updated_at")
        return doc

    def home_of(self, item):
        return api.resolve_item(item.id).project_id


class RemoveThroughTheSdk(Tree):
    def test_without_confirmed_it_says_what_moves_where_and_changes_nothing(self):
        before = self.store()
        plan = api.remove_project(self.alpha.id)
        self.assertEqual(self.store(), before)
        self.assertEqual((plan.removed, plan.needs_confirm, plan.move_id), (False, True, None))
        self.assertEqual((plan.parent_id, plan.to_project_id, plan.to_name), (self.shapes.id, self.shapes.id, "Shapes"))
        self.assertEqual(plan.sub_projects, [{"id": self.docs.id, "name": "Docs"}, {"id": self.old.id, "name": "Old"}])
        self.assertEqual((plan.runs, plan.run_titles, plan.items), (1, ["alpha run"], 2))
        self.assertEqual(plan.message, "Remove Alpha?\n\nInside: 2 sub-projects (Docs, Old), 1 night run (alpha run), "
                                       "2 other items.\nThen the sub-projects move to Shapes and the runs and items "
                                       "go to Shapes.\n\nNo session, folder or PR is touched; only the project goes. "
                                       "Undo brings it back with everything in it.")

    def test_confirmed_it_moves_everything_up_and_deletes_the_project_in_one_move(self):
        done = api.remove_project(self.alpha.id, confirmed=True)
        self.assertEqual((done.removed, done.needs_confirm), (True, False))
        self.assertIsInstance(done.move_id, int)
        self.assertEqual(done.message, "Removed Alpha. 2 sub-projects and 3 items moved to Shapes")
        with self.assertRaises(NotFound):
            api.get_project(self.alpha.id)
        for item in (self.run, self.pr, self.art):
            self.assertEqual(self.home_of(item), self.shapes.id)
        self.assertTrue(api.resolve_item(self.art.id).dismissed)            # still dismissed, just elsewhere
        self.assertEqual(api.get_project(self.docs.id).parent_id, self.shapes.id)
        self.assertEqual(api.get_project(self.old.id).parent_id, self.shapes.id)
        self.assertEqual(api.get_project(self.beta.id).linked_ids, [])
        self.assertEqual(api.list_rules().rules, [])
        moves = api.export_json().document["moves"]
        self.assertEqual(moves[-1]["kind"], "remove-project")
        up = [m for m in moves if m["kind"] == "move" and m["from_project"] == self.alpha.id]
        self.assertEqual(sorted(m["item_id"] or m["project_id"] for m in up),       # each recorded as a move
                         sorted([self.run.id, self.pr.id, self.art.id, self.docs.id, self.old.id]))

    def test_undo_brings_back_the_same_project_with_everything_in_it(self):
        before = self.store()
        done = api.remove_project(self.alpha.id, confirmed=True)
        back = api.undo_move(done.move_id)
        self.assertEqual(back.message, "Alpha is back, with 2 sub-projects and 3 items")
        self.assertEqual((back.project.id, back.project.parent_id, back.kind), (self.alpha.id, self.shapes.id,
                                                                                "remove-project"))
        self.assertEqual(self.store(), before)
        self.assertEqual(api.get_project(self.beta.id).linked_ids, [self.alpha.id])
        self.assertEqual([r.id for r in api.list_rules(self.alpha.id).rules], [self.rule.id])
        with self.assertRaises(Refused) as caught:
            api.undo_move(done.move_id)
        self.assertEqual(str(caught.exception), "Can't undo: Alpha is back already.")

    def test_a_top_level_project_sends_its_items_to_the_inbox_and_its_sub_projects_to_the_top(self):
        api.move(self.alpha.id, None)
        plan = api.remove_project(self.alpha.id)
        self.assertEqual((plan.parent_id, plan.to_project_id, plan.to_name), (None, "inbox", "Inbox"))
        self.assertIn("Then the sub-projects become top-level and the runs and items go to the Inbox.", plan.message)
        done = api.remove_project(self.alpha.id, confirmed=True)
        self.assertEqual(done.message, "Removed Alpha. 2 sub-projects are now top-level; 3 items moved to the Inbox")
        self.assertEqual({self.home_of(i) for i in (self.run, self.pr, self.art)}, {"inbox"})
        self.assertEqual(api.resolve_item(self.pr.id).placed_by, "inbox")   # unfiled again, so rules may file it
        self.assertIsNone(api.get_project(self.docs.id).parent_id)
        api.undo_move(done.move_id)
        self.assertEqual(api.get_project(self.alpha.id).parent_id, None)
        self.assertEqual(api.resolve_item(self.pr.id).placed_by, "manual")
        self.assertEqual(api.get_project(self.docs.id).parent_id, self.alpha.id)

    def test_a_stale_undo_is_refused_and_changes_nothing(self):
        done = api.remove_project(self.alpha.id, confirmed=True)
        api.move_item(self.pr.id, self.beta.id)
        before = self.store()
        with self.assertRaises(Refused) as caught:
            api.undo_move(done.move_id)
        self.assertEqual(str(caught.exception), "Can't undo: alpha#7 was moved or changed again since.")
        self.assertEqual(self.store(), before)

    def test_a_sub_project_moved_since_makes_the_undo_stale(self):
        done = api.remove_project(self.alpha.id, confirmed=True)
        api.move(self.docs.id, self.beta.id)
        with self.assertRaises(Refused) as caught:
            api.undo_move(done.move_id)
        self.assertEqual(str(caught.exception), "Can't undo: Docs was moved again since.")

    def test_the_name_taken_again_refuses_the_undo(self):
        done = api.remove_project(self.alpha.id, confirmed=True)
        api.create_project("alpha", self.shapes.id)
        with self.assertRaises(Refused) as caught:
            api.undo_move(done.move_id)
        self.assertEqual(str(caught.exception), "Can't undo: a project named Alpha is there now. "
                                                "Rename one of them first.")

    def test_an_empty_project_is_removed_the_same_way(self):
        plan = api.remove_project(self.beta.id)
        self.assertEqual(plan.message, "Remove Beta? Nothing inside. It goes; nothing on disk changes, "
                                       "and Undo brings it back.")
        self.assertEqual((plan.sub_projects, plan.runs, plan.items), ([], 0, 0))
        done = api.remove_project(self.beta.id, confirmed=True)
        self.assertEqual(done.message, "Removed Beta")
        back = api.undo_move(done.move_id)
        self.assertEqual((back.project.id, back.message), (self.beta.id, "Beta is back"))

    def test_the_inbox_and_an_archived_project_are_refused(self):
        with self.assertRaises(Refused) as caught:
            api.remove_project("inbox", confirmed=True)
        self.assertEqual(str(caught.exception), "The Inbox can't be removed.")
        with self.assertRaises(Refused) as caught:
            api.remove_project(self.old.id)
        self.assertEqual(str(caught.exception), "Can't remove Old: it is archived. Unarchive it first.")
        with self.assertRaises(NotFound):
            api.remove_project("p_000000000000")

    def test_a_sub_project_that_would_clash_by_name_refuses_it_before_anything(self):
        api.create_project("DOCS", self.shapes.id)
        before = self.store()
        with self.assertRaises(Refused) as caught:
            api.remove_project(self.alpha.id, confirmed=True)
        self.assertEqual(str(caught.exception), "Can't remove Alpha: its sub-project Docs would land next to the "
                                                "project DOCS in Shapes. Rename one of them first.")
        self.assertEqual(self.store(), before)

    def test_delete_keeps_its_empty_only_rule(self):
        with self.assertRaises(Refused):
            api.delete_project(self.alpha.id)


class FromTheCli(Tree):
    def cli(self, *argv):
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def test_without_yes_it_prints_the_plan_and_exits_confirm_needed(self):
        code, _, err = self.cli("remove-project", "Alpha")
        self.assertEqual(code, 2)
        self.assertIn("project-studio: confirm_needed: Remove Alpha?", err)
        self.assertIn("Nothing was removed. Run again with --yes to do it.", err)
        code, out, _ = self.cli("remove-project", "Alpha", "--json")
        self.assertEqual((code, json.loads(out)["error"]["code"]), (2, "confirm_needed"))
        self.assertEqual(api.get_project(self.alpha.id).name, "Alpha")

    def test_with_yes_it_removes_and_prints_the_undo_command(self):
        code, out, err = self.cli("remove-project", self.alpha.id[:8], "--yes")
        self.assertEqual((code, err), (0, ""))
        lines = out.strip().splitlines()
        self.assertEqual(lines[0], "Removed Alpha. 2 sub-projects and 3 items moved to Shapes")
        move_id = int(lines[1].split()[1].rstrip("."))
        self.assertEqual(lines[1], "Move %d. Undo: project-studio undo %d" % (move_id, move_id))
        code, out, _ = self.cli("undo", str(move_id))
        self.assertEqual((code, out.strip()), (0, "Alpha is back, with 2 sub-projects and 3 items"))

    def test_json_and_refusals_use_the_usual_exit_codes(self):
        code, out, _ = self.cli("--json", "remove-project", "Beta", "--yes")
        self.assertEqual((code, json.loads(out)["removed"]), (0, True))
        code, out, _ = self.cli("remove-project", "inbox", "--yes", "--json")
        self.assertEqual((code, json.loads(out)["error"]["code"]), (1, "refused"))
        self.assertEqual(self.cli("remove-project")[0], 2)

    def test_help_names_the_command(self):
        code, out, _ = self.cli("help")
        self.assertEqual(code, 0)
        self.assertIn("remove-project", out)


class OverMcp(Tree):
    converse = mcp_tests.McpServer.converse
    call = staticmethod(mcp_tests.McpServer.call)

    def test_confirm_is_required_and_only_true_removes(self):
        tool = {t["name"]: t for t in mcp_tests.mcp_server.TOOLS}["studio_remove_project"]
        self.assertTrue(tool["annotations"]["destructiveHint"])
        self.assertEqual(tool["inputSchema"]["required"], ["project_id", "confirm"])
        out = self.converse(self.call(1, "studio_remove_project", {"project_id": self.alpha.id}),
                            self.call(2, "studio_remove_project", {"project_id": self.alpha.id, "confirm": False}),
                            self.call(3, "studio_remove_project", {"project_id": self.alpha.id, "confirm": True}),
                            self.call(4, "studio_remove_project", {"project_id": "inbox", "confirm": True}))
        self.assertTrue(out[1]["result"]["isError"])
        self.assertTrue(out[4]["result"]["isError"])
        self.assertIn("The Inbox can't be removed.", json.dumps(out[4]["result"]))
        for rid in (2, 3):
            self.assertNotIn("isError", out[rid]["result"])
            self.assertEqual(validate(out[rid]["result"]["structuredContent"], tool["outputSchema"]), [], rid)
        plan, done = out[2]["result"]["structuredContent"], out[3]["result"]["structuredContent"]
        self.assertEqual((plan["needs_confirm"], plan["removed"], plan["move_id"]), (True, False, None))
        self.assertEqual((done["needs_confirm"], done["removed"]), (False, True))
        undo = self.converse(self.call(5, "studio_undo", {"move_id": done["move_id"]}))[5]["result"]
        self.assertNotIn("isError", undo)
        self.assertEqual(undo["structuredContent"]["project"]["id"], self.alpha.id)


class FromThePage(Tree):
    def setUp(self):
        super().setUp()
        self.addCleanup(api.stop_studio)
        self.port = api.open_studio().port
        self.token = server.read_info()["token"]

    def post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, json.dumps(body).encode(),
                     {"Host": "127.0.0.1:%d" % self.port, "X-Studio-Token": self.token})
        res = conn.getresponse()
        data = json.loads(res.read())
        conn.close()
        return res.status, data

    def test_remove_asks_first_then_removes_and_the_undo_route_brings_it_back(self):
        status, plan = self.post("/api/remove-project", {"project_id": self.alpha.id})
        self.assertEqual((status, plan["needs_confirm"]), (200, True))
        status, done = self.post("/api/remove-project", {"project_id": self.alpha.id, "confirmed": True})
        self.assertEqual((status, done["removed"], done["parent_id"]), (200, True, self.shapes.id))
        status, back = self.post("/api/undo", {"move_id": done["move_id"]})
        self.assertEqual((status, back["project"]["id"]), (200, self.alpha.id))
