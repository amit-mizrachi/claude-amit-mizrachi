"""Ticket 06: project moves with Undo, the Inbox drawer, the "Move to..." / "Set parent" picker,
rules from moves in the project view, and the studio's move routes over a real socket."""

import http.client
import json
import os

from sdk import api, server
from sdk.errors import Refused

from .support import Sources, TempHome
from .test_readers import SID_A, SID_B, SID_C, agent

CYCLE = "Can't move Project Studio into Studio MCP tools: it is inside Project Studio."


class ProjectMoves(TempHome):
    def setUp(self):
        super().setUp()
        self.studio = api.create_project("Project Studio")
        self.tools = api.create_project("Studio MCP tools", self.studio.id)
        self.evals = api.create_project("Eval oracles")

    def test_a_card_onto_a_card_is_undoable(self):
        moved = api.move(self.evals.id, self.studio.id)
        self.assertEqual((moved.project.parent_id, moved.message), (self.studio.id, "Moved to Project Studio"))
        self.assertIsNotNone(moved.move_id)
        back = api.undo_move(moved.move_id)
        self.assertEqual((back.project.parent_id, back.message), (None, "Moved back to the top level"))

    def test_undo_after_a_newer_move_is_refused(self):
        moved = api.move(self.evals.id, self.studio.id)
        api.move(self.evals.id, None)
        with self.assertRaises(Refused) as caught:
            api.undo_move(moved.move_id)
        self.assertEqual(str(caught.exception), "Can't undo: Eval oracles was moved again since.")

    def test_a_cycle_is_refused_with_the_exact_copy(self):
        with self.assertRaises(Refused) as caught:
            api.move(self.studio.id, self.tools.id)
        self.assertEqual(str(caught.exception), CYCLE)

    def test_a_project_move_teaches_no_rule_and_a_moved_project_can_still_be_deleted(self):
        moved = api.move(self.evals.id, self.studio.id)
        with self.assertRaises(Refused):
            api.save_rule_from_move(moved.move_id)
        self.assertEqual(api.delete_project(self.evals.id).name, "Eval oracles")

    def test_set_parent_offers_the_top_level_and_every_other_project(self):
        offer = api.move_choices(self.tools.id)
        self.assertEqual((offer.kind, offer.title), ("project", "Set parent of Studio MCP tools"))
        self.assertEqual([c.label for c in offer.choices], ["Top level", "Eval oracles"])
        top = api.move_choices(self.studio.id)
        self.assertEqual([c.label for c in top.choices], ["Eval oracles", "Project Studio / Studio MCP tools"])


