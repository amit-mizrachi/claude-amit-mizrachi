"""A night run's conductor (ticket 02): the reader, its attachment to the run, and Open conductor
through the SDK, the CLI and the MCP. Fixture homes and fixture transcripts only."""

import json
import os
import subprocess
import sys
import time

from sdk import api
from sdk.errors import InvalidInput, Refused
from sdk.readers import runs, sessions

from . import PLUGIN
from .support import Sources, validate
from .test_mcp_server import SERVER

SID_A = "11111111-1111-4111-8111-111111111111"
SID_B = "22222222-2222-4222-8222-222222222222"
SID_C = "33333333-3333-4333-8333-333333333333"
SID_D = "44444444-4444-4444-8444-444444444444"
BIN = os.path.join(PLUGIN, "bin", "project-studio")


def agent(sid, name, cwd):
    return {"id": sid[:8], "sessionId": sid, "name": name, "cwd": cwd, "state": "working", "kind": "background",
            "startedAt": int(time.time() * 1000) - 120000}


class Conductor(Sources):
    def items(self):
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}

    def old(self, path):
        then = time.time() - 3600
        os.utime(path, (then, then))
        return path

    def session(self, sid, cwd, title="", commands=(), stamp="2026-10-23T11:00:00.000Z"):
        """A bg session's transcript that ran each of `commands` with the Bash tool at `stamp`."""
        path = self.transcript(sid, cwd, title=title)
        with open(path, "a") as fh:
            for command in commands:
                fh.write(json.dumps({"type": "assistant", "timestamp": stamp, "sessionId": sid, "message": {
                    "role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Bash",
                                                      "input": {"command": command}}]}}) + "\n")
        return self.old(path)

    def run_with_file(self, ids):
        ws = self.workspace("x-20261023", files={"state/CONDUCTOR.session": "".join(i + "\n" for i in ids),
                                                 "state/T02.session": SID_B + "\n"})
        for sid in ids:
            self.session(sid, ws)
        self.session(SID_B, ws, title="ns-x-20261023-T02")
        return ws


class Reader(Conductor):
    def test_the_file_names_the_conductor_newest_last(self):
        ws = self.workspace("x-20261023", files={"state/CONDUCTOR.session": SID_A + "\n" + SID_C + "\n" + SID_A + "\n"})
        rec = runs.read_workspace(ws, runs.World())
        self.assertEqual(rec["conductor_session_id"], SID_A)          # a relay back to A: A is newest
        self.assertEqual(rec["conductor_session_ids"], [SID_C, SID_A])
        self.assertIn(SID_C, rec["sessions"])
        self.assertIn(SID_A, rec["sessions"])

    def test_a_relay_appends_and_the_newest_wins(self):
        ws = self.run_with_file([SID_A, SID_C])
        found = self.items()
        run = api.project_status("inbox", refresh=False).runs
        self.assertEqual([r.conductor_item_id for r in run if r.item_id == found[ws].id], [found[SID_C].id])

    def test_a_marathon_reuses_its_phase_conductor_file(self):
        ws = self.mkdir("roots", "m-20261023")
        self.write(os.path.join(ws, "phases", "PHASE_CHAIN"), "CONDUCTOR\n")
        self.write(os.path.join(ws, "phases", "state", "CONDUCTOR.session"), SID_D + "\n")
        self.write(os.path.join(ws, "facts.env"), "SLUG=m-20261023\nMARATHON_MODE=review\n")
        rec = runs.read_workspace(ws, runs.World())
        self.assertEqual((rec["kind"], rec["conductor_session_id"]), ("night-marathon", SID_D))

    def test_no_file_falls_back_to_the_session_that_ran_the_runner(self):
        ws = self.workspace("y-20261023", files={"state/T01.session": SID_B + "\n"})
        self.session(SID_A, "/tmp", commands=["bash %s/runner.sh start %s" % (ws, ws)],
                     stamp="2026-10-23T09:00:00.000Z")
        self.session(SID_C, "/tmp", commands=["bash %s/schedule.sh %s && echo ok" % (ws, ws)],
                     stamp="2026-10-23T12:00:00.000Z")
        self.session(SID_B, ws, title="ns-y-20261023-T01", commands=["bash %s/launch.sh %s T02" % (ws, ws)],
                     stamp="2026-10-23T13:00:00.000Z")         # a ticket session, listed in T01.session
        self.session(SID_D, ws, title="ns-y-20261023-T03", commands=["bash '%s/launch.sh' %s T04" % (ws, ws)],
                     stamp="2026-10-23T14:00:00.000Z")         # a ticket session by its name only
        found = self.items()
        self.assertEqual(found[ws].data["conductor_session_id"], SID_C)   # the newest that is no ticket
        self.assertEqual(found[SID_C].workspace_item_id, found[ws].id)

    def test_the_scan_reads_each_transcript_on_from_where_it_stopped(self):
        ws = self.workspace("z-20261023")
        path = self.session(SID_A, "/tmp", commands=["echo nothing here"])
        first = sessions.conductor_scan(None)
        self.assertEqual(first.records["files"][SID_A][1], os.path.getsize(path))
        self.assertEqual(first.records["files"][SID_A][2], {})
        with open(path, "a") as fh:
            fh.write(json.dumps({"type": "assistant", "timestamp": "2026-10-23T15:00:00.000Z", "message": {
                "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "%s/runner.sh start %s/"
                                                                                       % (ws, ws)}}]}}) + "\n")
            fh.write('{"type": "assistant", "half a line')
        again = sessions.conductor_scan(first.records)
        self.assertEqual(again.records["files"][SID_A][2], {ws: "2026-10-23T15:00:00.000Z"})
        self.assertLess(again.records["files"][SID_A][1], os.path.getsize(path))   # the half line waits


