"""The studio's home page through the public SDK: card order, at most 3 runs, "+ n earlier runs",
"n inside", the empty text, first run, a failed source's banner, the "Still reading" note while a
slow source is read, and the 14-day Inbox window."""

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
        self.assertEqual(state.caption, "Needs you first, then running, then latest change")

    def test_a_project_without_runs_says_so(self):
        alpha = api.create_project("Alpha")
        api.refresh(force=True)
        state = api.home()
        self.assertFalse(state.loading)
        self.assertFalse(state.first_run)
        [card] = state.cards
        self.assertEqual((card.project.id, card.empty, card.runs, card.more), (alpha.id, "No night runs yet", [], ""))

    def test_blocked_comes_before_done_and_empty(self):
        done, blocked = self.workspace("done-20261023", tags=DONE3), self.workspace(
            "blk-20261023", tags=(("T01", "DONE"), ("T02", "BLOCKED: tests red"), ("T03", None)))
        a, b, c = api.create_project("A"), api.create_project("B"), api.create_project("C")
        self.file([done], a.id)
        self.file([blocked], b.id)
        cards = api.home().cards
        self.assertEqual(cards[0].project.id, b.id)
        self.assertEqual(cards[0].attention, "blocked")
        self.assertEqual(cards[0].runs[0].word, "Blocked")
        self.assertEqual({card.project.id for card in cards}, {a.id, b.id, c.id})
        self.assertEqual([card.empty for card in cards if card.project.id == c.id], ["No night runs yet"])

    def test_at_most_three_runs_then_the_earlier_ones_as_text(self):
        running = self.workspace("live-20261023", tags=(("T01", "DONE"), ("T02", ""), ("T03", None)))
        done = [self.workspace("old%d-20261020" % n, tags=DONE3) for n in range(4)]
        p = api.create_project("P")
        self.file([running] + done, p.id)
        [card] = api.home().cards
        self.assertEqual(len(card.runs), 3)
        self.assertEqual(card.runs[0].status, "running")
        self.assertEqual(card.runs[0].progress, "T02 of 3")
        self.assertEqual(card.more, "+ 2 earlier runs, all done")

    def test_sub_projects_show_only_as_a_count(self):
        p = api.create_project("P")
        api.create_project("Inner", parent_id=p.id)
        api.create_project("Other", parent_id=p.id)
        api.refresh(force=True)
        [card] = api.home().cards
        self.assertEqual(card.inside, "2 inside")

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
        self.assertEqual((state.reading, state.reading_text), (["prs"], "Still reading PRs..."))
        self.write(gate, "1")
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual((api.home().reading, api.home().reading_text), ([], ""))

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
