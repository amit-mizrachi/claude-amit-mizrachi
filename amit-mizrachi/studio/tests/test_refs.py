"""References through the public SDK: resolve_project and resolve_item."""

from unittest import mock

from sdk import api
from sdk.errors import Ambiguous, InvalidInput, NotFound

from .support import Sources
from .test_readers import SID_A, SID_B, agent


def ids(*values):
    """Patch the next ids a create hands out, so tests can make prefixes collide."""
    return mock.patch("sdk.model.new_project_id", side_effect=list(values))


class ProjectRefs(Sources):
    def test_an_exact_id_and_the_inbox_resolve(self):
        alpha = api.create_project("Alpha")
        self.assertEqual(api.resolve_project(alpha.id).id, alpha.id)
        self.assertEqual(api.resolve_project("inbox").id, "inbox")
        self.assertEqual(api.resolve_project("INBOX").id, "inbox")      # by name, any case

    def test_a_prefix_works_with_and_without_p_and_needs_four_characters(self):
        with ids("p_abcd11111111", "p_abcd22222222"):
            one, two = api.create_project("One"), api.create_project("Two")
        self.assertEqual(api.resolve_project("p_abcd1").id, one.id)
        self.assertEqual(api.resolve_project("abcd2").id, two.id)
        self.assertEqual(api.resolve_project(one.id[:8]).id, one.id)   # the short id the CLI prints
        with self.assertRaises(NotFound):
            api.resolve_project("abc")                                  # under 4 characters: not a prefix

    def test_a_name_matches_any_case_and_outer_spaces(self):
        alpha = api.create_project("Night Runs")
        self.assertEqual(api.resolve_project("  night runs ").id, alpha.id)

    def test_an_archived_name_does_not_match_but_its_id_does(self):
        old = api.create_project("Old")
        child = api.create_project("Kid", parent_id=old.id)
        api.archive_project(old.id)
        for name in ("Old", "kid"):
            with self.assertRaises(NotFound):
                api.resolve_project(name)
        self.assertEqual(api.resolve_project(old.id).id, old.id)
        self.assertEqual(api.resolve_project(child.id).id, child.id)

    def test_a_shared_name_is_ambiguous_with_candidates(self):
        a, b = api.create_project("Alpha"), api.create_project("Beta")
        da = api.create_project("Docs", parent_id=a.id)
        db = api.create_project("Docs", parent_id=b.id)
        with self.assertRaises(Ambiguous) as caught:
            api.resolve_project("docs")
        err = caught.exception
        self.assertEqual(err.code, "ambiguous")
        self.assertEqual(sorted(c["id"] for c in err.candidates), sorted([da.id, db.id]))
        self.assertEqual(sorted(c["parent_path"] for c in err.candidates), [["Alpha"], ["Beta"]])
        self.assertEqual(set(err.to_dict()), {"code", "message", "candidates"})
        self.assertIn("Alpha", str(err))

    def test_a_shared_prefix_is_ambiguous_and_a_unique_name_beats_it(self):
        with ids("p_beef11111111", "p_beef22222222", "p_0000beef0000"):
            one, two = api.create_project("One"), api.create_project("Two")
            named = api.create_project("beef")
        with self.assertRaises(Ambiguous) as caught:
            api.resolve_project("p_beef")
        self.assertEqual([c["id"] for c in caught.exception.candidates], [one.id, two.id])
        self.assertEqual(api.resolve_project("beef").id, named.id)      # a name wins over a shared prefix
        self.assertEqual(api.resolve_project("0000").id, named.id)      # a unique prefix wins over a name

    def test_candidates_stop_at_twenty(self):
        for n in range(22):
            parent = api.create_project("Parent %d" % n)
            api.create_project("Same", parent_id=parent.id)
        with self.assertRaises(Ambiguous) as caught:
            api.resolve_project("same")
        self.assertEqual(len(caught.exception.candidates), 20)
        self.assertIn("22 projects", str(caught.exception))
        self.assertIn("and 2 more", str(caught.exception))

    def test_nothing_matches_and_empty_is_invalid(self):
        api.create_project("Alpha")
        with self.assertRaises(NotFound) as caught:
            api.resolve_project("nope")
        self.assertEqual(caught.exception.to_dict()["code"], "not_found")
        for bad in ("", "   ", None):
            with self.assertRaises(InvalidInput):
                api.resolve_project(bad)


class ItemRefs(Sources):
    def setUp(self):
        super().setUp()
        self.agents([agent(SID_A, "alpha", "/w/proj/alpha"), agent(SID_B, "beta", "/w/proj/beta")])

    def refresh(self, *item_ids):
        with mock.patch("sdk.reconcile.new_item_id", side_effect=list(item_ids)):
            api.refresh(force=True)
        return {i.key: i for i in api.find_items(refresh=False).items}

    def test_an_exact_id_and_a_prefix_with_and_without_i_resolve(self):
        by_key = self.refresh("i_aaaa11111111", "i_bbbb22222222")
        a = by_key[SID_A]
        self.assertEqual(api.resolve_item(a.id).id, a.id)
        self.assertEqual(api.resolve_item(a.id[:8]).id, a.id)
        self.assertEqual(api.resolve_item(a.id[2:7]).id, a.id)
        self.assertEqual(api.resolve_item(a.id).project_path, ["Inbox"])

    def test_a_short_prefix_and_a_title_do_not_match(self):
        by_key = self.refresh("i_aaaa11111111", "i_bbbb22222222")
        with self.assertRaises(NotFound):
            api.resolve_item(by_key[SID_A].id[2:5])         # "aaa": under 4 characters as typed
        with self.assertRaises(NotFound):
            api.resolve_item("alpha")

    def test_a_shared_prefix_is_ambiguous_with_candidates(self):
        self.refresh("i_cafe11111111", "i_cafe22222222")
        with self.assertRaises(Ambiguous) as caught:
            api.resolve_item("cafe")
        candidates = caught.exception.candidates
        self.assertEqual([c["id"] for c in candidates], ["i_cafe11111111", "i_cafe22222222"])
        self.assertEqual(set(candidates[0]), {"id", "title", "kind", "project_path"})
        self.assertEqual(candidates[0]["project_path"], ["Inbox"])

    def test_nothing_matches(self):
        self.refresh("i_aaaa11111111", "i_bbbb22222222")
        with self.assertRaises(NotFound):
            api.resolve_item("i_ffff")
        with self.assertRaises(InvalidInput):
            api.resolve_item("")
