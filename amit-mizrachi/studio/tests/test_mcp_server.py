"""The project-studio MCP server, driven over stdin/stdout JSON-RPC like a real client."""

import json
import os
import subprocess
import sys

from . import STUDIO
from .support import Sources, TempHome, validate
from .test_readers import SID_A, agent

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
        tools = {t["name"]: t for t in out[2]["result"]["tools"]}
        self.assertEqual(set(tools), {"studio_list", "studio_create", "studio_find", "studio_status", "studio_add",
                                      "studio_move", "studio_link", "studio_remove", "studio_archive",
                                      "studio_open"})
        for tool in tools.values():
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertEqual(tool["outputSchema"]["type"], "object")
            for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                self.assertIn(hint, tool["annotations"])
        self.assertTrue(tools["studio_list"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["studio_create"]["annotations"]["readOnlyHint"])
        self.assertEqual(tools["studio_create"]["inputSchema"]["required"], ["name"])
        self.assertLessEqual(tools["studio_list"]["inputSchema"]["properties"]["limit"]["maximum"], 200)

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

    def test_a_stale_revision_is_a_tool_error_with_the_sdk_message(self):
        self.agents([agent(SID_A, "alpha", "/w/alpha")])
        out = self.converse(self.call(1, "studio_find", {}), self.call(2, "studio_create", {"name": "One"}))
        item, one = out[1]["result"]["structuredContent"]["items"][0], out[2]["result"]["structuredContent"]["id"]
        out = self.converse(self.call(3, "studio_move", {"id": item["id"], "to_project_id": one,
                                                         "revision": item["revision"] + 5}))
        self.assertTrue(out[3]["result"]["isError"])
        self.assertIn("refused: alpha changed since you looked", out[3]["result"]["content"][0]["text"])
