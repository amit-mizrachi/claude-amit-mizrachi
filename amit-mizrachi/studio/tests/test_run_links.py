"""Sprint 3 ticket 02: every night run line shows its links (its PR, Open plan, Open conductor), drawn
from the same `run_actions` list as its menu, on home, in the project view, in `status` and over the
MCP; a project's PR line is a link per PR. Fixture homes only: nothing here reads ~/.project-studio."""

import json
import os
import re
import subprocess
import sys

from sdk import api, runmenu
from sdk.results import to_dict

from . import PLUGIN
from . import test_mcp_server as mcp_tests
from .support import Sources, validate

SID_C = "33333333-3333-4333-8333-333333333333"     # the conductor of the PR run and the waiting run
BIN = os.path.join(PLUGIN, "bin", "project-studio")
PLAN = "https://claude.ai/artifact/abc"
PR_A = "https://github.com/me/r/pull/733"
PR_B = "https://github.com/me/r/pull/738"
DONE2 = (("T01", "DONE"), ("T02", "DONE"))
GREEN = [{"status": "COMPLETED", "conclusion": "SUCCESS"}]
RUNNING = [{"status": "IN_PROGRESS", "conclusion": ""}]


def pr_row(number, branch, checks):
    return {"number": number, "title": branch, "headRefName": branch, "state": "OPEN", "isDraft": False,
            "url": "https://github.com/me/r/pull/%d" % number, "updatedAt": "2026-10-24T00:00:00Z",
            "statusCheckRollup": checks}


class RunLinks(Sources):
    """In Alpha: a finished run with PR #733 (checks green), a plan and a known conductor; a second
    finished run with PR #738 (checks running); a blocked run with nothing to open; a run waiting on
    you (a gate) with a plan and its conductor."""

    def setUp(self):
        super().setUp()
        repo, _ = self.git_repo("r", [])
        facts = {"REPO_PATH": repo, "REPO_SLUG": "me/r"}
        self.pr_ws = self.workspace("withpr-20261024", facts=dict(facts, BRANCH="feat/a"), tags=DONE2,
                                    files={"state/ARTIFACT.url": PLAN + "\n", "state/CONDUCTOR.session": SID_C + "\n"})
        self.two_ws = self.workspace("second-20261024", facts=dict(facts, BRANCH="feat/b"), tags=DONE2)
        self.stuck_ws = self.workspace("stuck-20261024", tags=(("T01", "DONE"), ("T02", "BLOCKED: tests red")))
        self.wait_ws = self.workspace("wait-20261024", tags=(("T01", "DONE"),),
                                      files={"state/T01.waiting-on-user": "plan gate\n",
                                             "state/ARTIFACT.url": PLAN + "/w\n",
                                             "state/CONDUCTOR.session": SID_C + "\n"})
        self.prs("me/r", [pr_row(733, "feat/a", GREEN), pr_row(738, "feat/b", RUNNING)])
        self.transcript(SID_C, self.pr_ws)
        api.refresh(force=True)
        found = {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}
        self.alpha = api.create_project("Alpha")
        self.run, self.two, self.stuck, self.wait = (found[w] for w in (self.pr_ws, self.two_ws, self.stuck_ws,
                                                                         self.wait_ws))
        for run in (self.run, self.two, self.stuck, self.wait):
            api.move_item(run.id, self.alpha.id)

    def card(self):
        return next(c for c in api.home().cards if c.project.id == self.alpha.id)

    def surfaces(self, item_id):
        """The run as a home line, a project view panel and a `status` Run."""
        line = next(r for r in self.card().runs if r.item_id == item_id)
        panel = next(r for r in api.project_view(self.alpha.id).runs if r.item_id == item_id)
        run = next(r for r in api.project_status(self.alpha.id, refresh=False).runs if r.item_id == item_id)
        return {"home": line, "view": panel, "status": run}


