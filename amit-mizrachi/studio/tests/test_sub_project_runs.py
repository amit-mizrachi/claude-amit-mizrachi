"""Ticket 03 (sprint project-studio-manage2): a sub-project's night runs show from its parent.

The project view, `status` and `show` group the rolled-up runs by active sub-project, in tree
order at every depth: a header (glyph, word, counts in words, whether it starts open) and its own
runs, at most 5 before "+ n more". Archived sub-projects are left out. The counts wording
("2 blocked, 1 running, 4 done") is one helper, used by home, the view, `list`, `show` and `status`.
"""

import json
import subprocess
import sys

from sdk import api
from sdk.results import Run
from sdk.runwords import run_counts_text

from .support import Sources
from .test_cli import BIN

DONE2 = (("T01", "DONE"), ("T02", "DONE"))
BLOCKED = (("T01", "DONE"), ("T02", "BLOCKED: tests red"))
LIVE = (("T01", "DONE"), ("T02", ""))


def run(status, gone=False):
    return Run(item_id="i_x", kind="night-sprint", title="x", project_id="p_x", status=status, reason="",
               progress=None, stage="", stages=[], pr=None, artifact_url="", started_at="", updated_at="", gone=gone)


class CountsInWords(Sources):
    def test_one_count_per_status_most_urgent_first(self):
        runs = [run("done"), run("blocked"), run("running"), run("done"), run("blocked"), run("done"), run("done")]
        self.assertEqual(run_counts_text(runs), "2 blocked, 1 running, 4 done")
        self.assertEqual(run_counts_text([run("needs-you"), run("paused")]), "1 waiting on you, 1 paused")
        self.assertEqual(run_counts_text([run("running", gone=True), run("done")]), "1 done, 1 gone")
        self.assertEqual(run_counts_text([]), "no runs")


class ParentWithSubs(Sources):
    """Shapes-agent to Machina with two sub-projects: Machina decision units (a blocked run, a done
    run, and Inner below it with a running run) and Per-domain evals (6 done runs). The parent has
    a done run of its own; an archived sub-project holds one more."""

    def setUp(self):
        super().setUp()
        self.parent = api.create_project("Shapes-agent to Machina")
        self.units = api.create_project("Machina decision units", parent_id=self.parent.id)
        self.evals = api.create_project("Per-domain evals", parent_id=self.parent.id)
        self.inner = api.create_project("Inner", parent_id=self.units.id)
        self.old = api.create_project("Old", parent_id=self.parent.id)
        spaces = {"own-1": (DONE2, self.parent), "stuck-1": (BLOCKED, self.units), "units-done": (DONE2, self.units),
                  "live-1": (LIVE, self.inner), "archived-1": (DONE2, self.old)}
        spaces.update({"evals-%d" % n: (DONE2, self.evals) for n in range(6)})
        paths = {slug: self.workspace(slug, tags=tags) for slug, (tags, _) in spaces.items()}
        api.refresh(force=True)
        found = {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}
        self.ids = {}
        for slug, (_, project) in spaces.items():
            self.ids[slug] = found[paths[slug]].id
            api.move_item(self.ids[slug], project.id)
        api.archive_project(self.old.id)

    def heads(self, groups):
        return [(g.project_id, g.parent_id, g.depth, g.status, g.word, g.text, g.open) for g in groups]


