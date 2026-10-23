"""The project-studio CLI, driven as a subprocess like a person at a terminal.

`open`, `pbcopy` and `claude` are stubbed on PATH (tests/stubs): nothing opens on this Mac.
"""

import json
import os
import pty
import subprocess
import sys
import time

from sdk import api
from sdk.results import to_dict

from . import PLUGIN
from .support import Sources
from .test_readers import SID_A, SID_B, agent

BIN = os.path.join(PLUGIN, "bin", "project-studio")


class Cli(Sources):
    def run_cli(self, *argv, stdin=subprocess.DEVNULL):
        """(exit code, stdout, stderr); the environment is TempHome's, so the store is the temp one.
        stdin is not a tty unless a test passes one."""
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=stdin, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def ok(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        return out

    def json_ok(self, *argv):
        return json.loads(self.ok(*argv))

    def tree(self):
        self.alpha, self.beta = api.create_project("Alpha"), api.create_project("Beta")
        self.docs_a = api.create_project("Docs", parent_id=self.alpha.id)
        self.docs_b = api.create_project("Docs", parent_id=self.beta.id)

    def sessions(self):
        self.agents([agent(SID_A, "alpha work", "/w/proj/alpha"), agent(SID_B, "beta work", "/w/proj/beta")])
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(refresh=False).items}

    # ------------------------------------------------------------ list

    def test_list_prints_the_tree_with_short_ids_and_run_lines(self):
        self.tree()
        lines = self.ok("list").splitlines()
        self.assertEqual(lines[0].split(), ["inbox", "Inbox", "0", "items"])
        self.assertTrue(lines[1].startswith(self.alpha.id[:8] + "  Alpha"), lines)
        self.assertIn("    Docs", lines[2])                       # nested under Alpha
        self.assertTrue(lines[1].endswith("no runs"), lines)

    def test_list_json_is_the_sdk_shape_with_run_lines(self):
        self.tree()
        api.archive_project(self.beta.id)
        out = self.json_ok("list", "--json")
        self.assertEqual(out, json.loads(json.dumps(to_dict(api.list_projects(with_runs=True)))))
        self.assertNotIn(self.beta.id, [p["id"] for p in out["projects"]])
        self.assertEqual(out["run_lines"][self.alpha.id], "no runs")
        self.assertNotIn("inbox", out["run_lines"])
        everything = self.json_ok("--json", "list", "--all")       # --json before the command works too
        self.assertIn(self.beta.id, [p["id"] for p in everything["projects"]])
        self.assertIn("(archived)", self.ok("list", "--all"))

    def test_list_shows_a_night_run_and_a_limit_footer(self):
        self.tree()
        self.workspace("sprint-one")
        api.refresh(force=True)
        run = api.find_items(kind="night-sprint", refresh=False).items[0]
        api.move_item(run.id, self.alpha.id)
        alpha_line = [l for l in self.ok("list").splitlines() if "Alpha" in l][0]
        self.assertIn("1 run", alpha_line)
        self.assertNotIn("no runs", alpha_line)
        self.assertIn("(2 of 5 shown - raise --limit for more)", self.ok("list", "--limit", "2"))

    # ------------------------------------------------------------ show and status

    def test_show_by_name_prefix_and_id_in_text_and_json(self):
        self.tree()
        text = self.ok("show", "alpha")
        self.assertTrue(text.startswith("Alpha  %s" % self.alpha.id), text)
        self.assertIn("Inside", text)
        self.assertIn("Docs", text)
        self.assertEqual(self.ok("show", self.alpha.id[:8]), text)
        self.assertEqual(self.ok("show", self.alpha.id[2:8]), text)    # the p_ may be left out
        view = self.json_ok("show", self.alpha.id, "--json")
        self.assertEqual(view["project"]["id"], self.alpha.id)
        self.assertEqual([t["name"] for t in view["inside"]], ["Docs"])
        self.assertIn("Nothing filed here yet.", self.ok("show", "inbox"))

    def test_show_lists_a_filed_session(self):
        self.tree()
        a = self.sessions()[SID_A]
        api.move_item(a.id, self.alpha.id)
        text = self.ok("show", "Alpha")
        self.assertIn("Sessions", text)
        self.assertIn("alpha work", text)
        self.assertIn(a.id[:8], text)

    def test_status_without_a_project_is_the_server_and_with_one_is_the_project(self):
        self.tree()
        self.assertEqual(self.ok("status"), "Project Studio is not running.\n")
        self.assertFalse(self.json_ok("status", "--json")["running"])
        self.assertEqual(self.ok("stop"), "Project Studio is not running.\n")
        text = self.ok("status", "Alpha", "--no-refresh")
        self.assertTrue(text.startswith("Alpha  %s" % self.alpha.id), text)
        self.assertIn("0 runs, 0 active", text)
        status = self.json_ok("--json", "status", "alpha")
        self.assertEqual(status["project"]["id"], self.alpha.id)
        self.assertEqual(status["sub_projects"][0]["project"]["id"], self.docs_a.id)
        self.assertIn("No runs or items here yet.", self.ok("status", "Inbox"))

    def test_status_lists_inbox_sessions(self):
        self.sessions()
        text = self.ok("status", "inbox", "--no-refresh")
        self.assertIn("Sessions", text)
        self.assertIn("alpha work", text)
        self.assertIn("beta work", text)

    # ------------------------------------------------------------ find, inbox, refresh, rules

    def test_find_in_text_and_json(self):
        self.tree()
        by_key = self.sessions()
        api.move_item(by_key[SID_A].id, self.alpha.id)
        lines = self.ok("find", "--no-refresh").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(any(l.startswith(by_key[SID_A].id[:8]) and "Alpha" in l for l in lines), lines)
        found = self.json_ok("find", "ALPHA", "--json", "--no-refresh")
        self.assertEqual([i["id"] for i in found["items"]], [by_key[SID_A].id])
        in_alpha = self.json_ok("find", "--project", "alpha", "--json", "--no-refresh")
        self.assertEqual([i["id"] for i in in_alpha["items"]], [by_key[SID_A].id])
        self.assertEqual(self.ok("find", "nothing-like-this", "--no-refresh"), "No items match.\n")
        self.assertIn("(1 of 2 shown", self.ok("find", "--limit", "1", "--no-refresh"))

    def test_inbox_in_text_and_json(self):
        self.assertEqual(self.ok("inbox", "--no-refresh"), "The Inbox is empty.\n")
        by_key = self.sessions()
        text = self.ok("inbox", "--no-refresh")
        self.assertIn(by_key[SID_A].id[:8], text)
        self.assertIn("beta work", text)
        out = self.json_ok("inbox", "--json", "--no-refresh")
        self.assertEqual(out["total"], 2)
        self.assertEqual(sorted(e["item"]["id"] for e in out["entries"]), sorted(i.id for i in by_key.values()))

    def test_refresh_says_what_changed(self):
        self.agents([agent(SID_A, "alpha work", "/w/proj/alpha")])
        text = self.ok("refresh", "--force")
        self.assertIn("1 added", text)
        self.assertIn("Every source read fine.", text)
        out = self.json_ok("refresh", "--force", "--json")
        self.assertEqual(out["added"], 0)
        self.assertTrue(all(s["ok"] for s in out["sources"]))

    def test_refresh_names_a_failed_source(self):
        self.agents_fail()
        text = self.ok("refresh", "--force")
        self.assertIn("Failed sources", text)
        self.assertIn("agents", text)

    def test_rules_empty_and_one_project(self):
        self.tree()
        self.assertEqual(self.ok("rules"), "No rules yet.\n")
        self.assertEqual(self.json_ok("rules", "--project", "alpha", "--json")["rules"], [])

    # ------------------------------------------------------------ help, errors and exit codes

    def test_help_lists_every_command_and_one_command_help(self):
        text = self.ok("help")
        for name in ("open", "stop", "status", "list", "show", "find", "inbox", "refresh", "rules", "help"):
            self.assertIn(name, text)
        self.assertIn("Exit codes", text)
        self.assertIn("--refresh", self.ok("help", "show"))
        self.assertIn("--refresh", self.ok("show", "--help"))
        self.assertIn("usage: project-studio", self.ok("--help"))

    def test_usage_errors_exit_2(self):
        for argv in (["list", "--limit", "abc"], ["nonsense"], ["show"], ["find", "--kind", "bogus"],
                     ["help", "bogus"]):
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertEqual(out, "")
            self.assertIn("usage:", err)

    def test_an_unknown_project_exits_1_with_a_coded_error(self):
        code, out, err = self.run_cli("show", "nope")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("project-studio: not_found: "), err)
        code, out, err = self.run_cli("show", "nope", "--json")
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(json.loads(out)["error"]["code"], "not_found")
        code, _, err = self.run_cli("find", "--project", "nope")
        self.assertEqual(code, 1)
        self.assertIn("not_found", err)

    def test_an_ambiguous_name_exits_1_and_lists_the_candidates(self):
        self.tree()
        code, out, err = self.run_cli("status", "docs")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("project-studio: ambiguous: "), err)
        for p in (self.docs_a, self.docs_b):
            self.assertIn(p.id, err)
        self.assertIn("(in Alpha)", err)
        code, out, _ = self.run_cli("--json", "show", "docs")
        self.assertEqual(code, 1)
        error = json.loads(out)["error"]
        self.assertEqual(error["code"], "ambiguous")
        self.assertEqual(sorted(c["id"] for c in error["candidates"]), sorted([self.docs_a.id, self.docs_b.id]))
        self.assertEqual(self.json_ok("show", self.docs_b.id[:8], "--json")["project"]["id"], self.docs_b.id)

    def test_invalid_input_from_the_sdk_exits_1(self):
        code, _, err = self.run_cli("list", "--limit", "0")
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("project-studio: invalid_input: "), err)


