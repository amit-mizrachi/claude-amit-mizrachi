"""The studio's home page: one card per top-level project, and the bar above the cards.

Every rule the home page shows lives here, not in the web server or the page script:
- A card shows at most 3 night runs of the project and everything under it, ranked
  needs-you > blocked > running > paused > latest change, then "+ n earlier runs".
- Cards are ordered needs-you first, then blocked, then running, then by latest change.
- A card lists its active sub-projects in tree order, each a line of its own (glyph, status word,
  "1 blocked, 2 done" / "no runs", "2 inside" for the levels below it); a run that lives in one
  says which ("in Machina decision units"). Archived sub-projects do not show.
- A failed source gives a banner; its items keep their last-good state.
- The state is built from what the store holds and never waits for a read: a source still being
  read is named in a quiet note ("Still reading PRs...") until it lands.
- The Inbox count leaves out items quiet for longer than `items.INBOX_DAYS`.
- A dismissed item shows nowhere here: not as a card's run, not in its PR line, not in a count.
"""

import time

from . import cache, items, model, store
from .reconcile import WORKSPACE_KINDS
from .results import HomeBanner, HomeCard, HomeRun, HomeState, HomeSubProject

MAX_RUNS = 3
CARD_RANK = {"needs-you": 0, "blocked": 1, "running": 2}
GLYPHS = {"needs-you": "!", "blocked": "\u2717", "running": "\u25cf", "paused": "\u2016", "pending": "\u25cb",
          "done": "\u2713", "unknown": "?"}
WORDS = {"needs-you": "Waiting on you", "blocked": "Blocked", "running": "Running", "paused": "Paused",
         "pending": "Pending", "done": "Done", "unknown": "Unknown"}
COMMANDS = {"prs": "gh pr list", "agents": "claude agents", "jobs": "the jobs folder",
            "transcripts": "the session transcripts", "worktrees": "git worktree list",
            "workspaces": "the workspace scan", "workspace": "a workspace's state files"}
CAPTION = "Needs you first, then running, then latest change"
READING = {"prs": "PRs", "worktrees": "worktrees", "agents": "sessions", "jobs": "sessions",
           "transcripts": "sessions", "workspaces": "night runs", "workspace": "night runs"}


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


def home_run(run):
    """A run as one card line: glyph, name, status word, reason, "T03 of 5", stage bar, Open plan."""
    url = run.artifact_url if run.artifact_url.startswith(("https://", "http://")) else ""
    return HomeRun(item_id=run.item_id, title=run.title, status=run.status, glyph=GLYPHS.get(run.status, "?"),
                   word=WORDS.get(run.status, run.status.title()),
                   reason=run.reason if run.status in ("needs-you", "done") else "", progress=_progress_text(run) if run.status != "needs-you" else "",
                   bar=_stage_bar(run) if run.status != "needs-you" else [],
                   open_plan_url=url if run.status == "needs-you" else "", pr=pr_text(run.pr), gone=run.gone)


def _more_text(hidden):
    if not hidden:
        return ""
    noun = "run" if len(hidden) == 1 else "runs"
    tail = ", all done" if all(r.status == "done" for r in hidden) else ""
    return "+ %d earlier %s%s" % (len(hidden), noun, tail)


def _active_children(tree, pid):
    """`pid`'s sub-projects that are not archived, in tree order (by name, any case)."""
    kids = [c for c in tree.children.get(pid, []) if not tree.rows[c]["archived_at"]]
    return sorted(kids, key=lambda c: (tree.rows[c]["name"].lower(), c))


def _holder(tree, pid, home):
    """The sub-project of `pid` that `home` is (or is under), or None when `home` is `pid` itself."""
    return next((p for p in [home] + tree.ancestors(home) if tree.rows[p]["parent_id"] == pid), None)


def _sub_line(tree, sub, runs):
    """A sub-project as its card line; `runs` (ranked) are the card's runs."""
    from .projectview import tile_state   # projectview imports this module
    homes = set(items.subtree(tree, sub))
    status, text = tile_state([r for r in runs if r.project_id in homes])
    deeper = len(_active_children(tree, sub))
    return HomeSubProject(project_id=sub, name=tree.rows[sub]["name"], status=status,
                          glyph="\u00b7" if status == "pending" else GLYPHS.get(status, "?"),
                          word="" if status == "pending" else WORDS.get(status, status.title()),
                          text=text, inside="%d inside" % deeper if deeper else "")


def _card_run(tree, pid, run):
    line = home_run(run)
    holder = _holder(tree, pid, run.project_id)
    if holder:
        line.sub_project_id, line.sub_project = holder, "in %s" % tree.rows[holder]["name"]
    return line


def _card(tree, pid, runs):
    project = tree.project(pid)
    shown, hidden = runs[:MAX_RUNS], runs[MAX_RUNS:]
    top = shown[0].status if shown else None
    pr = next((pr_text(r.pr) for r in shown if pr_text(r.pr)), "")
    changed = max([r.updated_at for r in runs] + [project.updated_at])
    return HomeCard(project=project, sub_projects=[_sub_line(tree, c, runs) for c in _active_children(tree, pid)],
                    runs=[_card_run(tree, pid, r) for r in shown], more=_more_text(hidden), pr=pr,
                    attention="needs-you" if top == "needs-you" else "blocked" if top == "blocked" else "",
                    empty="No night runs yet" if not runs else "", changed_at=changed)


def _cards(conn):
    tree = model.Tree(conn)
    shown = "dismissed_at IS NULL"
    every_pr = [items.to_item(dict(r), tree) for r in conn.execute("SELECT * FROM items WHERE kind = 'pr' AND " + shown)]
    arts = [items.to_item(dict(r), tree) for r in conn.execute("SELECT * FROM items WHERE kind = 'artifact' AND " + shown)]
    runs_by_home = {}
    marks = ",".join("?" * len(WORKSPACE_KINDS))
    for r in conn.execute("SELECT * FROM items WHERE gone_at IS NULL AND %s AND kind IN (%s)" % (shown, marks),
                          WORKSPACE_KINDS):
        run = items.to_run(items.to_item(dict(r), tree), every_pr, arts)
        runs_by_home.setdefault(run.project_id, []).append(run)
    cards = []
    for pid in tree.children.get(None, []):
        row = tree.rows[pid]
        if row["archived_at"] or pid == store.INBOX_ID:
            continue
        runs = [r for home in items.subtree(tree, pid) for r in runs_by_home.get(home, [])]
        cards.append(_card(tree, pid, items.rank_runs(runs)))
    cards.sort(key=lambda c: c.changed_at, reverse=True)
    cards.sort(key=lambda c: CARD_RANK.get(c.runs[0].status if c.runs else "", len(CARD_RANK)))
    return cards


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
    """'Still reading PRs...', 'Still reading night runs and PRs...', or '' when nothing is read."""
    words = []
    for source in sources:
        word = READING.get(source, source)
        if word not in words:
            words.append(word)
    if not words:
        return ""
    return "Still reading %s..." % (", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else words[0])


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
    cards = _cards(conn)
    banners = [_banner(e, now) for _, e in sorted(entries.items()) if not e.ok]
    return HomeState(cards=cards, caption=CAPTION, inbox_count=sum(counts.values()),
                     source_age="PRs %s" % ago(prs_at, now) if prs_at else "",
                     loading=False, first_run=not cards, first_run_text=_first_run_text(counts),
                     banners=banners, reading=list(reading), reading_text=reading_text(reading),
                     generated_at=store.now_iso(), archived=archived(conn))
