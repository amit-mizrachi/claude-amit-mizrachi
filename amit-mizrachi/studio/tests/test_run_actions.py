"""Ticket 05: one actions menu for a night run, built from ONE SDK list (`api.run_actions`), the same
on home's run lines and the project view's panels; the CLI's `actions` and the MCP's
`studio_run_actions`. Fixture homes only: nothing here reads or writes ~/.project-studio."""

import json
import os
import subprocess
import sys
import time

from sdk import api
from sdk.errors import NotFound, Refused
from sdk.results import to_dict

from . import PLUGIN
from . import test_mcp_server as mcp_tests
from .support import Sources, validate

SID_A = "11111111-1111-4111-8111-111111111111"     # the live run's ticket session
SID_C = "33333333-3333-4333-8333-333333333333"     # the live run's conductor
BIN = os.path.join(PLUGIN, "bin", "project-studio")
PLAN = "https://claude.ai/artifact/abc"
PR = "https://github.com/me/r/pull/7"


def agent(sid, name, cwd):
    return {"id": sid[:8], "sessionId": sid, "name": name, "cwd": cwd, "state": "working", "kind": "background",
            "startedAt": int(time.time() * 1000) - 120000}


def ids(actions):
    return [a.id for a in actions]


class RunMenu(Sources):
    """In Alpha: a running run with a plan, a PR, a live ticket session and a known conductor; a
    blocked run with none of those; a run waiting on you (CI red) with its conductor known. A loose
    session in the Inbox."""

    def setUp(self):
        super().setUp()
        self.live_ws = self.workspace("live-20261024", tags=(("T01", "DONE"), ("T02", ""), ("T03", None)),
                                      files={"state/ARTIFACT.url": PLAN + "\n", "state/PR.url": PR + "\n",
                                             "state/T02.session": SID_A + "\n",
                                             "state/CONDUCTOR.session": SID_C + "\n"})
        self.stuck_ws = self.workspace("stuck-20261024", tags=(("T01", "DONE"), ("T02", "BLOCKED: tests red")))
        self.wait_ws = self.workspace("wait-20261024", tags=(("T01", "DONE"),),
                                      files={"state/ACCEPTANCE.verdict": "FAIL abc1234 required checks failing\n",
                                             "state/CONDUCTOR.session": SID_C + "\n"})
        self.agents([agent(SID_A, "ns-live-20261024-T02", self.live_ws)])
        self.old(self.transcript(SID_A, self.live_ws, title="ns-live-20261024-T02"))
        self.old(self.transcript(SID_C, self.live_ws))
        self.old(self.transcript("44444444-4444-4444-8444-444444444444", self.mkdir("loose"), kind="interactive",
                                 title="loose work"))
        found = self.items()
        self.alpha = api.create_project("Alpha")
        self.beta = api.create_project("Beta")
        self.live, self.stuck, self.wait = found[self.live_ws], found[self.stuck_ws], found[self.wait_ws]
        self.ticket, self.conductor = found[SID_A], found[SID_C]
        self.session = found["44444444-4444-4444-8444-444444444444"]
        for run in (self.live, self.stuck, self.wait):
            api.move_item(run.id, self.alpha.id)

    def old(self, path):
        then = time.time() - 3600
        os.utime(path, (then, then))
        return path

    def items(self):
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}

    def lines(self):
        card = next(c for c in api.home().cards if c.project.id == self.alpha.id)
        return {r.item_id: r for r in card.runs}

    def panels(self):
        return {r.item_id: r for r in api.project_view(self.alpha.id).runs}


