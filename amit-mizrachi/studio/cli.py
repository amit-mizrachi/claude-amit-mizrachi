#!/usr/bin/env python3
"""project-studio - the Project Studio command line, a thin adapter over the SDK.

`bin/project-studio` is a shim that calls `main(argv)` here. Like `mcp_server.py` and `web.py`,
each command parses its arguments, calls ONE function of `sdk.api`, and formats the result. A
project or item named on the command line is first turned into its id with `api.resolve_project`
or `api.resolve_item` (that is parsing, not logic). No SQL, ranking or state rule lives here.

Adding a command:
- Add one `Command(name, summary, example, setup, run, text)` to COMMANDS.
  `setup(parser)` adds its arguments; `run(args)` returns the SDK result; `text(result)` returns
  the lines printed without `--json`. `after(result)` is an optional side step (`open` opens the
  browser).
- Name projects with `project_ref(value)` and items with `item_ref(value)`.
- Format with `short(id)` (8 characters), `table(rows)` (aligned ASCII columns, two spaces apart),
  `section(title, rows)` and `cut(shown, total)`.

Output and exit codes, the same for every command:
- Text by default, ASCII only from our side. `--json` (before or after the command) prints
  `to_dict(result)` with sort_keys, the shape the MCP tools return.
- 0 on success. 1 on an SDK error: `project-studio: <code>: <message>` on stderr, or with `--json`
  `{"error": {"code", "message", ...}}` on stdout (an ambiguous name adds `candidates`).
  2 on a usage error (argparse prints the usage on stderr), and when a command that needs `--yes`
  did not get it (`delete`; `terminal`, `throw` and `remove-project` without a tty): the message says what it
  would have done, code `confirm_needed`, on stderr or as `--json` error.
- A move (`file`, `add`, `accept`, `nest`, `remove`, `dismiss`, `restore`, `mark-done`, `undo`) prints
  its move id and the `undo` command. `command <item>` prints only the command, so `$(project-studio command <item>)` works.
- `project-studio` alone is `open`, and `open | status | stop` print what they printed before.
- `remove-project` prints what moved where, its move id and the `undo` command that brings it all back.
- `actions <run>` prints the run's actions menu, one line each: id, label, the command that does it.
- `rule-add` prints the rule and, with `--apply`, one move id and `undo` command per filed item;
  `--dry-run` saves nothing. `--branch-prefix` without `--repo` is a usage error (exit 2).

Zero dependencies. Python 3.9+. Data in `$PROJECT_STUDIO_HOME`, default `~/.project-studio`.
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sdk import api, store  # noqa: E402
from sdk.errors import StudioError  # noqa: E402
from sdk.results import StudioServer, to_dict  # noqa: E402

PROG = "project-studio"
SHORT = 8
LIST_LIMIT = 50
STATUS_LIMIT = 20


# ---------------------------------------------------------------- references and formatting helpers

def project_ref(value):
    """The id of the project `value` names (id, unique id prefix or name), or None for None."""
    return api.resolve_project(value).id if value is not None else None


def item_ref(value):
    """The id of the item `value` names (id or unique id prefix)."""
    return api.resolve_item(value).id


def short(value):
    return (value or "")[:SHORT]


def table(rows):
    """Rows of cells as aligned columns, two spaces apart; the last cell of a row is not padded."""
    rows = [[str(c if c is not None else "") for c in row] for row in rows]
    if not rows:
        return []
    widths = [max(len(row[i]) for row in rows if i < len(row)) for i in range(max(len(row) for row in rows))]
    return ["  ".join(c.ljust(widths[i]) if i < len(row) - 1 else c for i, c in enumerate(row)).rstrip()
            for row in rows]


def section(title, rows):
    """A blank line, the title, and the rows indented by two spaces; nothing when there are no rows."""
    return ["", title] + ["  " + line for line in table(rows)] if rows else []


def cut(shown, total):
    """The footer for a page cut by --limit, or nothing."""
    return ["(%d of %d shown - raise --limit for more)" % (shown, total)] if shown < total else []


def path(project_path):
    return " / ".join(project_path)


# ---------------------------------------------------------------- text for each result

def say(result):
    if result.running:
        return "Project Studio %s at %s (pid %d)" % ("started" if result.started else "runs", result.url, result.pid)
    return "Project Studio is not running."


def text_server(result):
    return [say(result)]


def text_list(result):
    rows = []
    for p in result.projects:
        name = "  " * (len(p.path) - 1) + p.name + (" (archived)" if p.archived_at else "")
        line = "%d item%s" % (p.item_count, "" if p.item_count == 1 else "s") if p.is_inbox \
            else result.run_lines.get(p.id, "")
        rows.append([short(p.id), name, line] + ([result.last_activity.get(p.id, "")] if result.last_activity else []))
    return table(rows) + cut(len(result.projects), result.total)


def run_groups(groups, row):
    """A heading per sub-project ("In Machina decision units  p_1a2b3c4d  1 blocked, 2 done"), one
    indent per level below the project, and its own runs under it as `row(run)` cells."""
    lines = []
    for g in groups:
        pad = "  " * (g.depth - 1)
        lines += ["", "%sIn %s  %s  %s" % (pad, g.name, short(g.project_id), g.text)]
        lines += [pad + "  " + line for line in table([row(r) for r in g.runs])]
    return lines


def view_run_row(r):
    return [short(r.item_id), r.word, r.title, r.detail, r.started, r.pr, r.pr_url]


def status_run_row(r):
    return [short(r.item_id), r.word, r.title, r.reason, r.progress_text, r.pr_text, r.pr_url]


def text_view(view):
    head = ["%s  %s" % (path(view.project.path), view.project.id)] + ([view.linked] if view.linked else [])
    body = section("Inside", [[short(t.project_id), t.name, t.text] for t in view.inside])
    body += section("Runs", [view_run_row(r) for r in view.runs])
    body += run_groups(view.sub_runs, view_run_row)
    body += section("Sessions", [[short(s.item_id), s.kind, s.title, s.age] for s in view.sessions])
    for fold in view.folds:
        if fold.kind != "sessions":     # the sessions fold has no rows of its own: they are view.sessions
            title = "%s %d - %s" % (fold.label, fold.count, fold.summary) if fold.summary else fold.label
            body += section(title, [[short(r.item_id), r.title, r.text] for r in fold.rows])
    body += section("Rules", [[r.id, r.description] for r in view.rules])
    if view.dismissed:
        fold = view.dismissed
        body += section("%s %d - %s (restore: %s restore <item>)" % (fold.label, fold.count, fold.summary, PROG),
                        [[short(r.item_id), r.title, r.text] for r in fold.rows])
    return head + (body or ["", "Nothing filed here yet."])


def text_status(result):
    if isinstance(result, StudioServer):
        return text_server(result)
    head = ["%s  %s" % (path(result.project.path), result.project.id)]
    lines = section("Runs", [status_run_row(r) for r in result.runs if r.project_id == result.project.id])
    lines += run_groups(result.groups, status_run_row)
    lines += section("Conductors (%s terminal <run> --conductor)" % PROG,
                     [[short(r.item_id), r.title, short(r.conductor_item_id)] for r in result.runs if r.conductor_item_id])
    lines += section("Inside", [[short(s.project.id), s.project.name, s.text] for s in result.sub_projects])
    lines += section("Sessions", [[short(i.id), i.kind, i.status or "-", i.title + (" (gone)" if i.gone else "")]
                                  for i in result.sessions])
    lines += section("Pull requests", [[short(i.id), i.status or "-", i.title] for i in result.prs])
    lines += section("Worktrees", [[short(i.id), i.title, i.key] for i in result.worktrees])
    lines += section("Artifacts", [[short(i.id), i.title, i.key] for i in result.artifacts])
    lines += section("Failed sources", [[s.source, s.key, s.error] for s in result.sources if not s.ok])
    if result.truncated:
        totals = ", ".join("%s %d" % (k, result.totals[k]) for k in ("runs", "sessions", "prs", "worktrees",
                                                                      "artifacts"))
        lines += ["", "(lists cut to --limit; totals: %s)" % totals]
    return head + (lines or ["", "No runs or items here yet."])


def text_find(result):
    rows = [[short(i.id), i.kind, i.status or "-", path(i.project_path),
             i.title + (" (gone)" if i.gone else "") + (" (dismissed)" if i.dismissed else "")] for i in result.items]
    return (table(rows) or ["No items match."]) + cut(len(result.items), result.total)


def text_inbox(result):
    rows = [[short(e.item.id), e.item.kind, e.item.title,
             "-> %s (%s)" % (e.suggestion.project_name, e.suggestion.reason) if e.suggestion else ""]
            for e in result.entries]
    return (table(rows) or ["The Inbox is empty."]) + cut(len(result.entries), result.total)


def text_refresh(result):
    lines = ["Read %d source%s: %d added, %d filed, %d gone, %d back." % (
        len(result.reads), "" if len(result.reads) == 1 else "s", result.added, result.filed, result.gone, result.back)]
    failed = [[s.source, s.key, s.error] for s in result.sources if not s.ok]
    return lines + (section("Failed sources", failed) if failed else ["Every source read fine."])


def text_rules(result):
    rows = [[r.id, r.project_name, r.signal, r.description] for r in result.rules]
    return table(rows) or ["No rules yet."]


def text_project(verb):
    """The text for a command that returns one Project: "Created Alpha / Docs  p_1a2b3c4d5e6f"."""
    return lambda project: ["%s %s  %s" % (verb, path(project.path), project.id)]


def text_delete(result):
    return ["Deleted %s  %s" % (result.name, result.id)]


def text_link(result):
    return ["%s %s and %s." % ("Linked" if result.created else "Already linked:", result.a_id, result.b_id)]


def text_unlink(result):
    if result.removed:
        return ["Unlinked %s and %s." % (result.a_id, result.b_id)]
    return ["Not linked: %s and %s. Nothing changed." % (result.a_id, result.b_id)]


def text_move(result):
    """The toast, then the move id and the command that undoes it; a filing adds the rule it could save.
    An item `add` created is not a move (it had no home before), so it names `remove` instead."""
    if result.created and result.item:
        return ["Added %s to %s  %s" % (result.item.title, path(result.item.project_path), result.item.id),
                "A new item, so there is no move to undo. Take it out: %s remove %s" % (PROG, result.item.id)]
    lines = [result.message or "Nothing moved."]
    if result.followed:
        verb = {"dismiss": "dismissed", "restore": "restored"}.get(result.kind, "moved")
        lines.append("%d attached item%s %s with it." % (len(result.followed), "" if len(result.followed) == 1
                                                        else "s", verb))
    if result.move_id is not None:
        lines.append("Move %d. Undo: %s undo %d" % (result.move_id, PROG, result.move_id))
        if result.rule_preview:
            lines.append("Always file items like this here (%s): %s rule-save %d" % (
                result.rule_preview.description, PROG, result.move_id))
    return lines


def text_rule(verb):
    def lines(rule):
        head = verb if verb != "Saved" or rule.created else "Already saved"
        return ["%s rule %s: %s -> %s" % (head, rule.id, rule.description, rule.project_name)]
    return lines


def text_rule_add(result):
    """add_rule's message, then the rule's id with its delete command, and one undo line per filed item."""
    lines = [result.message]
    if result.rule:
        lines.append("Rule %s. Delete it: %s rule-delete %s" % (result.rule.id, PROG, result.rule.id))
    for f in result.filed:
        lines.append("Move %d: %s. Undo: %s undo %d" % (f.move_id, f.title, PROG, f.move_id))
    return lines


def text_export(result):
    if result.path:
        return ["Wrote the store to %s" % result.path]
    return [json.dumps(result.document, indent=2, sort_keys=True)]


def text_purge(result):
    return ["Purged %d gone item%s%s" % (result.count, "" if result.count == 1 else "s",
                                        (": " + ", ".join(result.ids)) if result.ids else ".")]


def text_terminal(result):
    return [result.message, result.command.command]


def text_command(result):
    return [result.command]


def text_open_item(result):
    return [result.message]


# The command line that does each run action, so `actions` says what to type next.
ACTION_COMMANDS = {"open-plan": "open-item {run} --target plan", "open-pr": "open-item {run} --target pr",
                   "open-terminal": "terminal {target}", "open-conductor": "terminal {run} --conductor",
                   "move": "file {run} <project>", "mark-done": "mark-done {run}", "dismiss": "dismiss {run}",
                   "restore": "restore {run}", "throw-away": "throw {run}"}


def text_actions(result):
    """The run, then one line per action that applies: its id, label and the command that does it."""
    rows = [[a.id, a.label, "%s %s" % (PROG, ACTION_COMMANDS.get(a.id, a.id).format(run=result.item_id,
                                                                                    target=a.target_id))
             + ("  (removes things; asks first)" if a.destructive else "")] for a in result.actions]
    head = "%s  %s%s  %s" % (result.title, result.word, " (dismissed)" if result.dismissed else "", result.item_id)
    return [head] + ["  " + line for line in table(rows)]


def text_settings(result):
    return [result.message]


# ---------------------------------------------------------------- commands

class NeedsYes(Exception):
    """A command that needs `--yes` (or a y on a tty) before it acts: exit 2, the message says what it would do."""

    code = "confirm_needed"

    def to_dict(self):
        return {"code": self.code, "message": str(self)}


class UsageError(Exception):
    """Arguments argparse accepts but that do not go together: exit 2, like an argparse usage error."""

    code = "usage_error"

    def to_dict(self):
        return {"code": self.code, "message": str(self)}


class Command(object):
    def __init__(self, name, summary, example, setup, run, text, after=None):
        self.name, self.summary, self.example = name, summary, example
        self.setup, self.run, self.text, self.after = setup, run, text, after


def no_args(parser):
    pass


def open_browser(result):
    if sys.platform == "darwin":
        subprocess.run(["open", result.url], check=False)


def add_limit(parser, default):
    parser.add_argument("--limit", type=int, default=default, metavar="N",
                        help="show at most N (default %d, at most %d)" % (default, api.MAX_LIST_LIMIT))


def add_no_refresh(parser):
    parser.add_argument("--no-refresh", action="store_true", help="answer from the store; do not re-read due sources")


def setup_list(parser):
    parser.add_argument("--all", action="store_true", help="include archived projects")
    parser.add_argument("--by", choices=api.LIST_ORDERS, default="tree",
                        help="tree (default) or activity: latest activity first, as home orders its rows")
    add_limit(parser, api.MAX_LIST_LIMIT)


def setup_show(parser):
    parser.add_argument("project", help="project id, unique id prefix (4+ characters) or name")
    parser.add_argument("--refresh", action="store_true", help="re-read due sources first")


def setup_status(parser):
    parser.add_argument("project", nargs="?", help="project id, prefix or name; leave out for the studio server")
    add_limit(parser, STATUS_LIMIT)
    add_no_refresh(parser)


def run_status(args):
    if args.project is None:
        return api.studio_status()
    return api.project_status(project_ref(args.project), refresh=not args.no_refresh, limit=args.limit)


def setup_find(parser):
    parser.add_argument("query", nargs="?", help="text in the title, key, name, cwd or branch (any case)")
    parser.add_argument("--kind", choices=store.ITEM_KINDS, help="keep one kind")
    parser.add_argument("--project", help="keep items in this project or under it")
    parser.add_argument("--gone", action="store_true", help="include gone items")
    parser.add_argument("--dismissed", action="store_true", help="include dismissed items (marked, listed last)")
    parser.add_argument("--status", help="only night runs with this status: %s (needs-you is waiting on you)"
                        % ", ".join(api.RUN_STATUSES))
    add_limit(parser, LIST_LIMIT)
    add_no_refresh(parser)


def setup_inbox(parser):
    add_limit(parser, LIST_LIMIT)
    add_no_refresh(parser)


def setup_refresh(parser):
    parser.add_argument("--force", action="store_true", help="re-read every source, due or not")


def setup_rules(parser):
    parser.add_argument("--project", help="only this project's rules")


def setup_rule_add(parser):
    parser.add_argument("project", help="the project the rule files into: id, unique id prefix or name")
    signal = parser.add_mutually_exclusive_group(required=True)
    signal.add_argument("--workspace", metavar="GLOB", help="a night run's slug, as a glob: 'sis-*'")
    signal.add_argument("--repo", metavar="NAME", help="a repo folder name, matched exactly (every branch unless "
                                                       "--branch-prefix)")
    signal.add_argument("--cwd-prefix", metavar="FOLDER", help="a folder: what runs in it or under it")
    parser.add_argument("--branch-prefix", metavar="PREFIX", help="with --repo: branches that start with it ('eval/')")
    parser.add_argument("--apply", action="store_true", help="also file the matching Inbox items now, one undoable "
                                                             "move each")
    parser.add_argument("--dry-run", action="store_true", help="say how many items it would file, and which; "
                                                               "save nothing")


def run_rule_add(args):
    if args.branch_prefix is not None and args.repo is None:
        raise UsageError("--branch-prefix narrows a repo rule: add --repo <name>.")
    if args.workspace is not None:
        signal, pattern = "workspace", args.workspace
    elif args.repo is not None:
        signal, pattern = "repo-branch", " ".join(p for p in (args.repo, args.branch_prefix) if p)
    else:
        signal, pattern = "cwd", args.cwd_prefix
    return api.add_rule(project_ref(args.project), signal, pattern, apply=args.apply, dry_run=args.dry_run)


def add_project_arg(parser, name="project"):
    parser.add_argument(name, help="project id, unique id prefix (4+ characters) or name")


def add_item_arg(parser):
    parser.add_argument("item", help="item id or unique id prefix (4+ characters)")


def add_move_id(parser):
    parser.add_argument("move_id", type=int, help="the move id a filing printed")


def add_yes(parser, help):
    parser.add_argument("--yes", "-y", action="store_true", help=help)


def setup_create(parser):
    parser.add_argument("name", help="the new project's name")
    parser.add_argument("--under", metavar="PROJECT", help="create it under this project (default: top level)")


def setup_rename(parser):
    add_project_arg(parser)
    parser.add_argument("name", help="the new name")


def setup_delete(parser):
    add_project_arg(parser)
    add_yes(parser, "really delete it (an empty project only; archive one that holds anything)")


def run_delete(args):
    project = api.resolve_project(args.project)
    if not args.yes:
        raise NeedsYes("This deletes the project %s (%s) for good, with its links and rules. Run again with --yes."
                       % (path(project.path), project.id))
    return api.delete_project(project.id)


def setup_remove_project(parser):
    add_project_arg(parser)
    add_yes(parser, "remove it without asking")


def run_remove_project(args):
    """Without --yes: what is inside and where it goes, then y/N on a tty (confirm_needed without one)."""
    project_id = project_ref(args.project)
    result = api.remove_project(project_id, confirmed=args.yes)
    if not result.needs_confirm:
        return result
    if not sys.stdin.isatty():
        raise NeedsYes("%s Nothing was removed. Run again with --yes to do it." % result.message)
    if not ask(result.message + "\nRemove it?"):
        raise NeedsYes("Nothing was removed.")
    return api.remove_project(project_id, confirmed=True)


def text_remove_project(result):
    lines = [result.message]
    if result.move_id is not None:
        lines.append("Move %d. Undo: %s undo %d" % (result.move_id, PROG, result.move_id))
    return lines


def setup_nest(parser):
    add_project_arg(parser)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--under", metavar="PROJECT", help="the new parent project")
    where.add_argument("--top", action="store_true", help="move it to the top level")


def setup_link(parser):
    add_project_arg(parser, "a")
    add_project_arg(parser, "b")


def setup_unarchive(parser):
    parser.add_argument("project", help="the archived project's id or unique id prefix (4+ characters; "
                                        "`list --all` shows them)")


def setup_add(parser):
    parser.add_argument("kind", choices=store.ITEM_KINDS, help="the item's kind")
    parser.add_argument("key", help="its stable id: session UUID, folder path, https URL or file, owner/repo#n")
    add_project_arg(parser)
    parser.add_argument("--title", help="its title (default: from the key)")


def setup_file(parser):
    add_item_arg(parser)
    add_project_arg(parser)
    parser.add_argument("--revision", type=int, metavar="N", help="refuse when the item moved since revision N")


def setup_export(parser):
    parser.add_argument("dest", nargs="?", help="also write it to this file (mode 0600); without it, print it")


def setup_purge(parser):
    parser.add_argument("item", nargs="?", help="one gone item's id or prefix; leave out for every gone item")


def add_conductor(parser):
    parser.add_argument("--conductor", action="store_true",
                        help="a night run's conductor session (the one that set it up and watches it), "
                             "not its live ticket session")


def target_of(args):
    return "conductor" if args.conductor else "session"


def setup_terminal(parser):
    add_item_arg(parser)
    add_conductor(parser)
    add_yes(parser, "open it even when its transcript changed in the last 5 minutes")


def setup_command(parser):
    add_item_arg(parser)
    add_conductor(parser)


def ask(question):
    """True when the person at the terminal answers y; the question goes to stderr so stdout stays clean."""
    sys.stderr.write(question + " [y/N] ")
    sys.stderr.flush()
    return sys.stdin.readline().strip().lower() in ("y", "yes")


def run_terminal(args):
    item_id = item_ref(args.item)
    result = api.open_in_terminal(item_id, confirmed=args.yes, target=target_of(args))
    if not result.needs_confirm:
        return result
    if not sys.stdin.isatty():
        raise NeedsYes("%s Nothing ran. Run again with --yes to open it anyway." % result.message)
    if not ask("%s Open it anyway?" % result.message):
        raise NeedsYes("Nothing opened.")
    return api.open_in_terminal(item_id, confirmed=True, target=target_of(args))


def setup_throw(parser):
    add_item_arg(parser)
    add_yes(parser, "throw it away without asking")


def run_throw(args):
    """Without --yes: the plan, then y/N on a tty (confirm_needed without one)."""
    item_id = item_ref(args.item)
    result = api.throw_away(item_id, confirmed=args.yes)
    if not result.needs_confirm:
        return result
    if not sys.stdin.isatty():
        raise NeedsYes("%s Nothing was thrown away. Run again with --yes to do it." % result.message)
    if not ask("%s Throw it away?" % result.message):
        raise NeedsYes("Nothing was thrown away.")
    return api.throw_away(item_id, confirmed=True)


def text_throw(result):
    return [result.message]


def setup_settings(parser):
    parser.add_argument("name", nargs="?", choices=("terminal",), help="the setting: terminal")
    parser.add_argument("value", nargs="?", help="the new value: Terminal, iTerm or default; leave out to print it")


def run_settings(args):
    return api.set_terminal(args.value) if args.value is not None else api.settings()


def setup_open_item(parser):
    add_item_arg(parser)
    parser.add_argument("--target", choices=("default", "plan", "pr"), default="default",
                        help="plan: a night run's plan page, pr: its PR, default: the item itself")


COMMANDS = [
    Command("open", "Start the studio web page if it is not running, and open it in the browser.",
            "project-studio open", no_args, lambda a: api.open_studio(), text_server, after=open_browser),
    Command("stop", "Ask the running studio web server to stop.", "project-studio stop", no_args,
            lambda a: api.stop_studio(), text_server),
    Command("status", "Without a project: whether the studio server runs. With one: its night runs (each "
            "sub-project's under it, each with its PR's URL) and items.",
            "project-studio status 'Project Studio'", setup_status, run_status, text_status),
    Command("list", "Print the project tree with each project's night runs in words (\"2 blocked, 1 done\"); "
            "--by activity puts the latest activity first and says when (\"12 min ago\").", "project-studio list --by activity",
            setup_list, lambda a: api.list_projects(include_archived=a.all, limit=a.limit, with_runs=True, by=a.by),
            text_list),
    Command("show", "Print one project's view: sub-projects, its runs (each with its PR's URL), each "
            "sub-project's runs under it, sessions, PRs, worktrees, artifacts, rules.",
            "project-studio show p_1a2b3c", setup_show,
            lambda a: api.project_view(project_ref(a.project), refresh=a.refresh), text_view),
    Command("find", "List items that match, newest activity first.", "project-studio find alpha --kind session-bg",
            setup_find, lambda a: api.find_items(query=a.query, kind=a.kind, project_id=project_ref(a.project),
                                                 include_gone=a.gone, limit=a.limit, refresh=not a.no_refresh,
                                                 include_dismissed=a.dismissed, status=a.status),
            text_find),
    Command("inbox", "List unfiled items, newest first, with the suggested project.", "project-studio inbox --limit 20",
            setup_inbox, lambda a: api.inbox(limit=a.limit, refresh=not a.no_refresh), text_inbox),
    Command("refresh", "Re-read the due sources and say what changed and which sources failed.",
            "project-studio refresh --force", setup_refresh, lambda a: api.refresh(force=a.force), text_refresh),
    Command("rules", "List the filing rules, strongest signal first.", "project-studio rules --project 'Shapes evals'",
            setup_rules, lambda a: api.list_rules(project_ref(a.project)), text_rules),
    Command("create", "Create a project, top-level or under another.", "project-studio create Docs --under Alpha",
            setup_create, lambda a: api.create_project(a.name, project_ref(a.under)), text_project("Created")),
    Command("rename", "Give a project a new name.", "project-studio rename Docs 'Docs site'", setup_rename,
            lambda a: api.rename_project(project_ref(a.project), a.name), text_project("Renamed to")),
    Command("archive", "Archive a project and everything under it.", "project-studio archive 'Old work'",
            lambda p: add_project_arg(p), lambda a: api.archive_project(project_ref(a.project)),
            text_project("Archived")),
    Command("unarchive", "Bring an archived project back, with the sub-projects archived with it.",
            "project-studio unarchive p_1a2b3c", setup_unarchive,
            lambda a: api.unarchive_project(project_ref(a.project)), text_project("Unarchived")),
    Command("delete", "Delete an EMPTY project for good. Needs --yes; without it, says what it would delete.",
            "project-studio delete Scratch --yes", setup_delete, run_delete, text_delete),
    Command("remove-project", "Remove a project that holds things: its runs and items move to its parent (the "
            "Inbox for a top-level one), its sub-projects move up. Nothing on disk changes. Needs --yes or a y; "
            "undoable.", "project-studio remove-project Scratch --yes", setup_remove_project, run_remove_project,
            text_remove_project),
    Command("nest", "Move a project under another (--under) or to the top level (--top). Undoable.",
            "project-studio nest Docs --under Beta", setup_nest,
            lambda a: api.move(project_ref(a.project), None if a.top else project_ref(a.under)), text_move),
    Command("link", "Link two projects.", "project-studio link Alpha Beta", setup_link,
            lambda a: api.link_projects(project_ref(a.a), project_ref(a.b)), text_link),
    Command("unlink", "Remove the link between two projects. Not linked: changes nothing.",
            "project-studio unlink Alpha Beta", setup_link,
            lambda a: api.unlink_projects(project_ref(a.a), project_ref(a.b)), text_unlink),
    Command("add", "File an item into a project by hand: a session, folder, URL, file or PR. Undoable.",
            "project-studio add artifact https://claude.ai/artifact/abc Alpha", setup_add,
            lambda a: api.add_item(a.kind, a.key, project_ref(a.project), a.title), text_move),
    Command("file", "Move an item into a project by hand. Prints the move id for undo and rule-save.",
            "project-studio file i_1a2b3c4d Alpha", setup_file,
            lambda a: api.move_item(item_ref(a.item), project_ref(a.project), a.revision), text_move),
    Command("undo", "Put back what a move (file, add, accept, nest, remove, dismiss, restore, mark-done, "
            "remove-project) did.",
            "project-studio undo 42",
            add_move_id, lambda a: api.undo_move(a.move_id), text_move),
    Command("remove", "Take an item out of its project, back to the Inbox. It deletes nothing.",
            "project-studio remove i_1a2b3c4d", lambda p: add_item_arg(p),
            lambda a: api.remove_item(item_ref(a.item)), text_move),
    Command("dismiss", "Hide an item (a night run with its sessions, PRs, worktrees) from every list. "
            "Deletes nothing. Undoable.", "project-studio dismiss i_1a2b3c4d", lambda p: add_item_arg(p),
            lambda a: api.dismiss_item(item_ref(a.item)), text_move),
    Command("restore", "Show a dismissed item again (find --dismissed lists them). Undoable.",
            "project-studio restore i_1a2b3c4d", lambda p: add_item_arg(p),
            lambda a: api.restore_item(item_ref(a.item)), text_move),
    Command("mark-done", "Mark a night run done when its state files froze on a word no longer true. It shows Done, "
            "\"marked done by you\", until its files change again. Undoable.", "project-studio mark-done i_1a2b3c4d",
            lambda p: add_item_arg(p), lambda a: api.mark_done(item_ref(a.item)), text_move),
    Command("actions", "List what a night run's actions menu offers now (open plan / PR / terminal / conductor, "
            "move, mark done, dismiss, throw away), each with the command that does it. Changes nothing.",
            "project-studio actions i_1a2b3c4d", lambda p: add_item_arg(p),
            lambda a: api.run_actions(item_ref(a.item)), text_actions),
    Command("throw", "Throw away a night run: its folder to the Trash, its worktrees removed with git worktree "
            "remove (never forced), the run and its items out of the studio. Needs --yes or a y; refused while it runs.",
            "project-studio throw i_1a2b3c4d --yes", setup_throw, run_throw, text_throw),
    Command("accept", "File an Inbox item into its suggested project. Undoable.", "project-studio accept i_1a2b3c4d",
            lambda p: add_item_arg(p), lambda a: api.accept_suggestion(item_ref(a.item)), text_move),
    Command("rule-save", "Always file items like this here: save a rule from a filing's move id.",
            "project-studio rule-save 42", add_move_id, lambda a: api.save_rule_from_move(a.move_id),
            text_rule("Saved")),
    Command("rule-add", "Write a filing rule by pattern: a workspace glob, a repo (+ branch prefix) or a folder. "
            "Says how many Inbox items it files now; --apply files them, --dry-run saves nothing.",
            "project-studio rule-add Shapes --workspace 'sis-*' --dry-run", setup_rule_add, run_rule_add,
            text_rule_add),
    Command("rule-delete", "Delete one rule (ids from `rules`). Items it filed stay where they are.",
            "project-studio rule-delete r_1a2b3c4d5e6f", lambda p: p.add_argument("rule_id", help="the rule's id"),
            lambda a: api.delete_rule(a.rule_id), text_rule("Deleted")),
    Command("export", "Print the whole store as JSON, or write it to a file.", "project-studio export ~/studio.json",
            setup_export, lambda a: api.export_json(a.dest), text_export),
    Command("purge", "Delete gone items for good: one, or every gone item.", "project-studio purge", setup_purge,
            lambda a: api.purge_gone(item_ref(a.item) if a.item else None), text_purge),
    Command("terminal", "Open a session (or a night run's live session; --conductor: its conductor) in your "
            "terminal app (see settings). Asks y/N when it may be open.",
            "project-studio terminal i_1a2b3c4d", setup_terminal, run_terminal, text_terminal),
    Command("settings", "Print or set a setting. terminal: the app Open in Terminal uses (Terminal, iTerm, default).",
            "project-studio settings terminal iTerm", setup_settings, run_settings, text_settings),
    Command("command", "Print only the command that opens a session again (--conductor: a run's conductor), "
            "for $(...) and scripts.",
            "project-studio command i_1a2b3c4d --conductor", setup_command,
            lambda a: api.terminal_command(item_ref(a.item), target_of(a)), text_command),
    Command("open-item", "Open an item: a URL in the browser, a folder in Finder, a file in its app.",
            "project-studio open-item i_1a2b3c4d --target plan", setup_open_item,
            lambda a: api.open_target(item_ref(a.item), a.target), text_open_item),
]


# ---------------------------------------------------------------- parsing and the main loop

def parser():
    """The argparse parser: one sub-parser per Command, plus `help [command]`."""
    examples = "\n".join("  %-11s %s" % (c.name, c.example) for c in COMMANDS)
    top = argparse.ArgumentParser(
        prog=PROG, formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Project Studio: your projects, night runs and sessions, from the terminal. "
                    "With no command it runs `open`.",
        epilog="examples:\n%s\n  %-11s project-studio help show\n\n"
               "Exit codes: 0 ok, 1 a studio error, 2 a usage error or a missing --yes.\n"
               "Projects are named by id, unique id prefix (4+ characters) or name (any case); items by id or\n"
               "unique id prefix. A filing prints its move id: `project-studio undo <id>` puts it back."
               % (examples, "help"))
    top.add_argument("--json", action="store_true", help="print the result as JSON (the MCP tools' shape)")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="print the result as JSON (the MCP tools' shape)")
    subs = top.add_subparsers(dest="command", metavar="<command>")
    for c in COMMANDS:
        sub = subs.add_parser(c.name, parents=[common], help=c.summary, description=c.summary,
                              epilog="example:\n  %s" % c.example, formatter_class=argparse.RawDescriptionHelpFormatter)
        c.setup(sub)
    helper = subs.add_parser("help", help="Show this help, or one command's help.", description="Show help.",
                             epilog="example:\n  project-studio help find",
                             formatter_class=argparse.RawDescriptionHelpFormatter)
    helper.add_argument("topic", nargs="?", choices=[c.name for c in COMMANDS], metavar="command")
    return top, subs


def emit_error(args, exc):
    if getattr(args, "json", False):
        print(json.dumps({"error": exc.to_dict()}, indent=2, sort_keys=True))
    else:
        sys.stderr.write("%s: %s: %s\n" % (PROG, exc.code, exc))
    return 1


def main(argv):
    top, subs = parser()
    try:
        args = top.parse_args(argv)
    except SystemExit as exc:      # argparse: --help exits 0, a usage error exits 2
        return exc.code if isinstance(exc.code, int) else 2
    if args.command == "help":
        (subs.choices[args.topic] if args.topic else top).print_help()
        return 0
    command = {c.name: c for c in COMMANDS}[args.command or "open"]
    try:
        result = command.run(args)
    except StudioError as exc:
        return emit_error(args, exc)
    except (NeedsYes, UsageError) as exc:
        emit_error(args, exc)
        return 2
    if args.json:
        print(json.dumps(to_dict(result), indent=2, sort_keys=True))
    else:
        print("\n".join(command.text(result)))
    if command.after:
        command.after(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