class Attachment(Conductor):
    def test_the_conductor_lives_with_its_run_and_follows_a_move(self):
        ws = self.run_with_file([SID_A])
        found = self.items()
        conductor = found[SID_A]
        self.assertEqual((conductor.workspace_item_id, conductor.placed_by), (found[ws].id, "title"))
        home = api.create_project("Machina")
        moved = api.move(found[ws].id, home.id)
        self.assertIn(conductor.id, moved.followed)
        self.assertNotIn(conductor.id, [e.item.id for e in api.inbox().entries])     # after a refresh too
        status = api.project_status(home.id, refresh=False)
        self.assertIn(conductor.id, [s.id for s in status.sessions])
        self.assertEqual(status.runs[0].conductor_item_id, conductor.id)

    def test_a_read_that_finds_no_conductor_keeps_the_known_one(self):
        ws = self.run_with_file([SID_A])
        found = self.items()
        os.unlink(os.path.join(ws, "state", "CONDUCTOR.session"))
        again = self.items()
        self.assertEqual(again[ws].data["conductor_session_id"], SID_A)
        self.assertEqual(again[SID_A].project_id, found[ws].project_id)


class OpenConductor(Conductor):
    def test_the_run_carries_it_on_home_and_the_project_view(self):
        ws = self.run_with_file([SID_A])
        found = self.items()
        home = api.create_project("Machina")
        api.move(found[ws].id, home.id)
        view = api.project_view(home.id)
        self.assertEqual(view.runs[0].conductor_item_id, found[SID_A].id)
        card = [c for c in api.home().cards if c.project.id == home.id][0]
        self.assertEqual(card.runs[0].conductor_item_id, found[SID_A].id)

    def test_open_in_terminal_stays_the_ticket_session_and_conductor_is_apart(self):
        ws = self.run_with_file([SID_A])
        self.agents([agent(SID_A, "", ws), agent(SID_B, "ns-x-20261023-T02", ws)])
        found = self.items()
        self.assertEqual(api.terminal_command(found[ws].id).item_id, found[SID_B].id)
        cmd = api.terminal_command(found[ws].id, target="conductor")
        self.assertEqual((cmd.item_id, cmd.mode, cmd.command), (found[SID_A].id, "attach", "claude attach 11111111"))
        opened = api.open_in_terminal(found[ws].id, target="conductor")
        self.assertTrue(opened.opened)
        self.assertEqual(opened.command.item_id, found[SID_A].id)

    def test_a_conductor_not_listed_resumes_in_its_folder(self):
        ws = self.run_with_file([SID_A])
        found = self.items()
        cmd = api.terminal_command(found[ws].id, target="conductor")
        self.assertEqual(cmd.command, "cd %s && claude --resume %s" % (ws, SID_A))

    def test_no_known_conductor_and_a_bad_target_are_refused(self):
        ws = self.workspace("q-20261023")
        self.session(SID_B, ws)
        found = self.items()
        with self.assertRaises(Refused):
            api.terminal_command(found[ws].id, target="conductor")
        with self.assertRaises(InvalidInput):
            api.terminal_command(found[SID_B].id, target="conductor")
        with self.assertRaises(InvalidInput):
            api.open_in_terminal(found[ws].id, target="boss")
        self.assertIsNone(api.project_status("inbox", refresh=False).runs[0].conductor_item_id)

    def test_cli_command_and_terminal_take_conductor(self):
        ws = self.run_with_file([SID_A])
        found = self.items()

        def cli(*argv):
            done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            return done.stdout

        self.assertEqual(cli("command", found[ws].id, "--conductor").strip(),
                         "cd %s && claude --resume %s" % (ws, SID_A))
        out = json.loads(cli("--json", "terminal", found[ws].id, "--conductor", "--yes"))
        self.assertEqual(out["command"]["item_id"], found[SID_A].id)
        self.assertIn("Conductors", cli("status", "inbox", "--no-refresh"))

    def test_mcp_status_shows_it_and_studio_terminal_opens_it(self):
        ws = self.run_with_file([SID_A])
        found = self.items()
        home = api.create_project("Machina")
        api.move(found[ws].id, home.id)
        calls = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": {"name": "studio_status", "arguments": {"project_id": home.id}}},
                 {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "studio_terminal",
                             "arguments": {"item_id": found[ws].id, "target": "conductor", "confirm": True}}}]
        done = subprocess.run([sys.executable, SERVER], input="".join(json.dumps(c) + "\n" for c in calls),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        out = {r["id"]: r for r in map(json.loads, done.stdout.splitlines())}
        tools = {t["name"]: t for t in out[1]["result"]["tools"]}
        status, opened = out[2]["result"]["structuredContent"], out[3]["result"]
        self.assertEqual(status["runs"][0]["conductor_item_id"], found[SID_A].id)
        self.assertEqual(validate(status, tools["studio_status"]["outputSchema"]), [])
        self.assertNotIn("isError", opened)
        self.assertEqual(opened["structuredContent"]["command"]["item_id"], found[SID_A].id)
        self.assertEqual(validate(opened["structuredContent"], tools["studio_terminal"]["outputSchema"]), [])


def cli_run(*argv):
    return subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True, timeout=60)


