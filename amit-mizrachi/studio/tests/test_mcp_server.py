"""The project-studio MCP server, driven over stdin/stdout JSON-RPC like a real client."""

import json
import os
import subprocess
import sys

import mcp_server
from sdk import api

from . import STUDIO
from .support import Sources, TempHome, validate
from .test_readers import SID_A, SID_B, agent

SERVER = os.path.join(STUDIO, "mcp_server.py")


class McpServer(TempHome):
    def converse(self, *requests):
        """Send every request, close stdin, and return the responses keyed by id."""
        lines = "".join(json.dumps(r) + "\n" for r in requests)
        env = dict(os.environ, PROJECT_STUDIO_HOME=self.home)
        done = subprocess.run([sys.executable, SERVER], input=lines, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        replies = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
        return {r["id"]: r for r in replies}

    @staticmethod
    def call(rid, name, arguments):
        return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": arguments}}

    def test_initialize_and_tools_list_show_schemas_and_annotations(self):
        out = self.converse(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(out[1]["result"]["serverInfo"]["name"], "project-studio")
        listed = [t["name"] for t in out[2]["result"]["tools"]]
        tools = {t["name"]: t for t in out[2]["result"]["tools"]}
        self.assertEqual(listed, [t["name"] for t in mcp_server.TOOLS])     # the server's own list, no literal
        self.assertEqual(len(tools), len(listed), "a tool name is listed twice")
        self.assertEqual(set(tools), set(mcp_server.HANDLERS))
        for tool in tools.values():
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertEqual(tool["outputSchema"]["type"], "object")
            for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                self.assertIn(hint, tool["annotations"])
        self.assertTrue(tools["studio_list"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["studio_create"]["annotations"]["readOnlyHint"])
        self.assertEqual(tools["studio_create"]["inputSchema"]["required"], ["name"])
        self.assertLessEqual(tools["studio_list"]["inputSchema"]["properties"]["limit"]["maximum"], 200)
        for name in ("studio_delete", "studio_purge", "studio_rule_delete", "studio_throw_away"):
            self.assertTrue(tools[name]["annotations"]["destructiveHint"], name)

    def test_a_create_then_a_list_round_trips(self):
        out = self.converse(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            self.call(2, "studio_create", {"name": "Night runs"}),
            self.call(3, "studio_list", {}))
        created = out[2]["result"]
        self.assertNotIn("isError", created)
        project = created["structuredContent"]
        self.assertEqual(project["name"], "Night runs")
        self.assertEqual(json.loads(created["content"][0]["text"]), project)
        listed = out[3]["result"]["structuredContent"]
        self.assertEqual([p["id"] for p in listed["projects"]], ["inbox", project["id"]])
        self.assertEqual((listed["total"], listed["truncated"]), (2, False))

    def test_sdk_refusals_and_bad_arguments_are_tool_errors(self):
        out = self.converse(
            self.call(1, "studio_create", {"name": "x", "parent_id": "inbox"}),
            self.call(2, "studio_create", {"name": "x", "colour": "red"}),
            self.call(3, "studio_list", {"limit": 0}),
            {"jsonrpc": "2.0", "id": 4, "method": "no/such"})
        self.assertTrue(out[1]["result"]["isError"])
        self.assertIn("refused: The Inbox can't hold sub-projects.", out[1]["result"]["content"][0]["text"])
        self.assertIn("unknown argument(s): colour", out[2]["result"]["content"][0]["text"])
        self.assertTrue(out[3]["result"]["isError"])
        self.assertEqual(out[4]["error"]["code"], -32601)


class EveryNewTool(Sources):
    """Each ticket-02 tool called once over stdio; its structured output must fit its outputSchema."""

    converse = McpServer.converse
    call = staticmethod(McpServer.call)

    def test_each_new_tool_returns_schema_valid_output(self):
        self.agents([agent(SID_A, "alpha", "/w/alpha")])
        folder = self.mkdir("ad-hoc")
        out = self.converse({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                            self.call(2, "studio_create", {"name": "One"}),
                            self.call(3, "studio_create", {"name": "Two"}),
                            self.call(4, "studio_find", {"query": "alpha"}))
        schemas = {t["name"]: t["outputSchema"] for t in out[1]["result"]["tools"]}
        one, two = out[2]["result"]["structuredContent"]["id"], out[3]["result"]["structuredContent"]["id"]
        found = out[4]["result"]["structuredContent"]
        self.assertEqual([i["key"] for i in found["items"]], [SID_A])
        item = found["items"][0]
        out2 = self.converse(
            self.call(5, "studio_status", {"project_id": one}),
            self.call(6, "studio_add", {"kind": "worktree", "key": folder, "project_id": one}),
            self.call(7, "studio_move", {"id": item["id"], "to_project_id": one, "revision": item["revision"]}),
            self.call(8, "studio_link", {"a_id": one, "b_id": two}),
            self.call(9, "studio_remove", {"item_id": item["id"]}),
            self.call(10, "studio_archive", {"project_id": two}))
        replies = {**out, **out2}
        for rid, name in ((4, "studio_find"), (5, "studio_status"), (6, "studio_add"), (7, "studio_move"),
                          (8, "studio_link"), (9, "studio_remove"), (10, "studio_archive")):
            result = replies[rid]["result"]
            self.assertNotIn("isError", result, (name, result))
            self.assertEqual(validate(result["structuredContent"], schemas[name]), [], name)
            self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        self.assertEqual(replies[7]["result"]["structuredContent"]["item"]["project_id"], one)
        self.assertIsInstance(replies[7]["result"]["structuredContent"]["move_id"], int)
        self.assertEqual(replies[9]["result"]["structuredContent"]["item"]["project_id"], "inbox")
        self.assertTrue(replies[10]["result"]["structuredContent"]["archived_at"])

    def test_status_lists_are_bounded_with_totals(self):
        self.agents([agent(SID_A, "alpha", "/w/alpha"), agent(SID_B, "beta", "/w/beta")])
        out = self.converse(self.call(1, "studio_status", {"project_id": "inbox", "limit": 1}),
                            self.call(2, "studio_status", {"project_id": "inbox", "limit": 0}))
        status = out[1]["result"]["structuredContent"]
        self.assertEqual((len(status["sessions"]), status["totals"]["sessions"], status["truncated"]), (1, 2, True))
        self.assertTrue(out[2]["result"]["isError"])

    def test_an_unknown_tool_is_invalid_params(self):
        out = self.converse(self.call(1, "nope", {}))
        self.assertEqual(out[1]["error"]["code"], -32602)

    def test_a_stale_revision_is_a_tool_error_with_the_sdk_message(self):
        self.agents([agent(SID_A, "alpha", "/w/alpha")])
        out = self.converse(self.call(1, "studio_find", {}), self.call(2, "studio_create", {"name": "One"}))
        item, one = out[1]["result"]["structuredContent"]["items"][0], out[2]["result"]["structuredContent"]["id"]
        out = self.converse(self.call(3, "studio_move", {"id": item["id"], "to_project_id": one,
                                                         "revision": item["revision"] + 5}))
        self.assertTrue(out[3]["result"]["isError"])
        self.assertIn("refused: alpha changed since you looked", out[3]["result"]["content"][0]["text"])


class ManagementTools(Sources):
    """The management tools (rename, delete, undo, rules, Inbox, accept, purge), each over stdio."""

    converse = McpServer.converse
    call = staticmethod(McpServer.call)

    def sessions(self, *sids):
        rows = {SID_A: agent(SID_A, "alpha work", "/w/proj/alpha"), SID_B: agent(SID_B, "beta work", "/w/proj/beta")}
        self.agents([rows[sid] for sid in sids])
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False).items}

    def ok(self, reply, schemas, name):
        result = reply["result"]
        self.assertNotIn("isError", result, (name, result))
        self.assertEqual(validate(result["structuredContent"], schemas[name]), [], name)
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        return result["structuredContent"]

    def error(self, reply):
        self.assertTrue(reply["result"]["isError"], reply)
        return reply["result"]["content"][0]["text"]

    def test_each_management_tool_returns_schema_valid_output(self):
        alpha, scratch = api.create_project("Alpha"), api.create_project("Scratch")
        a = self.sessions(SID_A, SID_B)[SID_A]
        filed = api.move_item(a.id, alpha.id)
        out = self.converse({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                            self.call(2, "studio_rename", {"project_id": scratch.id, "name": "Scratch pad"}),
                            self.call(3, "studio_rule_save", {"move_id": filed.move_id}),
                            self.call(4, "studio_rules", {"project_id": alpha.id}),
                            self.call(5, "studio_remove", {"item_id": a.id}),
                            self.call(6, "studio_inbox", {"limit": 10}),
                            self.call(7, "studio_accept", {"item_id": a.id}))
        schemas = {t["name"]: t["outputSchema"] for t in out[1]["result"]["tools"]}
        self.assertEqual(self.ok(out[2], schemas, "studio_rename")["name"], "Scratch pad")
        rule = self.ok(out[3], schemas, "studio_rule_save")
        self.assertEqual((rule["project_id"], rule["created"]), (alpha.id, True))
        self.assertEqual([r["id"] for r in self.ok(out[4], schemas, "studio_rules")["rules"]], [rule["id"]])
        inbox = self.ok(out[6], schemas, "studio_inbox")
        entry = next(e for e in inbox["entries"] if e["item"]["id"] == a.id)
        self.assertEqual(entry["suggestion"]["project_id"], alpha.id)
        accepted = self.ok(out[7], schemas, "studio_accept")
        self.assertEqual(accepted["to_project_id"], alpha.id)
        out = self.converse(self.call(8, "studio_undo", {"move_id": accepted["move_id"]}),
                            self.call(9, "studio_rule_delete", {"rule_id": rule["id"]}),
                            self.call(10, "studio_rules", {}),
                            self.call(11, "studio_delete", {"project_id": scratch.id}),
                            self.call(12, "studio_delete", {"project_id": scratch.id, "confirmed": True}),
                            self.call(13, "studio_purge", {"all_gone": True}))
        self.assertEqual(self.ok(out[8], schemas, "studio_undo")["to_project_id"], "inbox")
        self.assertEqual(api.resolve_item(a.id).project_id, "inbox")
        self.assertEqual(self.ok(out[9], schemas, "studio_rule_delete")["id"], rule["id"])
        self.assertEqual(self.ok(out[10], schemas, "studio_rules"), {"rules": [], "total": 0})
        self.assertTrue(self.ok(out[11], schemas, "studio_delete")["needs_confirm"])
        self.assertTrue(self.ok(out[12], schemas, "studio_delete")["deleted"])
        self.assertEqual(self.ok(out[13], schemas, "studio_purge"), {"ids": [], "count": 0})

    def test_delete_says_what_it_would_delete_until_confirmed(self):
        scratch, other = api.create_project("Scratch"), api.create_project("Other")
        api.link_projects(scratch.id, other.id)
        full = api.create_project("Full")
        api.create_project("Inner", parent_id=full.id)
        out = self.converse(self.call(1, "studio_delete", {"project_id": scratch.id}),
                            self.call(2, "studio_delete", {"project_id": scratch.id, "confirmed": False}),
                            self.call(3, "studio_delete", {"project_id": full.id}),
                            self.call(4, "studio_delete", {"project_id": scratch.id, "confirmed": "yes"}),
                            self.call(5, "studio_delete", {"project_id": "inbox", "confirmed": True}))
        preview = out[1]["result"]["structuredContent"]
        self.assertEqual((preview["deleted"], preview["needs_confirm"], preview["links"], preview["rules"]),
                         (False, True, 1, 0))
        self.assertIn("Scratch (%s)" % scratch.id, preview["message"])
        self.assertIn("1 link and 0 rules", preview["message"])
        self.assertEqual(out[2]["result"]["structuredContent"], preview)
        self.assertIn("refused: Can't delete Full: it still holds 1 sub-project", self.error(out[3]))
        self.assertIn("invalid_input: confirmed must be true or false.", self.error(out[4]))
        self.assertIn("refused: The Inbox can't be deleted.", self.error(out[5]))
        self.assertIn(scratch.id, [p.id for p in api.list_projects().projects])   # nothing changed
        self.assertEqual(api.get_project(scratch.id).linked_ids, [other.id])
        out = self.converse(self.call(6, "studio_delete", {"project_id": scratch.id, "confirmed": True}),
                            self.call(7, "studio_delete", {"project_id": full.id, "confirmed": True}))
        done = out[6]["result"]["structuredContent"]
        self.assertEqual((done["deleted"], done["needs_confirm"], done["message"]), (True, False, "Deleted Scratch."))
        self.assertNotIn(scratch.id, [p.id for p in api.list_projects().projects])
        self.assertIn("refused: Can't delete Full", self.error(out[7]))
        self.assertIn(full.id, [p.id for p in api.list_projects().projects])

    def test_purge_without_an_item_needs_all_gone(self):
        self.sessions(SID_A, SID_B)
        found = self.sessions(SID_B)                                   # alpha is gone now
        a, b = found[SID_A], found[SID_B]
        self.assertTrue(a.gone)
        out = self.converse(self.call(1, "studio_purge", {}),
                            self.call(2, "studio_purge", {"all_gone": False}),
                            self.call(3, "studio_purge", {"item_id": a.id, "all_gone": True}),
                            self.call(4, "studio_purge", {"item_id": b.id}))
        for rid in (1, 2):
            self.assertIn("refused: Say which gone item to purge", self.error(out[rid]))
        self.assertIn("invalid_input: Give item_id or all_gone, not both.", self.error(out[3]))
        self.assertIn("refused: beta work is not gone", self.error(out[4]))
        self.assertEqual(api.find_items(include_gone=True, refresh=False).total, 2)   # nothing purged
        out = self.converse(self.call(5, "studio_purge", {"item_id": a.id}),
                            self.call(6, "studio_purge", {"all_gone": True}))
        self.assertEqual(out[5]["result"]["structuredContent"], {"ids": [a.id], "count": 1})
        self.assertEqual(out[6]["result"]["structuredContent"], {"ids": [], "count": 0})
        self.assertEqual([i.id for i in api.find_items(include_gone=True, refresh=False).items], [b.id])

    def test_undo_of_a_move_that_moved_again_is_refused(self):
        alpha, beta = api.create_project("Alpha"), api.create_project("Beta")
        a = self.sessions(SID_A)[SID_A]
        first = api.move_item(a.id, alpha.id)
        api.move_item(a.id, beta.id)
        out = self.converse(self.call(1, "studio_undo", {"move_id": first.move_id}))
        self.assertIn("refused: Can't undo", self.error(out[1]))
        self.assertEqual(api.resolve_item(a.id).project_id, beta.id)
