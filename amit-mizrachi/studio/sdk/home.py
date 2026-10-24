"""The studio's home page: one full-width row per top-level project, and the bar above the rows.

Every rule the home page shows lives here, not in the web server or the page script:
- Rows are ordered by latest activity: the newest event among the project's own and its
  sub-projects' items (a run's newest state change, a session's last transcript write, a PR
  update). Ties go by name (any case), then id. A project with no runs and nothing new in
  `QUIET_DAYS` days (nor made in them) is quiet: quiet rows come last, and the page folds them
  into "n quiet projects". `order` is the row order; the page keeps it from the load on.
- A row says its status (its top run's), its night runs in words ("2 blocked, 1 running, 4 done")
  and its last activity ("12 min ago"), then at most 6 of its OWN runs, ranked needs-you >
  blocked > running > paused > latest change, then "+ n more".
- Each active sub-project is a block inside its parent's row, in tree order: glyph, status word,
  its runs in words, "2 inside" for the levels below it, and at most 3 runs of it and everything
  under it, then "+ n more"; a run that lives deeper says where ("in Inner"). Archived
  sub-projects do not show.
- A failed source gives a banner while its last read failed, and only then: a read in flight does
  not touch it, so it stays put through the polls until the source reads fine; its items keep
  their last-good state.
- The state is built from what the store holds and never waits for a read: a source still being
  read is named in the header's status line ("Reading PRs...") until it lands, and that line is
  "PRs 5 min ago" otherwise (`status_text`). Nothing else in the state changes for a read.
- The Inbox count leaves out items quiet for longer than `items.INBOX_DAYS`.
- A dismissed item shows nowhere here: not as a row's run, not in its PR line, not in a count,
  and its activity does not count.
"""

import time

from . import cache, items, model, store
from .reconcile import WORKSPACE_KINDS, item_data
from .results import HomeBanner, HomeCard, HomeRun, HomeState, HomeSubProject

MAX_RUNS = 6           # a row's own runs before "+ n more"
MAX_SUB_RUNS = 3       # a sub-project block's runs before "+ n more"
QUIET_DAYS = 14        # no runs and nothing new for longer: the row folds into "n quiet projects"
ACTIVITY_KEYS = ("changed_at", "last_active", "updated_at", "started_at")   # an item's activity stamps
GLYPHS = {"needs-you": "!", "blocked": "\u2717", "running": "\u25cf", "paused": "\u2016", "pending": "\u25cb",
          "done": "\u2713", "unknown": "?"}
WORDS = {"needs-you": "Waiting on you", "blocked": "Blocked", "running": "Running", "paused": "Paused",
         "pending": "Pending", "done": "Done", "unknown": "Unknown"}
COMMANDS = {"prs": "gh pr list", "agents": "claude agents", "jobs": "the jobs folder",
            "transcripts": "the session transcripts", "conductors": "the conductor scan",
            "worktrees": "git worktree list",
            "workspaces": "the workspace scan", "workspace": "a workspace's state files"}
CAPTION = "Latest activity first"
READING = {"prs": "PRs", "worktrees": "worktrees", "agents": "sessions", "jobs": "sessions",
           "transcripts": "sessions", "conductors": "sessions", "workspaces": "night runs", "workspace": "night runs"}