class OldConductor(Conductor):
    """Ticket 07: a run whose known conductor's transcript is older than sessions.RECENT_DAYS."""

    def aged(self, path, days=sessions.RECENT_DAYS + 6):
        then = time.time() - days * 86400
        os.utime(path, (then, then))
        return path

    def old_run(self):
        ws = self.run_with_file([SID_A])
        self.aged(self.transcript_path(SID_A, ws))
        return ws

    def transcript_path(self, sid, cwd):
        folder = "-" + cwd.strip("/").replace("/", "-")
        return os.path.join(self.claude_home, "projects", folder, sid + ".jsonl")

    def test_an_old_conductor_gets_its_item_attached_to_the_run(self):
        ws = self.old_run()
        found = self.items()
        conductor = found[SID_A]
        self.assertEqual((conductor.workspace_item_id, conductor.placed_by), (found[ws].id, "title"))
        self.assertEqual(conductor.data["cwd"], ws)
        home = api.create_project("Machina")
        self.assertIn(conductor.id, api.move(found[ws].id, home.id).followed)
        self.assertNotIn(conductor.id, [e.item.id for e in api.inbox().entries])   # after a refresh too
        again = self.items()                                     # the next sessions read keeps it
        self.assertFalse(again[SID_A].gone)
        self.assertEqual((again[SID_A].id, again[SID_A].project_id), (conductor.id, home.id))
        self.assertEqual(api.project_status(home.id, refresh=False).runs[0].conductor_item_id, conductor.id)

    def test_home_the_view_and_the_terminal_command_open_it(self):
        ws = self.old_run()
        found = self.items()
        home = api.create_project("Machina")
        api.move(found[ws].id, home.id)
        self.assertEqual(api.project_view(home.id).runs[0].conductor_item_id, found[SID_A].id)
        card = [c for c in api.home().cards if c.project.id == home.id][0]
        self.assertEqual(card.runs[0].conductor_item_id, found[SID_A].id)
        self.assertIn("open-conductor", [a.id for a in api.run_actions(found[ws].id).actions])
        cmd = api.terminal_command(found[ws].id, target="conductor")
        self.assertEqual(cmd.command, "cd %s && claude --resume %s" % (ws, SID_A))
        done = cli_run("command", found[ws].id, "--conductor")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "cd %s && claude --resume %s" % (ws, SID_A))

    def test_a_conductor_with_no_transcript_has_no_item_and_says_why(self):
        ws = self.workspace("gone-20261023", files={"state/CONDUCTOR.session": SID_C + "\n"})
        found = self.items()
        self.assertNotIn(SID_C, found)
        self.assertIsNone([r for r in api.project_status("inbox", refresh=False).runs
                           if r.item_id == found[ws].id][0].conductor_item_id)
        with self.assertRaises(Refused) as caught:
            api.terminal_command(found[ws].id, target="conductor")
        self.assertIn("no transcript on disk", str(caught.exception))
        done = cli_run("command", found[ws].id, "--conductor")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no transcript on disk", done.stderr + done.stdout)
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "studio_terminal", "arguments": {"item_id": found[ws].id, "target": "conductor"}}}
        out = subprocess.run([sys.executable, SERVER], input=json.dumps(call) + "\n", stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        result = json.loads(out.stdout.splitlines()[0])["result"]
        self.assertTrue(result["isError"])
        self.assertIn("no transcript on disk", result["content"][0]["text"])

    def test_a_transcript_not_read_yet_says_refresh_and_a_refresh_opens_it(self):
        ws = self.workspace("late-20261023", files={"state/CONDUCTOR.session": SID_C + "\n"})
        found = self.items()
        self.aged(self.session(SID_C, ws))                       # written after the last read
        with self.assertRaises(Refused) as caught:
            api.terminal_command(found[ws].id, target="conductor")
        self.assertIn("refresh and try again", str(caught.exception))
        self.items()
        self.assertEqual(api.terminal_command(found[ws].id, target="conductor").command,
                         "cd %s && claude --resume %s" % (ws, SID_C))


if __name__ == "__main__":
    import unittest
    unittest.main()
