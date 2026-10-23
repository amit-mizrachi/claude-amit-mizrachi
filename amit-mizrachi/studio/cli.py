#!/usr/bin/env python3
"""project-studio - the Project Studio command line, a thin adapter over the SDK.

`bin/project-studio` is a shim that calls `main(argv)` here. Like `mcp_server.py` and `web.py`,
each command parses its arguments, calls ONE function of `sdk.api`, and formats the result. A
project or item named on the command line is first turned into its id with `api.resolve_project`
or `api.resolve_item` (that is parsing, not logic). No SQL, ranking or state rule lives here.

Adding a command (ticket 02 does this):
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
  2 on a usage error (argparse prints the usage on stderr).
- `project-studio` alone is `open`, and `open | status | stop` print what they printed before.

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


def pr_word(pr):
    """'PR #12 open', 'PR #9 draft', or '' for a run's PR dict."""
    if not pr or not pr.get("number"):
        return ""
    state = "draft" if pr.get("draft") and pr.get("state") == "open" else (pr.get("state") or "unknown")
    return "PR #%s %s" % (pr["number"], state)


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
        rows.append([short(p.id), name, line])
    return table(rows) + cut(len(result.projects), result.total)


def text_view(view):
    head = ["%s  %s" % (path(view.project.path), view.project.id)] + ([view.linked] if view.linked else [])
    body = section("Inside", [[short(t.project_id), t.name, t.text] for t in view.inside])
    body += section("Runs", [[short(r.item_id), r.word, r.title, r.detail, r.started, r.pr] for r in view.runs])
    body += section("Sessions", [[short(s.item_id), s.kind, s.title, s.age] for s in view.sessions])
    for fold in view.folds:
        if fold.kind != "sessions":     # the sessions fold has no rows of its own: they are view.sessions
            title = "%s %d - %s" % (fold.label, fold.count, fold.summary) if fold.summary else fold.label
            body += section(title, [[short(r.item_id), r.title, r.text] for r in fold.rows])
    body += section("Rules", [[r.id, r.description] for r in view.rules])
    return head + (body or ["", "Nothing filed here yet."])


def text_status(result):
    if isinstance(result, StudioServer):
        return text_server(result)
    head = ["%s  %s" % (path(result.project.path), result.project.id)]
    lines = section("Runs", [[short(r.item_id), r.status, r.title, (r.progress or {}).get("text") or "", r.stage,
                               r.reason, pr_word(r.pr)] for r in result.runs])
    lines += section("Inside", [[short(s.project.id), s.project.name, "%d runs, %d active" % (s.runs, s.runs_active)]
                                for s in result.sub_projects])
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
    rows = [[short(i.id), i.kind, i.status or "-", path(i.project_path), i.title + (" (gone)" if i.gone else "")]
            for i in result.items]
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


# ---------------------------------------------------------------- commands

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
    add_limit(parser, LIST_LIMIT)
    add_no_refresh(parser)


def setup_inbox(parser):
    add_limit(parser, LIST_LIMIT)
    add_no_refresh(parser)


def setup_refresh(parser):
    parser.add_argument("--force", action="store_true", help="re-read every source, due or not")


def setup_rules(parser):
    parser.add_argument("--project", help="only this project's rules")


COMMANDS = [
    Command("open", "Start the studio web page if it is not running, and open it in the browser.",
            "project-studio open", no_args, lambda a: api.open_studio(), text_server, after=open_browser),
    Command("stop", "Ask the running studio web server to stop.", "project-studio stop", no_args,
            lambda a: api.stop_studio(), text_server),
    Command("status", "Without a project: whether the studio server runs. With one: its night runs and items.",
            "project-studio status 'Project Studio'", setup_status, run_status, text_status),
    Command("list", "Print the project tree with each project's night-run line.", "project-studio list --all",
            setup_list, lambda a: api.list_projects(include_archived=a.all, limit=a.limit, with_runs=True), text_list),
    Command("show", "Print one project's view: sub-projects, runs, sessions, PRs, worktrees, artifacts, rules.",
            "project-studio show p_1a2b3c", setup_show,
            lambda a: api.project_view(project_ref(a.project), refresh=a.refresh), text_view),
    Command("find", "List items that match, newest activity first.", "project-studio find alpha --kind session-bg",
            setup_find, lambda a: api.find_items(query=a.query, kind=a.kind, project_id=project_ref(a.project),
                                                 include_gone=a.gone, limit=a.limit, refresh=not a.no_refresh),
            text_find),
    Command("inbox", "List unfiled items, newest first, with the suggested project.", "project-studio inbox --limit 20",
            setup_inbox, lambda a: api.inbox(limit=a.limit, refresh=not a.no_refresh), text_inbox),
    Command("refresh", "Re-read the due sources and say what changed and which sources failed.",
            "project-studio refresh --force", setup_refresh, lambda a: api.refresh(force=a.force), text_refresh),
    Command("rules", "List the filing rules, strongest signal first.", "project-studio rules --project 'Shapes evals'",
            setup_rules, lambda a: api.list_rules(project_ref(a.project)), text_rules),
]


# ---------------------------------------------------------------- parsing and the main loop

def parser():
    """The argparse parser: one sub-parser per Command, plus `help [command]`."""
    examples = "\n".join("  %-8s %s" % (c.name, c.example) for c in COMMANDS)
    top = argparse.ArgumentParser(
        prog=PROG, formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Project Studio: your projects, night runs and sessions, from the terminal. "
                    "With no command it runs `open`.",
        epilog="examples:\n%s\n  %-8s project-studio help show\n\n"
               "Exit codes: 0 ok, 1 a studio error, 2 a usage error. Projects are named by id, unique id prefix\n"
               "(4+ characters) or name (any case); items by id or unique id prefix." % (examples, "help"))
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
    if args.json:
        print(json.dumps(to_dict(result), indent=2, sort_keys=True))
    else:
        print("\n".join(command.text(result)))
    if command.after:
        command.after(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