class EveryRunCarriesItsLinks(RunLinks):
    def test_a_run_with_a_pr_carries_its_url_number_state_and_pr_link(self):
        for where, run in self.surfaces(self.run.id).items():
            self.assertEqual((run.pr_url, run.pr_number, run.pr_state), (PR_A, 733, "open"), where)
            self.assertEqual([link.id for link in run.links], ["open-pr", "open-plan", "open-conductor"], where)
            pr = run.links[0]
            self.assertEqual((pr.label, pr.hint, pr.url, pr.target_id, pr.primary),
                             ("#733", "PR #733 open - checks green", PR_A, self.run.id, False), where)
            self.assertFalse(any(link.primary for link in run.links), where)    # In review: every link quiet

    def test_a_run_without_a_pr_has_no_pr_fields_and_no_links(self):
        for where, run in self.surfaces(self.stuck.id).items():
            self.assertEqual((run.pr_url, run.pr_number, run.pr_state, run.links), ("", None, "", []), where)

    def test_a_run_waiting_on_you_draws_its_open_plan_filled(self):
        for where, run in self.surfaces(self.wait.id).items():
            self.assertEqual([(link.id, link.primary) for link in run.links],
                             [("open-plan", True), ("open-conductor", False)], where)
            conductor = run.links[1]
            self.assertEqual(conductor.target_id, run.conductor_item_id, where)

    def test_links_are_the_menus_open_actions_on_every_surface(self):
        for item in (self.run, self.two, self.stuck, self.wait):
            menu = {a.id: a for a in api.run_actions(item.id).actions}
            want = [(i, menu[i].target_id) for i in runmenu.LINKS if i in menu]
            for where, run in self.surfaces(item.id).items():
                self.assertEqual([(link.id, link.target_id) for link in run.links], want, (item.title, where))

    def test_a_home_line_and_a_panel_draw_no_link_twice(self):
        for where, run in self.surfaces(self.run.id).items():
            if where != "status":
                self.assertFalse(set(run.quick) & set(runmenu.LINKS), where)
        self.assertEqual(self.surfaces(self.wait.id)["home"].quick, [])


class TheProjectPrLine(RunLinks):
    def test_a_project_with_two_prs_lists_each_as_a_link(self):
        card = self.card()
        self.assertEqual(sorted((link.label, link.url, link.target_id) for link in card.prs),
                         [("PR #733 open - checks green", PR_A, self.run.id),
                          ("PR #738 open - checks running", PR_B, self.two.id)])
        self.assertEqual({link.id for link in card.prs}, {"open-pr"})
        self.assertEqual(card.pr, card.prs[0].label)

    def test_a_project_with_no_pr_has_an_empty_pr_line(self):
        api.dismiss_item(self.run.id)
        api.dismiss_item(self.two.id)
        card = self.card()
        self.assertEqual((card.pr, card.prs), ("", []))


class TheCliAndTheMcp(RunLinks):
    def cli(self, *argv):
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def test_status_and_show_print_each_runs_pr_url(self):
        for command in ("status", "show"):
            code, out, err = self.cli(command, self.alpha.id)
            self.assertEqual((code, err), (0, ""), command)
            line = next(row for row in out.splitlines() if "withpr-20261024" in row)
            self.assertTrue(line.rstrip().endswith(PR_A), (command, line))

    def test_status_json_has_the_pr_fields_and_links(self):
        code, out, _ = self.cli("status", self.alpha.id, "--json")
        self.assertEqual(code, 0)
        run = next(r for r in json.loads(out)["runs"] if r["item_id"] == self.run.id)
        self.assertEqual((run["pr_url"], run["pr_number"], run["pr_state"]), (PR_A, 733, "open"))
        self.assertEqual([link["id"] for link in run["links"]], ["open-pr", "open-plan", "open-conductor"])

    converse = mcp_tests.McpServer.converse
    call = staticmethod(mcp_tests.McpServer.call)

    def test_studio_status_returns_schema_valid_links(self):
        tool = next(t for t in mcp_tests.mcp_server.TOOLS if t["name"] == "studio_status")
        out = self.converse(self.call(1, "studio_status", {"project_id": self.alpha.id}))
        result = out[1]["result"]
        self.assertNotIn("isError", result)
        self.assertEqual(validate(result["structuredContent"], tool["outputSchema"]), [])
        run = next(r for r in result["structuredContent"]["runs"] if r["item_id"] == self.run.id)
        self.assertEqual(run["pr_url"], PR_A)
        self.assertEqual(run["links"][0], to_dict(self.surfaces(self.run.id)["status"].links[0]))


class ThePageDrawsTheLinks(RunLinks):
    def script(self):
        with open(os.path.join(PLUGIN, "studio", "static", "app.js")) as fh:
            return fh.read()

    def body(self, signature):
        return re.search(r"function %s \{(.*?)\n  \}\n" % re.escape(signature), self.script(), re.S).group(1)

    def test_run_lines_and_panels_draw_links_and_the_row_its_pr_links(self):
        self.assertIn("runLinks(run, acts);", self.body("runLine(run, from)"))
        self.assertIn("runLinks(r, acts);", self.body("runPanel(r, from)"))
        self.assertIn("prLinks(c.prs)", self.body("card(c)"))
        self.assertNotIn("open_plan_url", self.script())

    def test_a_run_name_wraps_instead_of_being_cut(self):
        with open(os.path.join(PLUGIN, "studio", "static", "app.css")) as fh:
            css = fh.read()
        rule = re.search(r"\.run \.nm\{([^}]*)\}", css).group(1)
        self.assertNotIn("ellipsis", rule)
        self.assertIn("overflow-wrap:anywhere", rule)
