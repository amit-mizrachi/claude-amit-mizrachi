"""Open in Terminal, the open actions, the project view and the header actions, through the public SDK.

`claude`, `open` and `pbcopy` are stubbed on PATH (tests/stubs): nothing opens on this Mac.
"""

import os
import re
import shlex
import time

from sdk import actions, api, store
from sdk.errors import InvalidInput, NotFound, Refused

from . import STUDIO
from .support import Sources

SID_A = "11111111-1111-4111-8111-111111111111"
SID_B = "22222222-2222-4222-8222-222222222222"
SID_C = "33333333-3333-4333-8333-333333333333"


def agent(sid, name, cwd, state="working"):
    return {"id": sid[:8], "sessionId": sid, "name": name, "cwd": cwd, "state": state, "kind": "background",
            "startedAt": int(time.time() * 1000) - 120000}


class Studio(Sources):
    def items(self):
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}

    def calls(self):
        path = os.path.join(self.stub, "calls")
        return open(path).read().splitlines() if os.path.exists(path) else []

    def flag(self, name):
        self.write(os.path.join(self.stub, name), "1")

    def old(self, path):
        then = time.time() - 3600
        os.utime(path, (then, then))


class TerminalCommand(Studio):
    def test_attach_when_claude_agents_lists_the_session(self):
        cwd = self.mkdir("work")
        self.agents([agent(SID_A, "ns-x-T01", cwd)])
        self.old(self.transcript(SID_A, cwd, title="ns-x-T01"))
        cmd = api.terminal_command(self.items()[SID_A].id)
        self.assertEqual((cmd.mode, cmd.command, cmd.confirm), ("attach", "claude attach 11111111", ""))

    def test_resume_in_the_recorded_cwd_when_not_listed(self):
        cwd = self.mkdir("work")
        self.old(self.transcript(SID_B, cwd, kind="interactive", title="Plan it"))
        cmd = api.terminal_command(self.items()[SID_B].id)
        self.assertEqual(cmd.mode, "resume")
        self.assertEqual(cmd.command, "cd %s && claude --resume %s" % (shlex.quote(cwd), SID_B))

    def test_a_bg_session_that_left_claude_agents_resumes(self):
        cwd = self.mkdir("work")
        self.agents([agent(SID_A, "ns-x-T01", cwd)])
        self.old(self.transcript(SID_A, cwd, title="ns-x-T01"))
        item = self.items()[SID_A]
        self.agents([])
        self.assertEqual(api.terminal_command(item.id).mode, "resume")

    def test_a_cwd_with_spaces_and_quotes_is_one_shell_word(self):
        cwd = self.mkdir("it's a \"dir\" $(touch x)")
        self.old(self.transcript(SID_B, cwd, kind="interactive", title="Plan it"))
        cmd = api.terminal_command(self.items()[SID_B].id)
        words = shlex.split(cmd.command)
        self.assertEqual(words, ["cd", cwd, "&&", "claude", "--resume", SID_B])

    def test_bad_ids_are_refused(self):
        with self.assertRaises(Refused):
            actions.command_for(SID_A, "1111; rm -rf ~", "/tmp", True)
        with self.assertRaises(Refused):
            actions.command_for("not-a-uuid; ls", "", "/tmp", False)
        with self.assertRaises(Refused):
            actions.command_for(SID_A, "", "relative/dir", False)
        with self.assertRaises(NotFound):
            api.terminal_command("i_nothere00000")
        with self.assertRaises(NotFound):
            api.terminal_command("../../etc/passwd")

    def test_only_sessions_and_runs_open_in_terminal(self):
        url = "https://claude.ai/artifact/abc"
        ws = self.workspace("x-20261023", files={"state/ARTIFACT.url": url + "\n"})
        found = self.items()
        with self.assertRaises(InvalidInput):
            api.terminal_command(found[url].id)
        with self.assertRaises(Refused):
            api.terminal_command(found[ws].id)    # a run with no live session

    def test_a_run_opens_its_live_session(self):
        ws = self.workspace("x-20261023")
        self.agents([agent(SID_A, "ns-x-T02", ws)])
        self.old(self.transcript(SID_A, ws, title="ns-x-T02"))
        found = self.items()
        cmd = api.terminal_command(found[ws].id)
        self.assertEqual((cmd.item_id, cmd.command), (found[SID_A].id, "claude attach 11111111"))