class SubProjectRuns(ParentWithSubs):

    def test_the_view_has_a_section_per_active_sub_project_in_tree_order(self):
        view = api.project_view(self.parent.id)
        self.assertEqual([r.item_id for r in view.runs], [self.ids["own-1"]])    # only its own runs
        self.assertEqual(self.heads(view.sub_runs), [
            (self.units.id, self.parent.id, 1, "blocked", "Blocked", "1 blocked, 1 running, 1 done", True),
            (self.inner.id, self.units.id, 2, "running", "Running", "1 running", True),
            (self.evals.id, self.parent.id, 1, "done", "Done", "6 done", False)])
        units, inner, evals = view.sub_runs
        self.assertEqual([r.item_id for r in units.runs], [self.ids["stuck-1"], self.ids["units-done"]])
        self.assertEqual([r.item_id for r in inner.runs], [self.ids["live-1"]])
        self.assertTrue(units.runs[0].can_mark_done)                            # a panel keeps its actions
        self.assertEqual((evals.name, len(evals.runs), evals.shown, evals.more), ("Per-domain evals", 6, 5, "+ 1 more"))
        self.assertEqual((units.shown, units.more), (2, ""))

    def test_archived_sub_projects_are_left_out(self):
        view = api.project_view(self.parent.id)
        self.assertNotIn(self.old.id, [g.project_id for g in view.sub_runs])
        every = [r.item_id for r in view.runs] + [r.item_id for g in view.sub_runs for r in g.runs]
        self.assertNotIn(self.ids["archived-1"], every)

    def test_a_sub_project_with_no_runs_is_a_folded_section(self):
        empty = api.create_project("Empty", parent_id=self.parent.id)
        view = api.project_view(self.parent.id)
        group = next(g for g in view.sub_runs if g.project_id == empty.id)
        self.assertEqual((group.status, group.glyph, group.word, group.text, group.open, group.runs),
                         ("pending", "\u00b7", "", "no runs", False, []))

    def test_status_groups_the_rolled_up_runs_the_same_way(self):
        status = api.project_status(self.parent.id, refresh=False)
        self.assertEqual(len(status.runs), 10)                                   # still rolled up
        self.assertEqual(self.heads(status.groups), self.heads(api.project_view(self.parent.id).sub_runs))
        evals = status.groups[-1]
        self.assertEqual((len(evals.runs), evals.more), (6, ""))                 # status lists them all
        self.assertEqual(evals.runs[0].kind, "night-sprint")                      # a Run, not a panel
        cut = api.project_status(self.parent.id, refresh=False, limit=2)
        self.assertEqual((len(cut.groups[-1].runs), cut.truncated), (2, True))

    def test_the_counts_wording_is_the_same_on_home_tiles_and_list(self):
        [card] = [c for c in api.home().cards if c.project.id == self.parent.id]
        self.assertEqual([(s.name, s.text) for s in card.sub_projects],
                         [("Machina decision units", "1 blocked, 1 running, 1 done"), ("Per-domain evals", "6 done")])
        view = api.project_view(self.parent.id)
        self.assertEqual([t.text for t in view.inside], ["1 blocked, 1 running, 1 done", "6 done"])
        lines = api.list_projects(with_runs=True).run_lines
        self.assertEqual(lines[self.parent.id], "1 blocked, 1 running, 8 done")
        self.assertEqual(lines[self.evals.id], "6 done")


class SubProjectRunsInTheCli(ParentWithSubs):
    def cli(self, *argv):
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        return done.stdout

    def test_show_prints_runs_under_each_sub_project_one_indent_per_level(self):
        out = self.cli("show", self.parent.id).splitlines()
        units = out.index("In Machina decision units  %s  1 blocked, 1 running, 1 done" % self.units.id[:8])
        inner = out.index("  In Inner  %s  1 running" % self.inner.id[:8])
        evals = out.index("In Per-domain evals  %s  6 done" % self.evals.id[:8])
        self.assertLess(units, inner)
        self.assertLess(inner, evals)
        self.assertTrue(out[units + 1].startswith("  %s  Blocked" % self.ids["stuck-1"][:8]), out[units + 1])
        self.assertTrue(out[inner + 1].startswith("    %s  Running" % self.ids["live-1"][:8]), out[inner + 1])
        self.assertEqual(sum(1 for line in out[evals + 1:] if "  Done  evals-" in line), 6)   # show prints all
        self.assertNotIn("Old", "\n".join(out[units:]))

    def test_show_and_status_json_carry_the_groups(self):
        view = json.loads(self.cli("show", self.parent.id, "--json"))
        self.assertEqual([g["project_id"] for g in view["sub_runs"]], [self.units.id, self.inner.id, self.evals.id])
        self.assertEqual(view["sub_runs"][2]["more"], "+ 1 more")
        status = json.loads(self.cli("--json", "status", self.parent.id, "--no-refresh"))
        self.assertEqual([(g["project_id"], g["depth"], g["open"]) for g in status["groups"]],
                         [(self.units.id, 1, True), (self.inner.id, 2, True), (self.evals.id, 1, False)])

    def test_status_and_list_text_use_the_counts_in_words(self):
        out = self.cli("status", self.parent.id, "--no-refresh")
        self.assertIn("In Machina decision units  %s  1 blocked, 1 running, 1 done" % self.units.id[:8], out)
        self.assertIn("1 blocked, 1 running, 8 done", self.cli("list"))
        self.assertNotIn("active", self.cli("list"))
