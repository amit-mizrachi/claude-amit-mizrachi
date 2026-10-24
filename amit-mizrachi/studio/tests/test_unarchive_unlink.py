"""Ticket 05: unarchive a project and unlink two projects, the way back for archive and link.
Through `sdk.api`, the CLI as a subprocess, the MCP server over stdin/stdout, and the studio web
server's routes. Fixture homes only: nothing here reads or writes ~/.project-studio."""

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
    """Alpha with Docs and Old under it; Old was archived on its own before Alpha was. Beta is linked to Alpha."""

    def setUp(self):
        super().setUp()
        self.alpha = api.create_project("Alpha")
        self.docs = api.create_project("Docs", self.alpha.id)
        self.old = api.create_project("Old", self.alpha.id)
        self.beta = api.create_project("Beta")
        api.link_projects(self.alpha.id, self.beta.id)
        api.archive_project(self.old.id)
        api.archive_project(self.alpha.id)

    def active(self):
        return [p.name for p in api.list_projects().projects]


class UnarchiveThroughTheSdk(Tree):
    def test_unarchive_brings_back_the_project_and_what_was_archived_with_it(self):
        back = api.unarchive_project(self.alpha.id)
        self.assertIsNone(back.archived_at)
        self.assertEqual(self.active(), ["Inbox", "Alpha", "Docs", "Beta"])
        self.assertIsNotNone(api.get_project(self.old.id).archived_at)   # archived on its own before: stays

    def test_unarchiving_an_active_project_changes_nothing(self):
        before = api.get_project(self.beta.id)
        self.assertEqual(api.unarchive_project(self.beta.id), before)
        api.unarchive_project(self.alpha.id)
        self.assertEqual(api.unarchive_project(self.alpha.id).archived_at, None)

    def test_an_active_sibling_with_the_name_in_any_case_refuses_it(self):
        api.create_project("ALPHA")
        with self.assertRaises(Refused) as caught:
            api.unarchive_project(self.alpha.id)
        self.assertEqual(str(caught.exception), "Can't unarchive Alpha: an active project named ALPHA already exists "
                                                "there. Rename one of them first.")
        self.assertIsNotNone(api.get_project(self.alpha.id).archived_at)

    def test_under_an_archived_parent_it_is_refused(self):
        with self.assertRaises(Refused) as caught:
            api.unarchive_project(self.old.id)
        self.assertEqual(str(caught.exception), "Can't unarchive Old: it is inside Alpha, which is archived. "
                                                "Unarchive Alpha first.")
        self.assertIsNotNone(api.get_project(self.old.id).archived_at)
        api.unarchive_project(self.alpha.id)
        self.assertIsNone(api.unarchive_project(self.old.id).archived_at)
        self.assertEqual(self.active(), ["Inbox", "Alpha", "Docs", "Old", "Beta"])

    def test_an_active_sub_project_under_an_archived_parent_is_refused(self):
        with self.assertRaises(Refused) as caught:
            api.unarchive_project(self.docs.id)
        self.assertEqual(str(caught.exception), "Can't unarchive Docs: it is inside Alpha, which is archived. "
                                                "Unarchive Alpha first.")

    def test_an_archived_project_is_found_by_id_prefix_and_an_unknown_id_is_not_found(self):
        self.assertEqual(api.resolve_project(self.alpha.id[:8]).id, self.alpha.id)
        with self.assertRaises(NotFound):
            api.unarchive_project("p_000000000000")

    def test_home_lists_every_archived_project_in_tree_order(self):
        archived = api.home().archived
        self.assertEqual([(a["id"], a["name"]) for a in archived], [(self.alpha.id, "Alpha"), (self.old.id, "Alpha / Old")])
        self.assertTrue(all(a["archived_at"] for a in archived))
        api.unarchive_project(self.alpha.id)
        self.assertEqual([a["name"] for a in api.home().archived], ["Alpha / Old"])


class UnlinkThroughTheSdk(Tree):
    def test_unlink_is_symmetric(self):
        gone = api.unlink_projects(self.beta.id, self.alpha.id)
        self.assertTrue(gone.removed)
        self.assertEqual((gone.a_id, gone.b_id), tuple(sorted((self.alpha.id, self.beta.id))))
        self.assertEqual(api.get_project(self.alpha.id).linked_ids, [])
        self.assertEqual(api.get_project(self.beta.id).linked_ids, [])

    def test_unlinking_a_pair_that_is_not_linked_reports_removed_false_and_changes_nothing(self):
        before = api.export_json().document["links"]
        self.assertFalse(api.unlink_projects(self.docs.id, self.beta.id).removed)
        self.assertFalse(api.unlink_projects(self.beta.id, self.beta.id).removed)
        self.assertEqual(api.export_json().document["links"], before)

    def test_an_unknown_project_is_not_found(self):
        with self.assertRaises(NotFound):
            api.unlink_projects(self.beta.id, "p_000000000000")

    def test_the_project_view_carries_each_link_for_its_unlink_control(self):
        api.unarchive_project(self.alpha.id)
        view = api.project_view(self.beta.id)
        self.assertEqual((view.linked, view.links), ("Linked: Alpha", [{"id": self.alpha.id, "name": "Alpha"}]))
        api.unlink_projects(self.alpha.id, self.beta.id)
        view = api.project_view(self.beta.id)
        self.assertEqual((view.linked, view.links), ("", []))