class OpenInTerminal(Studio):
    def setUp(self):
        super().setUp()
        self.cwd = self.mkdir("work")
        self.path = self.transcript(SID_B, self.cwd, kind="interactive", title="Plan it")
        self.old(self.path)
        self.item = self.items()[SID_B]

    def test_writes_a_0700_command_file_and_opens_it(self):
        done = api.open_in_terminal(self.item.id)
        self.assertTrue(done.opened)
        self.assertEqual(done.message, "Opened in Terminal:")
        self.assertEqual(done.path, os.path.join(store.home(), "open", self.item.id + ".command"))
        self.assertEqual(os.stat(done.path).st_mode & 0o777, 0o700)
        self.assertEqual(open(done.path).read().splitlines()[-1], done.command.command)
        self.assertIn("open %s" % done.path, self.calls())

    def test_a_failed_open_copies_the_command(self):
        self.flag("open-fail")
        done = api.open_in_terminal(self.item.id)
        self.assertEqual((done.opened, done.copied), (False, True))
        self.assertEqual(done.message, "Could not open Terminal. Command copied:")
        self.assertEqual(open(os.path.join(self.stub, "clipboard")).read(), done.command.command)

    def test_when_the_copy_fails_too_it_says_copy_it_yourself(self):
        self.flag("open-fail")
        self.flag("pbcopy-fail")
        done = api.open_in_terminal(self.item.id)
        self.assertEqual((done.opened, done.copied), (False, False))
        self.assertEqual(done.message, "Could not open Terminal. Copy this command:")

    def test_a_transcript_changed_in_the_last_5_minutes_asks_once(self):
        os.utime(self.path, None)
        asked = api.open_in_terminal(self.item.id)
        self.assertTrue(asked.needs_confirm)
        self.assertFalse(asked.opened)
        self.assertIn("may still be open in another window", asked.message)
        self.assertEqual([c for c in self.calls() if c.startswith("open ")], [])
        done = api.open_in_terminal(self.item.id, confirmed=True)
        self.assertTrue(done.opened)


class OpenTarget(Studio):
    def test_a_run_opens_its_plan_and_its_folder(self):
        url = "https://claude.ai/artifact/abc"
        ws = self.workspace("x-20261023", files={"state/ARTIFACT.url": url + "\n"})
        run = self.items()[ws]
        plan = api.open_target(run.id, "plan")
        self.assertEqual((plan.value, plan.how, plan.opened), (url, "url", True))
        folder = api.open_target(run.id)
        self.assertEqual((folder.value, folder.how), (ws, "folder"))
        self.assertEqual(self.calls()[-2:], ["open %s" % url, "open %s" % os.path.realpath(ws)])

    def test_refuses_paths_outside_known_roots(self):
        roots = [self.roots]
        outside = self.write(os.path.join(self.tmp, "elsewhere", "notes.html"), "x")
        with self.assertRaises(Refused):
            actions.open_argv(outside, roots)
        with self.assertRaises(Refused):
            actions.open_argv(os.path.join(self.roots, "..", "elsewhere", "notes.html"), roots)
        link = os.path.join(self.roots, "sneaky")
        os.symlink(os.path.dirname(outside), link)
        with self.assertRaises(Refused):
            actions.open_argv(os.path.join(link, "notes.html"), roots)

    def test_refuses_anything_but_http_urls_and_absolute_paths(self):
        for value in ("file:///etc/passwd", "javascript:alert(1)", "ssh://host", "-a Terminal", "relative/path",
                      "https://", "https://x.example/a b"):
            with self.assertRaises(Refused, msg=value):
                actions.open_argv(value, [self.roots])

    def test_a_file_that_is_not_a_page_is_only_revealed(self):
        script = self.write(os.path.join(self.roots, "x", "run.command"), "echo hi")
        page = self.write(os.path.join(self.roots, "x", "plan.html"), "<p>")
        self.assertEqual(actions.open_argv(script, [self.roots]), ("reveal", ["open", "-R", os.path.realpath(script)]))
        self.assertEqual(actions.open_argv(page, [self.roots]), ("file", ["open", os.path.realpath(page)]))

    def test_a_failed_open_is_reported_not_raised(self):
        ws = self.workspace("x-20261023")
        self.flag("open-fail")
        done = api.open_target(self.items()[ws].id)
        self.assertFalse(done.opened)
        self.assertTrue(done.message.startswith("Could not open "))

    def test_a_bad_target_is_refused(self):
        ws = self.workspace("x-20261023")
        with self.assertRaises(InvalidInput):
            api.open_target(self.items()[ws].id, "/etc/passwd")
        with self.assertRaises(Refused):
            api.open_target(self.items()[ws].id, "pr")


