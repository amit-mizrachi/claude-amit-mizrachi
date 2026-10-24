"""Home as full-width rows ordered by activity (ticket 04), through the public SDK and the CLI: a
project's own activity against a sub-project's, ties by name, dismissed items not counting, the
quiet fold, and `list --by activity` (SDK, text and JSON). A run's activity is the mtime of its
state files, so each test ages a workspace by setting them."""

import json
import os
import subprocess
import sys
import time

from sdk import api, home as homepage, store

from . import PLUGIN
from .support import Sources

BIN = os.path.join(PLUGIN, "bin", "project-studio")
DONE3 = (("T01", "DONE"), ("T02", "DONE"), ("T03", "DONE"))


class Rows(Sources):
    def aged(self, slug, minutes, now=None):
        """A done workspace whose every state file last changed `minutes` before `now` (default: now)."""
        ws = self.workspace(slug, tags=DONE3)
        then = (now or time.time()) - minutes * 60
        for base, dirs, files in os.walk(ws):
            for name in files + dirs:
                os.utime(os.path.join(base, name), (then, then))
            os.utime(base, (then, then))
        return ws

    def file(self, ws, project_id):
        api.refresh(force=True)
        found = {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}
        return api.move_item(found[ws].id, project_id).item

    def names(self, state=None):
        return [c.project.name for c in (state or api.home()).cards]

    def test_a_sub_projects_activity_lifts_its_parent_row(self):
        own, deep = self.aged("own-20261020", 60), self.aged("deep-20261022", 5)
        a, b = api.create_project("A"), api.create_project("B")
        sub = api.create_project("B sub", parent_id=b.id)
        self.file(own, a.id)
        self.file(deep, sub.id)
        state = api.home()
        self.assertEqual(self.names(state), ["B", "A"])
        self.assertEqual(state.order, [b.id, a.id])
        rows = {c.project.id: c for c in state.cards}
        self.assertEqual((rows[b.id].last_activity, rows[a.id].last_activity), ("5 min ago", "1 h ago"))
        self.assertTrue(rows[b.id].last_activity_at < store.now_iso())
        self.assertEqual(rows[b.id].runs, [])                       # the run is in its block, not the row's own
        self.assertEqual([r.title for r in rows[b.id].sub_projects[0].runs], ["deep-20261022"])

    def test_a_dismissed_item_does_not_count_as_activity(self):
        old, new = self.aged("old-20261020", 120), self.aged("new-20261022", 5)
        a, b = api.create_project("A"), api.create_project("B")
        self.file(old, a.id)
        newer = self.file(new, b.id)
        self.assertEqual(self.names(), ["B", "A"])
        api.dismiss_item(newer.id)
        self.assertEqual(self.names(), ["A", "B"])

    def test_ties_go_by_name_in_any_case(self):
        api.create_project("beta")
        api.create_project("Alpha")
        api.create_project("gamma")
        self.assertEqual(self.names(), ["Alpha", "beta", "gamma"])
        now = time.time()
        same = [self.aged("x%d-20261020" % n, 30, now) for n in range(2)]
        z, y = api.create_project("Zed"), api.create_project("Yak")
        self.file(same[0], z.id)
        self.file(same[1], y.id)
        self.assertEqual(self.names()[:2], ["Yak", "Zed"])           # the same activity: by name
        self.assertEqual(api.home().cards[2].last_activity, "no activity yet")

    def test_projects_quiet_for_14_days_without_runs_fold_at_the_bottom(self):
        run = self.aged("r-20261020", 10)
        busy, empty, sub_quiet = api.create_project("Busy"), api.create_project("Empty"), api.create_project("Also")
        api.create_project("Inner", parent_id=sub_quiet.id)
        self.file(run, busy.id)
        now = api.home()
        self.assertEqual(([c.quiet for c in now.cards], now.quiet_text), ([False, False, False], ""))
        with store.read() as conn:                                   # 20 days on: only the row with a run stays
            later = homepage.state(conn, now=time.time() + 20 * 86400)
        self.assertEqual(self.names(later), ["Busy", "Also", "Empty"])
        self.assertEqual([c.quiet for c in later.cards], [False, True, True])
        self.assertEqual(later.quiet_text, "2 quiet projects")
        self.assertEqual(later.order, [c.project.id for c in later.cards])
        self.assertEqual(later.cards[0].last_activity, "20 d ago")

    def test_list_by_activity_orders_like_home(self):
        old, new = self.aged("old-20261020", 120), self.aged("new-20261022", 5)
        a, b = api.create_project("A"), api.create_project("B")
        sub = api.create_project("B sub", parent_id=b.id)
        api.create_project("A sub", parent_id=a.id)
        self.file(old, a.id)
        self.file(new, sub.id)
        listed = api.list_projects(by="activity", with_runs=True)
        self.assertEqual([p.name for p in listed.projects], ["Inbox", "B", "B sub", "A", "A sub"])
        self.assertEqual((listed.last_activity[b.id], listed.last_activity[a.id]), ("5 min ago", "2 h ago"))
        self.assertNotIn("inbox", listed.last_activity)
        self.assertEqual(api.list_projects().last_activity, {})      # tree order says nothing about activity
        self.assertEqual([p.name for p in api.list_projects(top_level=True, by="activity").projects],
                         ["Inbox", "B", "A"])
        with self.assertRaises(api.InvalidInput):
            api.list_projects(by="newest")

    def test_cli_list_by_activity(self):
        old, new = self.aged("old-20261020", 120), self.aged("new-20261022", 5)
        a, b = api.create_project("A"), api.create_project("B")
        self.file(old, a.id)
        self.file(new, b.id)

        def cli(*argv):
            done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
            return done.returncode, done.stdout, done.stderr

        code, out, err = cli("list", "--by", "activity")
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertTrue(lines[1].startswith(b.id[:8] + "  B"), lines)
        self.assertTrue(lines[1].endswith("5 min ago"), lines)
        self.assertTrue(lines[2].endswith("2 h ago"), lines)
        self.assertIn("1 done", lines[2])
        code, out, _ = cli("list", "--by", "activity", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["last_activity"][a.id], "2 h ago")
        self.assertNotIn("ago", cli("list")[1])                     # the default stays the tree
        self.assertNotEqual(cli("list", "--by", "newest")[0], 0)