def ago(stamp, now):
    """'just now', '3 min ago', '2 h ago', '4 d ago' for an ISO 8601 UTC stamp; '' when unknown."""
    then = cache.epoch(stamp or "")
    if not then:
        return ""
    secs = max(0, int(now - then))
    if secs < 60:
        return "just now"
    if secs < 3600:
        return "%d min ago" % (secs // 60)
    if secs < 86400:
        return "%d h ago" % (secs // 3600)
    return "%d d ago" % (secs // 86400)


def clock(stamp):
    """Local 'HH:MM' for an ISO 8601 UTC stamp, '' when unknown."""
    then = cache.epoch(stamp or "")
    return time.strftime("%H:%M", time.localtime(then)) if then else ""


def pr_text(pr):
    """'PR #4102 draft - 2 checks red', 'PR #4127 open - checks green', 'PR #1182 merged', or ''."""
    if not pr or not pr.get("number"):
        return ""
    state = "draft" if pr.get("draft") and pr.get("state") == "open" else (pr.get("state") or "")
    parts = ["PR #%d %s" % (pr["number"], state or "unknown")]
    checks = pr.get("checks") or {}
    if state in ("open", "draft") and checks.get("total"):
        if checks.get("red"):
            parts.append("%d check%s red" % (checks["red"], "" if checks["red"] == 1 else "s"))
        elif checks.get("pending"):
            parts.append("checks running")
        else:
            parts.append("checks green")
    return " - ".join(parts)


def _ticket(name):
    return name[:1] == "T" and name[1:].isdigit()


def _stage_bar(run):
    """One cell per ticket stage: d done, r running, b blocked, w waiting on you, '' to do."""
    tickets = [s for s in run.stages if _ticket(s.get("name", ""))]
    total = (run.progress or {}).get("total") or len(tickets)
    cells = []
    for s in tickets[:total]:
        st = s.get("status")
        cells.append("d" if st in ("done", "skipped") else "b" if st == "blocked"
                     else ("w" if run.status == "needs-you" else "r") if st == "running" else "")
    return cells + [""] * (total - len(cells))


def _progress_text(run):
    """"T03 of 5"; once done, the tickets settled ("5 of 5"); blocked at a stage after the tickets
    (CI, FIX-FINAL), that stage ("at CI - 17 of 17 done"), so the last ticket is not named for it."""
    progress = run.progress or {}
    total = progress.get("total")
    if not total:
        return progress.get("text") or ""
    settled = _stage_bar(run).count("d")
    stage = next((s for s in run.stages if s.get("name") == run.stage), {})
    if run.status == "done":
        return "%d of %d" % (settled, total)
    if run.status == "blocked" and stage.get("status") == "blocked" and not _ticket(run.stage):
        return "at %s - %d of %d done" % (run.stage, settled, total)
    return progress.get("text") or ""


def home_run(run, actions=None):
    """A run as one card line: glyph, name, status word, reason, "T03 of 5", stage bar, Open plan, and
    its "..." menu (`actions`, `runmenu.for_run`'s list)."""
    from .runmenu import home_quick   # runmenu imports this module
    url = run.artifact_url if run.artifact_url.startswith(("https://", "http://")) else ""
    return HomeRun(item_id=run.item_id, title=run.title, status=run.status, glyph=GLYPHS.get(run.status, "?"),
                   word=WORDS.get(run.status, run.status.title()),
                   reason=run.reason if run.status in ("needs-you", "done") else "", progress=_progress_text(run) if run.status != "needs-you" else "",
                   bar=_stage_bar(run) if run.status != "needs-you" else [],
                   open_plan_url=url if run.status == "needs-you" else "", pr=pr_text(run.pr), gone=run.gone,
                   conductor_item_id=run.conductor_item_id, actions=list(actions or []),
                   quick=home_quick(run, actions or []))


def _more_text(hidden):
    if not hidden:
        return ""
    tail = ", all done" if all(r.status == "done" for r in hidden) else ""
    return "+ %d more%s" % (len(hidden), tail)


def _epoch(stamp):
    return cache.epoch(stamp[:19] + "Z") if isinstance(stamp, str) and len(stamp) >= 19 else 0


def _iso(then):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(then)) if then else ""


def activity(conn, tree):
    """{project id: epoch seconds of its newest activity, 0 for none}, over it and every active project
    under it: the newest changed_at / last_active / updated_at / started_at of any item it holds that
    is not dismissed (a run's state change, a session's last transcript write, a PR update)."""
    own = {}
    for r in conn.execute("SELECT project_id, data_json FROM items WHERE dismissed_at IS NULL"):
        data = item_data(r)
        own[r["project_id"]] = max([own.get(r["project_id"], 0)] + [_epoch(data.get(k)) for k in ACTIVITY_KEYS])
    return {pid: max(own.get(home, 0) for home in items.subtree(tree, pid)) for pid in tree.rows}


def ranking(conn, tree, now):
    """{project id: (quiet, newest activity epoch)}. Quiet: no night run (not gone, not dismissed) in it or
    under it, and neither activity nor a project made in it or under it in the last QUIET_DAYS days."""
    then = activity(conn, tree)
    marks = ",".join("?" * len(WORKSPACE_KINDS))
    with_runs = {r["project_id"] for r in conn.execute(
        "SELECT DISTINCT project_id FROM items WHERE gone_at IS NULL AND dismissed_at IS NULL AND kind IN (%s)"
        % marks, WORKSPACE_KINDS)}
    out = {}
    for pid in tree.rows:
        homes = items.subtree(tree, pid)
        made = max(_epoch(tree.rows[home]["created_at"]) for home in homes)
        quiet = not with_runs.intersection(homes) and now - max(then[pid], made) > QUIET_DAYS * 86400
        out[pid] = (quiet, then[pid])
    return out


def rank_key(tree, rank, pid):
    """The home order: active before quiet, newest activity first, then by name (any case), then id."""
    quiet, then = rank[pid]
    return (quiet, -then, tree.rows[pid]["name"].lower(), pid)


def activity_words(then, now):
    """'12 min ago' for an activity epoch, 'no activity yet' for 0."""
    return ago(_iso(then), now) if then else "no activity yet"


def by_activity(conn, projects, now=None):
    """`projects` (tree order) in the home order, and {id: '12 min ago'}. The Inbox stays first; each
    project with no ancestor in the list is placed by `rank_key`, and the ones under it follow it in
    tree order, so an indented list still reads as a tree."""
    now = time.time() if now is None else now
    tree = model.Tree(conn)
    rank = ranking(conn, tree, now)
    ids = {p.id for p in projects}

    def key(p):
        if p.is_inbox:
            return (0,)
        anchor = next((a for a in reversed(tree.ancestors(p.id)) if a in ids), p.id)
        return (1,) + rank_key(tree, rank, anchor)
    return sorted(projects, key=key), {p.id: activity_words(rank[p.id][1], now) for p in projects if not p.is_inbox}


def _active_children(tree, pid):
    """`pid`'s sub-projects that are not archived, in tree order (by name, any case)."""
    kids = [c for c in tree.children.get(pid, []) if not tree.rows[c]["archived_at"]]
    return sorted(kids, key=lambda c: (tree.rows[c]["name"].lower(), c))


def _holder(tree, pid, home):
    """The sub-project of `pid` that `home` is (or is under), or None when `home` is `pid` itself."""
    return next((p for p in [home] + tree.ancestors(home) if tree.rows[p]["parent_id"] == pid), None)


def _status_words(status):
    """(glyph, word) for a row's or block's status; a middle dot and '' with no runs."""
    if status == "pending":
        return "\u00b7", ""
    return GLYPHS.get(status, "?"), WORDS.get(status, status.title())


def _card_run(tree, pid, run, menus):
    """A run as a line in `pid`'s row or block, tagged "in <sub-project>" when it lives under `pid`."""
    line = home_run(run, menus.get(run.item_id))
    holder = _holder(tree, pid, run.project_id)
    if holder:
        line.sub_project_id, line.sub_project = holder, "in %s" % tree.rows[holder]["name"]
    return line


def _block(tree, sub, runs, menus):
    """A sub-project as a block in its parent's row; `runs` (ranked) are those of it and everything under it."""
    from .projectview import tile_state   # projectview imports this module
    status, text = tile_state(runs)
    glyph, word = _status_words(status)
    deeper = len(_active_children(tree, sub))
    return HomeSubProject(project_id=sub, name=tree.rows[sub]["name"], status=status, glyph=glyph, word=word,
                          text=text, inside="%d inside" % deeper if deeper else "",
                          runs=[_card_run(tree, sub, r, menus) for r in runs[:MAX_SUB_RUNS]],
                          more=_more_text(runs[MAX_SUB_RUNS:]))


def _card(tree, pid, runs, rank, now, menus):
    """`pid`'s row; `runs` (ranked) are those of it and everything under it; `menus` each run's actions."""
    from .projectview import tile_state   # projectview imports this module
    project = tree.project(pid)
    own = [r for r in runs if r.project_id == pid]
    blocks = []
    for sub in _active_children(tree, pid):
        homes = set(items.subtree(tree, sub))
        blocks.append(_block(tree, sub, [r for r in runs if r.project_id in homes], menus))
    status, counts = tile_state(runs)
    glyph, word = _status_words(status)
    pr = next((pr_text(r.pr) for r in runs[:MAX_RUNS] if pr_text(r.pr)), "")
    changed = max([r.updated_at for r in runs] + [project.updated_at])
    quiet, then = rank[pid]
    return HomeCard(project=project, sub_projects=blocks,
                    runs=[home_run(r, menus.get(r.item_id)) for r in own[:MAX_RUNS]],
                    more=_more_text(own[MAX_RUNS:]), pr=pr,
                    attention=status if status in ("needs-you", "blocked") else "",
                    empty="No night runs yet" if not runs else "", changed_at=changed, status=status,
                    glyph=glyph, word=word, counts=counts, last_activity_at=_iso(then),
                    last_activity=activity_words(then, now), quiet=quiet)


def _cards(conn, now):
    from . import runmenu   # runmenu imports this module
    tree = model.Tree(conn)
    shown = "dismissed_at IS NULL"
    every_pr = [items.to_item(dict(r), tree) for r in conn.execute("SELECT * FROM items WHERE kind = 'pr' AND " + shown)]
    arts = [items.to_item(dict(r), tree) for r in conn.execute("SELECT * FROM items WHERE kind = 'artifact' AND " + shown)]
    runs_by_home, known, menus = {}, items.session_ids(conn), {}
    marks = ",".join("?" * len(WORKSPACE_KINDS))
    for r in conn.execute("SELECT * FROM items WHERE gone_at IS NULL AND %s AND kind IN (%s)" % (shown, marks),
                          WORKSPACE_KINDS):
        run = items.to_run(items.to_item(dict(r), tree), every_pr, arts, known)
        runs_by_home.setdefault(run.project_id, []).append(run)
        menus[run.item_id] = runmenu.for_run(run, runmenu.has_plan(run, arts), runmenu.live_session(conn, run))
    rank = ranking(conn, tree, now)
    tops = [pid for pid in tree.children.get(None, []) if not tree.rows[pid]["archived_at"] and pid != store.INBOX_ID]
    tops.sort(key=lambda pid: rank_key(tree, rank, pid))
    return [_card(tree, pid, items.rank_runs([r for home in items.subtree(tree, pid)
                                              for r in runs_by_home.get(home, [])]), rank, now, menus) for pid in tops]


def quiet_text(cards):
    """'3 quiet projects', '1 quiet project', or '' when no row is quiet."""
    n = sum(1 for c in cards if c.quiet)
    return "%d quiet project%s" % (n, "" if n == 1 else "s") if n else ""


def _banner(entry, now):
    what = COMMANDS.get(entry.source, entry.source)
    where = entry.key.split("/")[-1] if entry.source in ("prs", "worktrees", "workspace") else ""
    head = "%s failed%s %s" % (what, " for " + where if where else "", ago(entry.fetched_at, now))
    if entry.source == "prs":
        kept = "PR states below are from %s." % clock(entry.good_at) if entry.good_at else "No PR states yet."
        return HomeBanner(source=entry.source, key=entry.key, text="%s - %s Run status is live." % (head, kept),
                          error=entry.error)
    kept = "showing what it said at %s." % clock(entry.good_at) if entry.good_at else "nothing read yet."
    return HomeBanner(source=entry.source, key=entry.key, text="%s - %s" % (head, kept), error=entry.error)


def _inbox_counts(conn, now):
    counts = {}
    for r in conn.execute("SELECT kind, data_json, seen_at FROM items WHERE project_id = ? AND gone_at IS NULL "
                          "AND dismissed_at IS NULL", (store.INBOX_ID,)):
        if items.recent(r, now):
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return counts


def reading_text(sources):
    """'Reading PRs...', 'Reading night runs and PRs...', or '' when nothing is read."""
    words = []
    for source in sources:
        word = READING.get(source, source)
        if word not in words:
            words.append(word)
    if not words:
        return ""
    return "Reading %s..." % (", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else words[0])


def _first_run_text(counts):
    sessions = counts.get("session-bg", 0) + counts.get("session-interactive", 0)
    runs = sum(counts.get(k, 0) for k in WORKSPACE_KINDS)
    parts = [p for p in ("%d session%s" % (sessions, "" if sessions == 1 else "s") if sessions else "",
                         "%d night run%s" % (runs, "" if runs == 1 else "s") if runs else "") if p]
    if not parts:
        return "Make a project, then drag sessions and night runs onto it."
    verb = "is" if sum(counts.values()) == 1 else "are"
    return "%s %s waiting in the Inbox. Make a project, then drag them onto it." % (" and ".join(parts), verb)


def archived(conn):
    """Every archived project as {"id", "name" (its path, "Alpha / Old"), "archived_at"}, in tree order.
    One archived under another is listed too: unarchiving it says to unarchive the outer one first."""
    tree = model.Tree(conn)
    found = sorted((tree.project(pid) for pid, row in tree.rows.items() if row["archived_at"]), key=model.order_key)
    return [{"id": p.id, "name": " / ".join(p.path), "archived_at": p.archived_at} for p in found]


def state(conn, now=None, reading=()):
    """The whole home page as one HomeState (what `GET /state` and every SSE event carry).
    `reading` names the sources being read right now (`refresh.reading()`). `loading` is False:
    the store answered, and only the page shows a skeleton before that."""
    now = time.time() if now is None else now
    entries = cache.entries(conn)
    prs = [e for (source, _), e in entries.items() if source == "prs"]
    prs_at = min((e.good_at for e in prs if e.good_at), default="")
    counts = _inbox_counts(conn, now)
    cards = _cards(conn, now)
    banners = [_banner(e, now) for _, e in sorted(entries.items()) if not e.ok]
    source_age = "PRs %s" % ago(prs_at, now) if prs_at else ""
    return HomeState(cards=cards, caption=CAPTION, inbox_count=sum(counts.values()),
                     source_age=source_age, status_text=reading_text(reading) or source_age,
                     loading=False, first_run=not cards, first_run_text=_first_run_text(counts),
                     banners=banners, reading=list(reading), reading_text=reading_text(reading),
                     generated_at=store.now_iso(), archived=archived(conn),
                     order=[c.project.id for c in cards], quiet_text=quiet_text(cards))