class ProjectView(Studio):
    def test_sessions_rows_runs_and_folds(self):
        ws = self.workspace("x-20261023", tags=(("T01", "DONE"), ("T02", ""), ("T03", None)))
        self.agents([agent(SID_A, "ns-x-T02", ws)])
        self.transcript(SID_A, ws, title="ns-x-T02")
        self.old(self.transcript(SID_B, self.mkdir("work"), kind="interactive", title="Plan it"))
        found = self.items()
        studio = api.create_project("Studio")
        api.move_item(found[ws].id, studio.id)
        api.move_item(found[SID_B].id, studio.id)
        view = api.project_view(studio.id)
        [run] = view.runs
        self.assertEqual((run.word, run.detail, run.bar, run.terminal_item_id), ("Running", "T02 of 3", ["d", "r", ""],
                                                                               found[SID_A].id))
        rows = {s.item_id: s for s in view.sessions}
        self.assertEqual((rows[found[SID_A].id].kind, rows[found[SID_A].id].action), ("bg", "Open in Terminal"))
        self.assertTrue(rows[found[SID_A].id].age.startswith("working - "))
        self.assertEqual((rows[found[SID_B].id].kind, rows[found[SID_B].id].action), ("interactive", "Resume in Terminal"))
        self.assertEqual(rows[found[SID_B].id].age, "last active 1 h")
        self.assertFalse(view.sessions_folded)

    def test_all_idle_folds_the_sessions(self):
        self.old(self.transcript(SID_B, self.mkdir("work"), kind="interactive", title="Plan it"))
        found = self.items()
        studio = api.create_project("Studio")
        api.move_item(found[SID_B].id, studio.id)
        view = api.project_view(studio.id)
        self.assertTrue(view.sessions_folded)
        [fold] = view.folds
        self.assertEqual((fold.label, fold.count, fold.summary), ("Sessions", 1, "none active"))

    def test_header_crumbs_linked_text_and_tiles(self):
        top = api.create_project("Project Studio")
        sub = api.create_project("Studio MCP tools", top.id)
        other = api.create_project("night-sprint plugin")
        api.link_projects(top.id, other.id)
        api.refresh(force=True)
        view = api.project_view(top.id)
        self.assertEqual(view.linked, "Linked: night-sprint plugin")
        self.assertEqual([(t.name, t.text) for t in view.inside], [("Studio MCP tools", "no runs")])
        self.assertNotIn(other.id, [c["id"] for c in view.link_choices])
        self.assertEqual(api.project_view(sub.id).crumbs, [{"id": top.id, "name": "Project Studio"}])


class HeaderActions(Studio):
    def test_rename(self):
        a = api.create_project("Alpha")
        api.create_project("Beta")
        self.assertEqual(api.rename_project(a.id, "  Gamma ").name, "Gamma")
        with self.assertRaises(Refused):
            api.rename_project(a.id, "beta")
        with self.assertRaises(InvalidInput):
            api.rename_project(a.id, "")
        with self.assertRaises(Refused):
            api.rename_project(store.INBOX_ID, "Other")

    def test_archive_and_link(self):
        a, b = api.create_project("Alpha"), api.create_project("Beta")
        self.assertTrue(api.link_projects(a.id, b.id).created)
        self.assertEqual(api.get_project(a.id).linked_ids, [b.id])
        self.assertTrue(api.archive_project(a.id).archived_at)


class NoStopKillOrRemove(Studio):
    WORDS = re.compile(r"\b(kill|stop|rm|pkill|terminate)\b", re.I)

    def test_no_session_is_ever_stopped_killed_or_removed(self):
        import web
        from mcp_server import TOOLS
        for route in web.ACTIONS:
            self.assertIsNone(self.WORDS.search(route.replace("/", " ")), route)
        for tool in TOOLS:
            self.assertIsNone(self.WORDS.search(tool["name"].replace("_", " ")), tool["name"])
        for name in ("sdk/actions.py", "static/app.js"):
            text = open(os.path.join(STUDIO, name)).read()
            for word in ("claude stop", "claude kill", "pkill", "kill(", "os.kill", "/api/stop", "/api/kill"):
                self.assertNotIn(word, text, name)