class FromTheCli(Tree):
    def cli(self, *argv):
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def test_unarchive_takes_an_archived_projects_id_prefix(self):
        code, out, err = self.cli("unarchive", self.alpha.id[:8])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.strip(), "Unarchived Alpha  %s" % self.alpha.id)
        code, out, _ = self.cli("unarchive", self.alpha.id, "--json")
        self.assertEqual((code, json.loads(out)["archived_at"]), (0, None))

    def test_a_refusal_is_exit_1_with_the_message(self):
        code, out, _ = self.cli("unarchive", self.old.id, "--json")
        self.assertEqual(code, 1)
        error = json.loads(out)["error"]
        self.assertEqual(error["code"], "refused")
        self.assertIn("Unarchive Alpha first.", error["message"])
        code, _, err = self.cli("unarchive", self.old.id)
        self.assertEqual(code, 1)
        self.assertIn("project-studio: refused: Can't unarchive Old", err)

    def test_unlink_says_whether_a_link_was_removed(self):
        code, out, _ = self.cli("unlink", "Beta", self.alpha.id)
        lo, hi = sorted((self.alpha.id, self.beta.id))
        self.assertEqual((code, out.strip()), (0, "Unlinked %s and %s." % (lo, hi)))
        code, out, _ = self.cli("unlink", "Beta", self.alpha.id)
        self.assertEqual((code, out.strip()), (0, "Not linked: %s and %s. Nothing changed." % (lo, hi)))
        code, out, _ = self.cli("--json", "unlink", "Beta", self.alpha.id)
        self.assertEqual((code, json.loads(out)), (0, {"a_id": lo, "b_id": hi, "removed": False}))

    def test_a_missing_argument_is_a_usage_error(self):
        self.assertEqual(self.cli("unlink", "Beta")[0], 2)
        self.assertEqual(self.cli("unarchive")[0], 2)

    def test_help_names_both_commands(self):
        code, out, _ = self.cli("help")
        self.assertEqual(code, 0)
        self.assertIn("unarchive", out)
        self.assertIn("unlink", out)


class OverMcp(Tree):
    converse = mcp_tests.McpServer.converse
    call = staticmethod(mcp_tests.McpServer.call)

    def test_both_tools_return_schema_valid_output_and_refusals_are_tool_errors(self):
        tools = {t["name"]: t for t in mcp_tests.mcp_server.TOOLS}
        for name in ("studio_unarchive", "studio_unlink"):
            self.assertFalse(tools[name]["annotations"]["destructiveHint"], name)
        out = self.converse(self.call(1, "studio_unarchive", {"project_id": self.old.id}),
                            self.call(2, "studio_unarchive", {"project_id": self.alpha.id}),
                            self.call(3, "studio_unlink", {"a_id": self.beta.id, "b_id": self.alpha.id}),
                            self.call(4, "studio_unlink", {"a_id": self.alpha.id, "b_id": self.beta.id}))
        self.assertTrue(out[1]["result"]["isError"])
        self.assertIn("Unarchive Alpha first.", json.dumps(out[1]["result"]))
        for rid, name in ((2, "studio_unarchive"), (3, "studio_unlink"), (4, "studio_unlink")):
            result = out[rid]["result"]
            self.assertNotIn("isError", result, (name, result))
            self.assertEqual(validate(result["structuredContent"], tools[name]["outputSchema"]), [], name)
        self.assertIsNone(out[2]["result"]["structuredContent"]["archived_at"])
        self.assertEqual([out[rid]["result"]["structuredContent"]["removed"] for rid in (3, 4)], [True, False])


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

    def test_unarchive_and_unlink_are_one_route_each(self):
        status, body = self.post("/api/unarchive", {"project_id": self.old.id})
        self.assertEqual((status, body["code"]), (400, "refused"))
        status, body = self.post("/api/unarchive", {"project_id": self.alpha.id})
        self.assertEqual((status, body["archived_at"]), (200, None))
        status, body = self.post("/api/unlink", {"project_id": self.beta.id, "other_id": self.alpha.id})
        self.assertEqual((status, body["removed"]), (200, True))
        self.assertEqual(api.get_project(self.beta.id).linked_ids, [])
