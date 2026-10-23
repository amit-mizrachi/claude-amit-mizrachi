"""The project-studio MCP server, driven over stdin/stdout JSON-RPC like a real client."""

import json
import os
import subprocess
import sys

from . import STUDIO
from .support import TempHome

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
        self.assertEqual(set(tools), {"studio_list", "studio_create"})
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