class Drawer(Sources):
    def setUp(self):
        super().setUp()
        self.agents([agent(SID_A, "alpha", "/w/proj/alpha"), agent(SID_B, "beta", "/w/proj/beta")])
        api.refresh(force=True)
        self.by_key = {i.key: i for i in api.find_items(refresh=False).items}
        self.one = api.create_project("One")

    def test_rows_carry_kind_and_fact_and_a_suggestion_only_when_there_is_one(self):
        moved = api.move_item(self.by_key[SID_A].id, self.one.id)
        api.save_rule_from_move(moved.move_id)
        api.remove_item(self.by_key[SID_A].id)
        view = api.inbox_view()
        rows = {r.item_id: r for r in view.rows}
        alpha, beta = rows[self.by_key[SID_A].id], rows[self.by_key[SID_B].id]
        self.assertEqual((view.count, view.hint), (2, "Drag a row onto a card, or Accept the suggestion."))
        self.assertTrue(alpha.meta.startswith("bg session"))
        self.assertEqual((alpha.chip, alpha.chip_title, alpha.can_accept),
                         ("\u2192 One", "rule: folder /w/proj/alpha", True))
        self.assertEqual((beta.chip, beta.can_accept), ("", False))

    def test_accept_toasts_and_offers_the_rule_with_its_parts(self):
        moved = api.move_item(self.by_key[SID_A].id, self.one.id)
        self.assertEqual(moved.message, "Moved to One")
        self.assertEqual(moved.rule_preview.parts, [["folder", "/w/proj/alpha"]])
        rule = api.save_rule_from_move(moved.move_id)
        self.assertEqual([r.id for r in api.project_view(self.one.id).rules], [rule.id])
        api.delete_rule(rule.id)
        self.assertEqual(api.project_view(self.one.id).rules, [])

    def test_undo_drops_the_rule_its_move_taught_and_keeps_an_older_one(self):
        moved = api.move_item(self.by_key[SID_A].id, self.one.id)
        self.assertTrue(api.save_rule_from_move(moved.move_id).created)
        back = api.undo_move(moved.move_id)
        self.assertEqual(back.message, "Moved back to Inbox. The rule was removed.")
        api.refresh(force=True)
        self.assertEqual(api.find_items(query="alpha", refresh=False).items[0].project_id, "inbox")
        self.assertEqual(api.list_rules().rules, [])
        older = api.save_rule_from_move(api.move_item(self.by_key[SID_B].id, self.one.id).move_id)
        api.move_item(self.by_key[SID_B].id, "inbox")
        again = api.move_item(self.by_key[SID_B].id, self.one.id)
        self.assertFalse(api.save_rule_from_move(again.move_id).created)
        self.assertEqual(api.undo_move(again.move_id).message, "Moved back to Inbox")
        self.assertEqual([r.id for r in api.list_rules().rules], [older.id])

    def test_a_session_started_in_the_home_folder_teaches_no_rule(self):
        self.agents([agent(SID_C, "homebody", os.path.expanduser("~"))])
        api.refresh(force=True)
        item = api.find_items(query="homebody", refresh=False).items[0]
        moved = api.move_item(item.id, self.one.id)
        self.assertIsNone(moved.rule_preview)
        with self.assertRaises(Refused) as caught:
            api.save_rule_from_move(moved.move_id)
        self.assertEqual(str(caught.exception), "Nothing about homebody to learn a rule from.")

    def test_move_to_offers_every_project_but_its_own(self):
        offer = api.move_choices(self.by_key[SID_A].id)
        self.assertEqual((offer.kind, offer.revision), ("item", self.by_key[SID_A].revision))
        self.assertEqual([c.label for c in offer.choices], ["One"])


class Routes(TempHome):
    def setUp(self):
        super().setUp()
        self.addCleanup(api.stop_studio)
        self.port = api.open_studio().port
        self.token = server.read_info()["token"]
        self.studio = api.create_project("Project Studio")
        self.tools = api.create_project("Studio MCP tools", self.studio.id)
        self.evals = api.create_project("Eval oracles")

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": "127.0.0.1:%d" % self.port, "X-Studio-Token": self.token}
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
        res = conn.getresponse()
        data = json.loads(res.read())
        conn.close()
        return res.status, data

    def test_move_and_undo_and_a_refused_cycle(self):
        status, moved = self.call("POST", "/api/move", {"target_id": self.evals.id, "to_project_id": self.studio.id})
        self.assertEqual((status, moved["message"]), (200, "Moved to Project Studio"))
        status, back = self.call("POST", "/api/undo", {"move_id": moved["move_id"]})
        self.assertEqual((status, back["project"]["parent_id"]), (200, None))
        status, refused = self.call("POST", "/api/move", {"target_id": self.studio.id, "to_project_id": self.tools.id})
        self.assertEqual((status, refused["code"], refused["message"]), (400, "refused", CYCLE))

    def test_the_drawer_and_the_picker_are_reads(self):
        status, drawer = self.call("GET", "/inbox")
        self.assertEqual((status, drawer["count"], drawer["rows"]), (200, 0, []))
        status, offer = self.call("GET", "/choices?id=%s" % self.tools.id)
        self.assertEqual((status, offer["title"]), (200, "Set parent of Studio MCP tools"))
        self.assertEqual(self.call("POST", "/api/rule/delete", {"rule_id": "r_000000000000"})[0], 400)
