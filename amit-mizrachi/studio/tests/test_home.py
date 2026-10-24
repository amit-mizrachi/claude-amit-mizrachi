"""The studio's home page through the public SDK: a row's status words, at most 6 own runs, "+ n more",
sub-project blocks (tree order, their own run line and runs, "in <sub-project>" on a deeper run,
archived ones left out), the empty text, first run, a failed source's banner (kept through a read in
flight, gone when the source reads fine), "Reading PRs..." in the header's status line while a slow
source is read with nothing else in the state moving, and the 14-day Inbox window. The activity order and the quiet
fold are in test_home_rows.py."""

import os
import threading
import time

from sdk import api, store

from .support import STUBS, Sources

DONE3 = (("T01", "DONE"), ("T02", "DONE"), ("T03", "DONE"))


class Home(Sources):
    def items(self):
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}

    def file(self, paths, project_id):
        found = self.items()
        for path in paths:
            api.move_item(found[path].id, project_id)

    def test_a_fresh_store_answers_with_the_first_run_state(self):
        state = api.home()
        self.assertFalse(state.loading)
        self.assertTrue(state.first_run)
        self.assertEqual(state.cards, [])
        self.assertEqual((state.reading, state.reading_text), ([], ""))
        self.assertEqual(state.caption, "Latest activity first")
        self.assertEqual((state.order, state.quiet_text), ([], ""))

    def test_a_project_without_runs_says_so(self):
        alpha = api.create_project("Alpha")
        api.refresh(force=True)
        state = api.home()
        self.assertFalse(state.loading)
        self.assertFalse(state.first_run)
        [card] = state.cards
        self.assertEqual((card.project.id, card.empty, card.runs, card.more), (alpha.id, "No night runs yet", [], ""))

    def test_a_row_says_its_status_and_runs_in_words(self):
        done, blocked = self.workspace("done-20261023", tags=DONE3), self.workspace(
            "blk-20261023", tags=(("T01", "DONE"), ("T02", "BLOCKED: tests red"), ("T03", None)))
        a, b, c = api.create_project("A"), api.create_project("B"), api.create_project("C")
        self.file([done], a.id)
        self.file([blocked], b.id)
        cards = api.home().cards
        rows = {card.project.id: card for card in cards}
        self.assertEqual((rows[b.id].attention, rows[b.id].status, rows[b.id].word, rows[b.id].counts),
                         ("blocked", "blocked", "Blocked", "1 blocked"))
        self.assertEqual(rows[b.id].runs[0].word, "Blocked")
        self.assertEqual((rows[a.id].word, rows[a.id].counts), ("Done", "1 done"))
        self.assertEqual((rows[c.id].glyph, rows[c.id].word, rows[c.id].counts), ("\u00b7", "", "no runs"))
        self.assertEqual({card.project.id for card in cards}, {a.id, b.id, c.id})
        self.assertEqual([card.empty for card in cards if card.project.id == c.id], ["No night runs yet"])

    def test_a_run_blocked_after_its_last_ticket_names_the_blocked_stage(self):
        ws = self.workspace("ci-20261023", tags=(("T01", "DONE"), ("T02", "DONE"),
                                                 ("CI", "BLOCKED: tests red after 3 fixes")))
        p = api.create_project("P")
        self.file([ws], p.id)
        [run] = api.home().cards[0].runs
        self.assertEqual((run.word, run.reason, run.bar), ("Blocked", "CI blocked: tests red after 3 fixes", ["d", "d"]))
        [status_run] = api.project_status(p.id, refresh=False).runs
        self.assertEqual(status_run.progress_text, "at CI - 2 of 2 done")

    def test_a_blocked_ticket_still_reads_as_that_ticket(self):
        ws = self.workspace("t-20261023", tags=(("T01", "BLOCKED: repo archived"), ("CI", None)))
        p = api.create_project("P")
        self.file([ws], p.id)
        [run] = api.home().cards[0].runs
        self.assertEqual((run.word, run.reason), ("Blocked", "T01 of 1 blocked: repo archived"))

    def test_a_merged_pr_ends_a_blocked_or_waiting_run(self):
        facts = {"REPO_SLUG": "me/r", "BRANCH": "feat/a"}
        ws = self.workspace("m-20261023", facts=facts, tags=(("T01", "DONE"), ("T02", "BLOCKED: tests red")))
        red = self.workspace("c-20261023", facts=dict(facts, BRANCH="feat/c"), tags=DONE3,
                             files={"state/ACCEPTANCE.verdict": "FAIL abc1234 required checks failing\n"})
        self.prs("me/r", [{"number": n, "title": b, "headRefName": "feat/" + b, "state": "MERGED", "isDraft": False,
                           "url": "https://github.com/me/r/pull/%d" % n, "updatedAt": "2026-10-20T00:00:00Z"}
                          for n, b in ((4, "a"), (5, "c"))])
        p = api.create_project("P")
        self.file([ws, red], p.id)
        card = api.home().cards[0]
        self.assertEqual(card.attention, "")
        lines = {r.title: (r.word, r.reason, r.progress) for r in card.runs}
        self.assertEqual(lines, {"m-20261023": ("Merged", "PR #4 merged", ""),
                                 "c-20261023": ("Merged", "PR #5 merged", "")})

    def test_at_most_six_runs_then_the_rest_as_text(self):
        running = self.workspace("live-20261023", tags=(("T01", "DONE"), ("T02", ""), ("T03", None)))
        done = [self.workspace("old%d-20261020" % n, tags=DONE3) for n in range(7)]
        p = api.create_project("P")
        self.file([running] + done, p.id)
        [card] = api.home().cards
        self.assertEqual(len(card.runs), 6)
        self.assertEqual(card.runs[0].status, "running")
        self.assertEqual(card.runs[0].progress, "T02 of 3")
        self.assertEqual(card.more, "+ 2 more, all done")

    def test_sub_projects_are_blocks_of_their_own_in_tree_order(self):
        p = api.create_project("P")
        beta = api.create_project("beta", parent_id=p.id)
        alpha = api.create_project("Alpha", parent_id=p.id)
        api.create_project("Deep one", parent_id=alpha.id)
        api.create_project("Deep two", parent_id=alpha.id)
        api.refresh(force=True)
        [card] = api.home().cards
        lines = [(s.project_id, s.name, s.status, s.glyph, s.word, s.text, s.inside) for s in card.sub_projects]
        self.assertEqual(lines, [(alpha.id, "Alpha", "pending", "\u00b7", "", "no runs", "2 inside"),
                                 (beta.id, "beta", "pending", "\u00b7", "", "no runs", "")])
        self.assertFalse(hasattr(card, "inside"))

    def test_a_sub_project_block_carries_its_runs_and_the_row_only_its_own(self):
        live = self.workspace("live-20261023", tags=(("T01", "DONE"), ("T02", ""), ("T03", None)))
        deep = self.workspace("deep-20261022", tags=DONE3)
        own = self.workspace("own-20261021", tags=DONE3)
        p = api.create_project("Shapes-agent to Machina")
        units = api.create_project("Machina decision units", parent_id=p.id)
        evals = api.create_project("Per-domain MCP and evals", parent_id=p.id)
        inner = api.create_project("Inner", parent_id=units.id)
        self.file([live], units.id)
        self.file([deep], inner.id)
        self.file([own], p.id)
        [card] = api.home().cards
        self.assertEqual([s.project_id for s in card.sub_projects], [units.id, evals.id])
        self.assertNotIn(p.id, [s.project_id for s in card.sub_projects])
        units_line, evals_line = card.sub_projects
        self.assertEqual((units_line.status, units_line.glyph, units_line.word, units_line.text, units_line.inside),
                         ("running", "\u25cf", "Running", "1 running, 1 done", "1 inside"))
        self.assertEqual((evals_line.word, evals_line.text), ("", "no runs"))
        self.assertEqual([(r.title, r.sub_project) for r in card.runs], [("own-20261021", "")])
        tags = [(r.title, r.sub_project_id, r.sub_project) for r in units_line.runs]
        self.assertEqual(tags, [("live-20261023", "", ""), ("deep-20261022", inner.id, "in Inner")])
        self.assertEqual((evals_line.runs, evals_line.more), ([], ""))
        self.assertEqual((card.status, card.counts), ("running", "1 running, 2 done"))

    def test_a_sub_project_block_shows_three_runs_then_the_rest_as_text(self):
        live = self.workspace("live-20261023", tags=(("T01", "DONE"), ("T02", ""), ("T03", None)))
        done = [self.workspace("old%d-20261020" % n, tags=DONE3) for n in range(3)]
        p = api.create_project("P")
        sub = api.create_project("Sub", parent_id=p.id)
        self.file([live] + done, sub.id)
        [block] = api.home().cards[0].sub_projects
        self.assertEqual([r.title for r in block.runs][0], "live-20261023")
        self.assertEqual((len(block.runs), block.more), (3, "+ 1 more, all done"))

    def test_archived_sub_projects_do_not_show(self):
        ws = self.workspace("arch-20261023", tags=DONE3)
        p = api.create_project("P")
        kept = api.create_project("Kept", parent_id=p.id)
        gone = api.create_project("Gone", parent_id=p.id)
        too = api.create_project("Gone too", parent_id=kept.id)
        self.file([ws], gone.id)
        api.archive_project(gone.id)
        api.archive_project(too.id)
        lone = api.create_project("Lone")
        cards = {c.project.id: c for c in api.home().cards}
        self.assertEqual([(s.name, s.inside) for s in cards[p.id].sub_projects], [("Kept", "")])
        self.assertEqual((cards[p.id].runs, cards[p.id].empty), ([], "No night runs yet"))
        self.assertEqual(cards[lone.id].sub_projects, [])

    def test_a_failed_pr_read_gives_a_banner_and_keeps_the_last_good_pr_text(self):
        repo, _ = self.git_repo("r", [])
        ws = self.workspace("s-20261023", facts={"REPO_PATH": repo, "REPO_SLUG": "me/r", "BRANCH": "feat/a"},
                            tags=DONE3)
        self.prs("me/r", [{"number": 4, "title": "a", "headRefName": "feat/a", "state": "OPEN", "isDraft": True,
                           "url": "https://github.com/me/r/pull/4", "updatedAt": "2026-10-20T00:00:00Z"}])
        p = api.create_project("P")
        self.file([ws], p.id)
        before = api.home()
        self.assertEqual(before.banners, [])
        self.assertTrue(before.cards[0].pr.startswith("PR #4"), before.cards[0].pr)
        self.assertTrue(before.source_age.startswith("PRs "), before.source_age)
        self.write(os.path.join(self.stub, "gh-fail"), "1")
        api.refresh(force=True)
        after = api.home()
        self.assertEqual(after.cards[0].pr, before.cards[0].pr)
        prs = [b for b in after.banners if b.source == "prs"]
        self.assertEqual(len(prs), 1)
        self.assertIn("gh pr list failed for r", prs[0].text)
        self.assertIn("PR states below are from", prs[0].text)
        self.assertIn("Run status is live.", prs[0].text)

    def slow_gh(self):
        """Put a `gh` first on PATH that waits until the returned gate file exists."""
        gate = os.path.join(self.stub, "gh-open")
        gh = self.write(os.path.join(self.mkdir("slowbin"), "gh"),
                        '#!/usr/bin/env bash\nwhile [ ! -e "%s" ]; do sleep 0.05; done\nexec "%s/gh" "$@"\n'
                        % (gate, STUBS))
        os.chmod(gh, 0o755)
        os.environ["PATH"] = os.path.dirname(gh) + os.pathsep + os.environ["PATH"]
        return gate

    def test_a_due_slow_source_does_not_hold_back_the_cards(self):
        gate = self.slow_gh()
        self.workspace("s-20261023", facts={"REPO_SLUG": "me/r"})
        alpha = api.create_project("Alpha")
        worker = threading.Thread(target=api.refresh, kwargs={"force": True}, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 10)
        self.addCleanup(self.write, gate, "1")
        deadline = time.time() + 10
        while "prs" not in api.home().reading and time.time() < deadline:
            time.sleep(0.05)
        started = time.time()
        state = api.home(refresh=True)
        self.assertLess(time.time() - started, 5)
        self.assertEqual([card.project.id for card in state.cards], [alpha.id])
        self.assertFalse(state.loading)
        self.assertEqual((state.reading, state.reading_text, state.status_text),
                         (["prs"], "Reading PRs...", "Reading PRs..."))
        self.write(gate, "1")
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual((api.home().reading, api.home().reading_text), ([], ""))

    def pr_project(self):
        """A project holding a run whose repo has one open PR, read once; the `gh` on PATH waits for a gate."""
        gate = self.slow_gh()
        self.write(gate, "1")
        repo, _ = self.git_repo("r", [])
        ws = self.workspace("s-20261023", facts={"REPO_PATH": repo, "REPO_SLUG": "me/r", "BRANCH": "feat/a"},
                            tags=DONE3)
        self.prs("me/r", [{"number": 4, "title": "a", "headRefName": "feat/a", "state": "OPEN", "isDraft": True,
                           "url": "https://github.com/me/r/pull/4", "updatedAt": "2026-10-20T00:00:00Z"}])
        self.file([ws], api.create_project("P").id)
        return gate

    def read_slowly(self, gate):
        """Start a forced refresh held at `gh` and return (the home state while PRs are read, the worker)."""
        os.remove(gate)
        worker = threading.Thread(target=api.refresh, kwargs={"force": True}, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 10)
        self.addCleanup(self.write, gate, "1")
        deadline = time.time() + 10
        while "prs" not in api.home().reading and time.time() < deadline:
            time.sleep(0.05)
        return api.home(), worker

    def test_a_pr_read_shows_only_in_the_status_line_and_keeps_the_same_rows(self):
        gate = self.pr_project()
        before = api.home()
        self.assertTrue(before.status_text.startswith("PRs "), before.status_text)
        during, worker = self.read_slowly(gate)
        self.assertEqual((during.reading, during.status_text), (["prs"], "Reading PRs..."))
        self.write(gate, "1")
        worker.join(10)
        after = api.home()
        self.assertEqual((after.reading, after.status_text), ([], after.source_age))
        for state in (during, after):
            self.assertEqual(state.cards, before.cards)
            self.assertEqual((state.order, state.banners, state.quiet_text, state.archived),
                             (before.order, before.banners, before.quiet_text, before.archived))

    def test_a_failed_source_banner_stays_through_a_read_and_goes_when_it_reads_fine(self):
        gate = self.pr_project()
        fail = self.write(os.path.join(self.stub, "gh-fail"), "1")
        api.refresh(force=True)
        failed = [(b.source, b.key, b.error) for b in api.home().banners]
        self.assertEqual([b[0] for b in failed], ["prs"])
        during, worker = self.read_slowly(gate)
        self.assertEqual([(b.source, b.key, b.error) for b in during.banners], failed)
        self.write(gate, "1")
        worker.join(10)
        self.assertEqual([(b.source, b.key, b.error) for b in api.home().banners], failed)
        os.remove(fail)
        api.refresh(force=True)
        self.assertEqual(api.home().banners, [])

    def unfiled(self, name, days_ago):
        """An artifact back in the Inbox whose last activity was `days_ago` days ago."""
        p = api.create_project("Holder " + name)
        item = api.add_item("artifact", "https://example.com/" + name, p.id).item
        api.remove_item(item.id)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days_ago * 86400))
        with store.write() as conn:
            conn.execute("UPDATE items SET data_json = ?, seen_at = ? WHERE id = ?",
                         ('{"updated_at": "%s"}' % stamp, stamp, item.id))
        return item.id

    def test_the_inbox_holds_only_items_active_in_the_last_14_days(self):
        fresh, stale = self.unfiled("fresh", 13), self.unfiled("stale", 15)
        self.assertEqual(api.home().inbox_count, 1)
        self.assertEqual([e.item.id for e in api.inbox(refresh=False).entries], [fresh])
        view = api.inbox_view()
        self.assertEqual((view.count, [r.item_id for r in view.rows]), (1, [fresh]))
        found = api.find_items("example.com/stale", refresh=False)
        self.assertEqual([i.id for i in found.items], [stale])
        target = api.create_project("Target")
        self.assertEqual(api.move_item(stale, target.id).item.project_id, target.id)

    def test_the_inbox_project_counts_what_the_inbox_shows(self):
        fresh = self.unfiled("fresh", 1)
        self.unfiled("stale", 30)
        with store.write() as conn:
            conn.execute("UPDATE items SET gone_at = ? WHERE id != ? AND project_id = ?",
                         (store.now_iso(), fresh, store.INBOX_ID))
        self.unfiled("other", 2)
        inbox = api.get_project(store.INBOX_ID)
        self.assertEqual(inbox.item_count, api.home().inbox_count)
        self.assertEqual(inbox.item_count, 2)
        self.assertEqual(api.list_projects().projects[0].item_count, 2)