class ChangeCommands(Cli):
    def calls(self):
        path = os.path.join(self.stub, "calls")
        if not os.path.exists(path):
            return []
        with open(path) as fh:
            return fh.read().splitlines()

    def move_id(self, out):
        """The move id from a move's text: "Move 3. Undo: project-studio undo 3"."""
        line = [l for l in out.splitlines() if l.startswith("Move ")][0]
        self.assertTrue(line.endswith("Undo: project-studio undo %s" % line.split()[1].rstrip(".")), line)
        return int(line.split()[1].rstrip("."))

    # ------------------------------------------------------------ projects

    def test_create_rename_archive_in_text_and_json(self):
        self.assertTrue(self.ok("create", "Alpha").startswith("Created Alpha  p_"))
        made = self.json_ok("create", "Docs", "--under", "alpha", "--json")
        self.assertEqual(made["path"], ["Alpha", "Docs"])
        self.assertEqual(self.ok("rename", made["id"][:8], "Docs site"),
                         "Renamed to Alpha / Docs site  %s\n" % made["id"])
        self.assertEqual(self.json_ok("--json", "rename", "docs site", "Docs")["name"], "Docs")
        self.assertTrue(self.ok("archive", "Docs").startswith("Archived Alpha / Docs"))
        self.assertIsNotNone(self.json_ok("archive", made["id"], "--json")["archived_at"])
        code, _, err = self.run_cli("create", "alpha")                 # a sibling has the name
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("project-studio: "), err)

    def test_delete_without_yes_refuses_with_exit_2_and_says_what(self):
        scratch = api.create_project("Scratch")
        code, out, err = self.run_cli("delete", "scratch")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("project-studio: confirm_needed: "), err)
        self.assertIn("Scratch (%s)" % scratch.id, err)
        self.assertIn("--yes", err)
        code, out, err = self.run_cli("delete", "scratch", "--json")
        self.assertEqual((code, err), (2, ""))
        self.assertEqual(json.loads(out)["error"]["code"], "confirm_needed")
        self.assertIn(scratch.id, [p.id for p in api.list_projects().projects])
        self.assertEqual(self.ok("delete", "scratch", "--yes"), "Deleted Scratch  %s\n" % scratch.id)
        self.assertNotIn(scratch.id, [p.id for p in api.list_projects().projects])
        other = api.create_project("Other")
        self.assertEqual(self.json_ok("--json", "delete", other.id, "--yes"), {"id": other.id, "name": "Other"})

    def test_nest_prints_the_move_id_and_undo_puts_it_back(self):
        self.tree()
        out = self.ok("nest", "Alpha", "--under", "Beta")
        self.assertIn("Moved to Beta", out)
        self.assertEqual(api.resolve_project("Alpha").path, ["Beta", "Alpha"])
        self.assertIn("Moved back to the top level", self.ok("undo", str(self.move_id(out))))
        self.assertEqual(api.resolve_project("Alpha").path, ["Alpha"])
        moved = self.json_ok("nest", self.docs_a.id, "--top", "--json")
        self.assertIsNone(moved["to_project_id"])
        self.assertIsInstance(moved["move_id"], int)
        code, _, err = self.run_cli("nest", "Alpha")                   # --under or --top is required
        self.assertEqual(code, 2)
        self.assertIn("usage:", err)

    def test_link_twice_says_already_linked(self):
        self.tree()
        lo, hi = sorted((self.alpha.id, self.beta.id))
        self.assertEqual(self.ok("link", "alpha", "beta"), "Linked %s and %s.\n" % (lo, hi))
        self.assertEqual(self.json_ok("link", "beta", "alpha", "--json"), {"a_id": lo, "b_id": hi, "created": False})

    # ------------------------------------------------------------ items and moves

    def test_file_prints_the_move_id_and_undo_reverses_it(self):
        self.tree()
        a = self.sessions()[SID_A]
        out = self.ok("file", a.id[:8], "alpha")
        self.assertTrue(out.startswith("Moved to Alpha"), out)
        self.assertIn("project-studio rule-save %d" % self.move_id(out), out)
        self.assertEqual(api.resolve_item(a.id).project_id, self.alpha.id)
        self.assertIn("Moved back to Inbox", self.ok("undo", str(self.move_id(out))))
        self.assertEqual(api.resolve_item(a.id).project_id, "inbox")
        moved = self.json_ok("--json", "file", a.id, "beta")
        self.assertEqual((moved["to_project_id"], moved["item"]["id"]), (self.beta.id, a.id))
        undone = self.json_ok("undo", str(moved["move_id"]), "--json")
        self.assertEqual(undone["to_project_id"], "inbox")
        code, _, err = self.run_cli("undo", str(moved["move_id"]))    # moved again since: refused
        self.assertEqual(code, 1)
        self.assertIn("project-studio: refused: Can't undo", err)
        code, _, err = self.run_cli("file", a.id, "beta", "--revision", "1")
        self.assertEqual(code, 1)
        self.assertIn("project-studio: ", err)

    def test_add_a_new_item_names_remove_and_add_of_a_known_one_is_a_move(self):
        self.tree()
        out = self.ok("add", "artifact", "https://claude.ai/artifact/abc", "alpha", "--title", "The plan")
        self.assertTrue(out.startswith("Added The plan to Alpha  i_"), out)
        item_id = out.split()[5]
        self.assertIn("project-studio remove %s" % item_id, out)
        again = self.ok("add", "artifact", "https://claude.ai/artifact/abc", "beta")
        self.assertIn("Moved to Beta", again)
        self.move_id(again)
        added = self.json_ok("--json", "add", "pr", "acme/app#7", "beta")
        self.assertTrue(added["created"])
        self.assertEqual(added["item"]["project_id"], self.beta.id)

    def test_remove_accept_rule_save_rules_and_rule_delete(self):
        self.tree()
        a = self.sessions()[SID_A]
        filed = self.json_ok("file", a.id, "alpha", "--json")
        saved = self.ok("rule-save", str(filed["move_id"]))
        self.assertTrue(saved.startswith("Saved rule r_"), saved)
        self.assertIn("-> Alpha", saved)
        rule_id = saved.split()[2].rstrip(":")
        self.assertFalse(self.json_ok("rule-save", str(filed["move_id"]), "--json")["created"])
        self.assertIn("Already saved rule %s" % rule_id, self.ok("rule-save", str(filed["move_id"])))
        removed = self.ok("remove", a.id)
        self.assertIn("Moved to Inbox", removed)
        self.move_id(removed)
        accepted = self.ok("accept", a.id[:8])                        # the rule suggests Alpha
        self.assertIn("Moved to Alpha", accepted)
        self.move_id(accepted)
        api.remove_item(a.id)
        self.assertEqual(self.json_ok("--json", "accept", a.id)["to_project_id"], self.alpha.id)
        self.assertEqual(self.json_ok("--json", "remove", a.id)["to_project_id"], "inbox")
        self.assertEqual([r["id"] for r in self.json_ok("rules", "--json")["rules"]], [rule_id])
        self.assertTrue(self.ok("rule-delete", rule_id).startswith("Deleted rule %s" % rule_id))
        self.assertEqual(self.ok("rules"), "No rules yet.\n")
        code, out, _ = self.run_cli("--json", "rule-delete", rule_id)
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(out))
        code, _, err = self.run_cli("accept", self.sessions()[SID_B].id)   # no suggestion for it
        self.assertEqual(code, 1)
        self.assertIn("project-studio: refused: ", err)

    def test_export_prints_or_writes_the_store_and_purge_counts(self):
        self.tree()
        document = json.loads(self.ok("export"))
        self.assertEqual(document["format"], "project-studio-export")
        dest = os.path.join(self.tmp, "out", "studio.json")
        os.makedirs(os.path.dirname(dest))
        self.assertEqual(self.ok("export", dest), "Wrote the store to %s\n" % dest)
        with open(dest) as fh:
            self.assertEqual(json.load(fh)["format"], "project-studio-export")
        self.assertEqual(self.json_ok("export", "--json")["path"], None)
        self.assertEqual(self.ok("purge"), "Purged 0 gone items.\n")
        self.assertEqual(self.json_ok("--json", "purge"), {"count": 0, "ids": []})
        a = self.sessions()[SID_A]
        code, _, err = self.run_cli("purge", a.id)                     # not gone: refused
        self.assertEqual(code, 1)
        self.assertIn("project-studio: ", err)

    # ------------------------------------------------------------ terminal, command, open-item

    def session_to_open(self, fresh=False):
        path = self.transcript(SID_B, self.mkdir("work"), kind="interactive", title="Plan it")
        then = time.time() - (0 if fresh else 3600)
        os.utime(path, (then, then))
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(refresh=False).items}[SID_B]

    def test_command_prints_only_the_command(self):
        item = self.session_to_open()
        out = self.ok("command", item.id[:8])
        self.assertEqual(out, api.terminal_command(item.id).command + "\n")
        self.assertEqual(len(out.splitlines()), 1)
        self.assertEqual(self.json_ok("command", item.id, "--json")["mode"], "resume")
        self.assertEqual([c for c in self.calls() if c.startswith("open ")], [])

    def test_terminal_opens_with_the_open_stub(self):
        item = self.session_to_open()
        out = self.ok("terminal", item.id)
        self.assertEqual(out.splitlines(), ["Opened in Terminal:", api.terminal_command(item.id).command])
        command_file = os.path.join(self.home, "open", item.id + ".command")
        self.assertIn("open %s" % command_file, self.calls())
        self.assertTrue(self.json_ok("--json", "terminal", item.id)["opened"])

    def test_terminal_without_a_tty_or_yes_refuses_when_it_needs_confirming(self):
        item = self.session_to_open(fresh=True)
        code, out, err = self.run_cli("terminal", item.id)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("project-studio: confirm_needed: "), err)
        self.assertIn("--yes", err)
        code, out, _ = self.run_cli("--json", "terminal", item.id)
        self.assertEqual((code, json.loads(out)["error"]["code"]), (2, "confirm_needed"))
        self.assertEqual([c for c in self.calls() if c.startswith("open ")], [])
        self.assertIn("Opened in Terminal:", self.ok("terminal", item.id, "--yes"))
        self.assertEqual(len([c for c in self.calls() if c.startswith("open ")]), 1)

    def test_terminal_on_a_tty_asks_and_opens_only_on_y(self):
        item = self.session_to_open(fresh=True)
        for answer, code, opens in ((b"n\n", 2, 0), (b"y\n", 0, 1)):
            master, slave = pty.openpty()
            self.addCleanup(os.close, master)
            os.write(master, answer)
            got, _, err = self.run_cli("terminal", item.id, stdin=slave)
            os.close(slave)
            self.assertEqual(got, code, err)
            self.assertIn("[y/N]", err)
            self.assertEqual(len([c for c in self.calls() if c.startswith("open ")]), opens)

    def test_open_item_opens_a_url_with_the_open_stub(self):
        self.tree()
        api.add_item("artifact", "https://claude.ai/artifact/abc", self.alpha.id)
        item = api.find_items(kind="artifact", refresh=False).items[0]
        self.assertEqual(self.ok("open-item", item.id[:8]), "Opened https://claude.ai/artifact/abc\n")
        self.assertEqual(self.calls()[-1], "open https://claude.ai/artifact/abc")
        opened = self.json_ok("--json", "open-item", item.id)
        self.assertEqual((opened["how"], opened["opened"]), ("url", True))
        code, _, err = self.run_cli("open-item", item.id, "--target", "plan")
        self.assertEqual(code, 1)
        self.assertIn("project-studio: ", err)

    def test_help_lists_every_change_command(self):
        text = self.ok("help")
        for name in ("create", "rename", "archive", "delete", "nest", "link", "add", "file", "undo", "remove",
                     "accept", "rule-save", "rule-delete", "export", "purge", "terminal", "command", "open-item"):
            self.assertIn("  %s " % name, text)
        self.assertIn("missing --yes", text)