class WhichActionsApply(RunMenu):
    def test_a_live_run_with_a_plan_a_pr_a_ticket_session_and_a_conductor(self):
        menu = api.run_actions(self.live.id)
        self.assertEqual((menu.item_id, menu.title, menu.status, menu.word, menu.project_id, menu.dismissed),
                         (self.live.id, "live-20261024", "running", "Running", self.alpha.id, False))
        self.assertEqual(ids(menu.actions), ["open-plan", "open-pr", "open-terminal", "open-conductor", "move",
                                             "dismiss", "throw-away"])
        by_id = {a.id: a for a in menu.actions}
        self.assertEqual(by_id["open-terminal"].target_id, self.ticket.id)
        self.assertEqual(by_id["open-conductor"].target_id, self.conductor.id)
        for name in ("open-plan", "open-pr", "move", "dismiss", "throw-away"):
            self.assertEqual(by_id[name].target_id, self.live.id, name)
        self.assertEqual([a.label for a in menu.actions], ["Open plan", "Open PR", "Open in Terminal", "Open conductor",
                                                           "Move to...", "Dismiss", "Throw away..."])
        self.assertTrue(all(a.hint for a in menu.actions))

    def test_only_throw_away_is_destructive_and_asks_first(self):
        for run in (self.live, self.stuck, self.wait):
            menu = api.run_actions(run.id).actions
            self.assertEqual([a.id for a in menu if a.destructive], ["throw-away"])
            self.assertEqual([a.id for a in menu if a.needs_confirm], ["throw-away"])
            self.assertEqual(menu[-1].id, "throw-away")

    def test_a_blocked_run_with_nothing_to_open_can_be_marked_done(self):
        self.assertEqual(ids(api.run_actions(self.stuck.id).actions), ["move", "mark-done", "dismiss", "throw-away"])

    def test_a_run_waiting_on_you_offers_its_conductor_and_mark_done(self):
        menu = api.run_actions(self.wait.id)
        self.assertEqual(menu.status, "needs-you")
        self.assertEqual(ids(menu.actions), ["open-conductor", "move", "mark-done", "dismiss", "throw-away"])

    def test_marked_done_it_no_longer_offers_mark_done(self):
        api.mark_done(self.stuck.id)
        self.assertEqual(ids(api.run_actions(self.stuck.id).actions), ["move", "dismiss", "throw-away"])

    def test_a_dismissed_run_offers_restore_instead_of_dismiss(self):
        api.dismiss_item(self.stuck.id)
        menu = api.run_actions(self.stuck.id)
        self.assertTrue(menu.dismissed)
        self.assertEqual(ids(menu.actions), ["move", "mark-done", "restore", "throw-away"])

    def test_a_session_is_refused_and_an_unknown_id_is_not_found(self):
        with self.assertRaises(Refused) as caught:
            api.run_actions(self.session.id)
        self.assertEqual(str(caught.exception), "Only a night run has run actions; loose work is a session.")
        with self.assertRaises(NotFound):
            api.run_actions("i_000000000000")

    def test_asking_changes_nothing(self):
        before = to_dict(api.export_json())
        api.run_actions(self.live.id)
        after = to_dict(api.export_json())
        before.pop("exported_at", None), after.pop("exported_at", None)
        self.assertEqual(before, after)


class HomeAndViewDrawTheSameList(RunMenu):
    def test_home_lines_and_view_panels_carry_run_actions_list(self):
        lines, panels = self.lines(), self.panels()
        for run in (self.live, self.stuck, self.wait):
            want = to_dict(api.run_actions(run.id))["actions"]
            self.assertEqual([to_dict(a) for a in lines[run.id].actions], want, run.title)
            self.assertEqual([to_dict(a) for a in panels[run.id].actions], want, run.title)

    def test_a_waiting_line_on_home_shows_open_conductor_beside_open_plan(self):
        lines = self.lines()
        self.assertEqual(lines[self.wait.id].quick, ["open-conductor"])
        self.assertEqual(lines[self.live.id].quick, [])          # running: its menu only
        self.assertEqual(lines[self.stuck.id].quick, [])

    def test_a_panel_shows_every_action_but_move_as_a_button(self):
        panels = self.panels()
        self.assertEqual(panels[self.live.id].quick, ["open-plan", "open-pr", "open-terminal", "open-conductor",
                                                      "dismiss", "throw-away"])
        self.assertEqual(panels[self.stuck.id].quick, ["mark-done", "dismiss", "throw-away"])

    def test_a_sub_projects_run_panel_carries_its_menu_too(self):
        inner = api.create_project("Inner", self.alpha.id)
        api.move_item(self.stuck.id, inner.id)
        [group] = api.project_view(self.alpha.id).sub_runs
        [panel] = group.runs
        self.assertEqual(ids(panel.actions), ids(api.run_actions(self.stuck.id).actions))
        block = next(c for c in api.home().cards if c.project.id == self.alpha.id).sub_projects[0]
        self.assertEqual(ids(block.runs[0].actions), ids(api.run_actions(self.stuck.id).actions))

    def test_move_to_another_project_takes_the_attached_items_and_undo_puts_it_back(self):
        moved = api.move(self.live.id, self.beta.id)
        self.assertIn(self.ticket.id, moved.followed)
        self.assertEqual(api.run_actions(self.live.id).project_id, self.beta.id)
        self.assertNotIn(self.live.id, self.lines())
        api.undo_move(moved.move_id)
        self.assertEqual(api.run_actions(self.live.id).project_id, self.alpha.id)
        self.assertIn(self.live.id, self.lines())


class ActionsFromTheCli(RunMenu):
    def cli(self, *argv):
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def test_actions_prints_each_action_with_the_command_that_does_it(self):
        code, out, err = self.cli("actions", self.live.id[:8])
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0], "live-20261024  Running  %s" % self.live.id)
        self.assertEqual([line.split()[0] for line in lines[1:]], ["open-plan", "open-pr", "open-terminal",
                                                                   "open-conductor", "move", "dismiss", "throw-away"])
        self.assertIn("project-studio open-item %s --target plan" % self.live.id, out)
        self.assertIn("project-studio terminal %s" % self.ticket.id, out)
        self.assertIn("project-studio terminal %s --conductor" % self.live.id, out)
        self.assertIn("project-studio file %s <project>" % self.live.id, out)
        self.assertIn("project-studio throw %s  (removes things; asks first)" % self.live.id, out)

    def test_json_is_the_sdk_shape(self):
        code, out, _ = self.cli("actions", self.stuck.id, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), json.loads(json.dumps(to_dict(api.run_actions(self.stuck.id)))))

    def test_a_session_is_refused_with_exit_1(self):
        code, out, _ = self.cli("actions", self.session.id, "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["error"]["code"], "refused")

    def test_help_names_the_command(self):
        code, out, _ = self.cli("help")
        self.assertEqual(code, 0)
        self.assertIn("actions", out)
        code, out, _ = self.cli("help", "actions")
        self.assertEqual(code, 0)
        self.assertIn("project-studio actions i_1a2b3c4d", out)


class ActionsOverMcp(RunMenu):
    converse = mcp_tests.McpServer.converse
    call = staticmethod(mcp_tests.McpServer.call)

    def test_the_tool_is_read_only_and_returns_schema_valid_actions(self):
        tools = {t["name"]: t for t in mcp_tests.mcp_server.TOOLS}
        tool = tools["studio_run_actions"]
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertFalse(tool["annotations"]["destructiveHint"])
        self.assertFalse(tool["inputSchema"]["additionalProperties"])
        out = self.converse(self.call(1, "studio_run_actions", {"item_id": self.live.id}),
                            self.call(2, "studio_run_actions", {"item_id": self.session.id}),
                            self.call(3, "studio_run_actions", {"item_id": self.live.id, "extra": 1}))
        result = out[1]["result"]
        self.assertNotIn("isError", result)
        self.assertEqual(validate(result["structuredContent"], tool["outputSchema"]), [])
        self.assertEqual([a["id"] for a in result["structuredContent"]["actions"]],
                         ids(api.run_actions(self.live.id).actions))
        self.assertTrue(out[2]["result"]["isError"])
        self.assertIn("unknown argument(s): extra", out[3]["result"]["content"][0]["text"])
