"""The studio's project view (`#/p/<id>`): header, sub-project tiles, run panels, sessions, folds.

Every rule the project view shows lives here, not in the web server or the page script:
- Runs are ranked as on the card (needs-you > blocked > running > paused > latest); a run panel
  shows its links after its name (`runmenu.links`: its PR "#733", Open plan, Open conductor) and
  offers Open in Terminal (a ticket session of it is still listed by `claude agents`).
- A bg session still listed opens ("Open in Terminal"); an interactive or removed one resumes.
- Sessions fold into "Everything else" when none is active; PRs, worktrees and artifacts always do.
- Gone PRs, worktrees and artifacts are left out; gone sessions show greyed, "(removed)".
- The project's own attach rules are listed, strongest signal first, each one deletable.
- A Blocked or Waiting-on-you run panel offers "Mark done" (`can_mark_done`); a run marked done
  shows Done, "marked done by you", until its files change.
- Each run panel carries its "..." menu, `actions`: `runmenu.for_run`'s list, the same one home's
  run lines and `run_actions` give; the buttons on the panel are drawn from it too.
- Under the project's own run panels, each active sub-project (at every depth, one indent per
  level) is a section: its header (glyph and word of its runs rolled up worst first, counts in words over it and
  everything under it, "2 blocked, 1 running, 4 done") and its own run panels, at most 5 before
  "+ n more". It starts open when a needs-you, blocked or running run is in it or under it.
  Archived sub-projects are left out.
- Dismissed items leave every list above and fold into "Dismissed" at the bottom, each row with
  Restore; a run's attached items went with it, so they show here too.
"""

import os
import time

from . import cache, items, model, runstatus, store
from .runmenu import for_run, has_plan as run_has_plan, links as run_links, live_session
from .reconcile import WORKSPACE_KINDS
from .home import MOVING, _active_children, _progress_text, _stage_bar, clock, pr_text
from .results import ProjectView, RunGroup, ViewFold, ViewRow, ViewRun, ViewSession, ViewTile

FINISHED = ("done", "finished", "completed", "failed", "error", "stopped", "exited")
SESSION_GLYPHS = {"running": "\u25cf", "done": "\u2713", "pending": "\u00b7", "unknown": "\u25cb"}
OPEN, RESUME = "Open in Terminal", "Resume in Terminal"


def span(stamp, now):
    """'just now', '2 min', '3 h', '1 d' since an ISO 8601 UTC stamp; '' when unknown."""
    then = cache.epoch(stamp or "")
    if not then:
        return ""
    secs = max(0, int(now - then))
    if secs < 60:
        return "just now"
    if secs < 3600:
        return "%d min" % (secs // 60)
    if secs < 86400:
        return "%d h" % (secs // 3600)
    return "%d d" % (secs // 86400)


def _join(*parts):
    return " - ".join(p for p in parts if p)


# ---------------------------------------------------------------- sessions

def session_state(item):
    """(status, phrase, stamp, action) for a session: working / finished / active / last active / gone."""
    d = item.data
    last = d.get("last_active") or d.get("started_at") or ""
    if item.gone or d.get("status") == "removed":
        return "unknown", "gone", item.gone_at or last, RESUME
    if item.kind == "session-interactive":
        if d.get("recently_active"):
            return "running", "active", last, RESUME
        return "pending", "last active", last, RESUME
    if d.get("status") == "unknown":
        return "unknown", "status unknown, last active", last, OPEN
    if str(d.get("status") or "").lower() in FINISHED:
        return "done", "finished", last, OPEN
    return "running", "working", last, OPEN


def view_session(item, now):
    status, phrase, stamp, action = session_state(item)
    gone = item.gone or item.data.get("status") == "removed"
    when = span(stamp, now)
    age = ("%s %s" % (phrase, when) if phrase == "last active" else _join(phrase, when)) if when else phrase
    return ViewSession(item_id=item.id, kind="bg" if item.kind == "session-bg" else "interactive",
                       title=item.title + (" (removed)" if gone else ""), status=status,
                       glyph=SESSION_GLYPHS[status], age=age, action=action, gone=gone)


# ---------------------------------------------------------------- runs and tiles

def _detail(run):
    """Where a running or paused run is ("REDRAW - T03 of 5"); every other status's reason."""
    if run.status not in MOVING:
        return run.reason
    current = (run.progress or {}).get("current") or ""
    stage = run.stage if run.stage and run.stage != current else ""
    return _join(stage, _progress_text(run))


def view_run(conn, run, arts):
    """`run` as a ViewRun; `arts`: the artifacts that are not dismissed, gone ones too (`has_plan`)."""
    live = live_session(conn, run)
    has_plan = run_has_plan(run, arts)
    menu = for_run(run, has_plan, live)
    started = clock(run.started_at) if run.status not in runstatus.SETTLED else ""
    return ViewRun(item_id=run.item_id, title=run.title, status=run.status, glyph=run.glyph,
                   word=run.word, detail=_detail(run),
                   bar=_stage_bar(run) if run.status != "needs-you" else [],
                   started="started %s" % started if started else "", pr=pr_text(run.pr),
                   has_plan=has_plan, has_pr=bool(run.pr and run.pr.get("url")),
                   terminal_item_id=live, gone=run.gone,
                   can_mark_done=run.status in runstatus.MARKABLE and not run.gone,
                   conductor_item_id=run.conductor_item_id if not run.gone else None,
                   actions=menu, quick=[], pr_url=run.pr_url, pr_number=run.pr_number,
                   pr_state=run.pr_state, links=run_links(run, menu))


def view_tile(sub):
    status = runstatus.NO_RUNS if not sub.runs else sub.top_status or "unknown"
    glyph = runstatus.roll_up_words(status)[0]
    return ViewTile(project_id=sub.project.id, name=sub.project.name, status=status, glyph=glyph, text=sub.text)


def run_lines(conn, project_ids):
    """Each project's night-run line, rolled up over its active sub-projects as its row says it, worst
    first ("1 waiting on you, 1 in review, 1 merged"), "no runs". The Inbox gets none."""
    tree = model.Tree(conn)
    prs = items.every_pr(conn, tree)
    marks = ",".join("?" * len(WORKSPACE_KINDS))
    every = [items.to_run(items.to_item(dict(r), tree), prs, [])
             for r in conn.execute("SELECT * FROM items WHERE dismissed_at IS NULL AND kind IN (%s)" % marks,
                                   WORKSPACE_KINDS)]
    lines = {}
    for pid in project_ids:
        if pid == store.INBOX_ID:
            continue
        homes = set(items.subtree(tree, pid))
        lines[pid] = runstatus.counts_text([r for r in every if r.project_id in homes])
    return lines


# ---------------------------------------------------------------- sub-project sections

SECTION_RUNS = 5                                    # run panels a section shows before "+ n more"
OPEN_STATUSES = ("needs-you", "blocked", "running")  # a section with one of these, in it or under it, starts open


def run_groups(tree, project_id, runs, panel=None):
    """One `RunGroup` per active sub-project of `project_id`, at every depth, in tree order (a
    sub-project, then its own sub-projects, one level deeper): its header (status glyph and word of
    its runs rolled up worst first, counts in words over it and everything under it, whether it starts open) and its
    OWN runs, ranked as `runs` are. `panel(run)` turns each run into what the caller shows (a
    `ViewRun` for the page); None keeps the `Run`."""
    out = []

    def walk(pid, depth):
        for child in _active_children(tree, pid):
            under = set(items.subtree(tree, child))
            mine = [r for r in runs if r.project_id in under]
            own = [r for r in mine if r.project_id == child]
            status, text = runstatus.roll_up(mine), runstatus.counts_text(mine)
            glyph, word = runstatus.roll_up_words(status)
            hidden = len(own) - SECTION_RUNS
            out.append(RunGroup(project_id=child, name=tree.rows[child]["name"], parent_id=pid, depth=depth,
                                status=status, glyph=glyph, word=word, text=text,
                                open=any(r.status in OPEN_STATUSES and not r.gone for r in mine),
                                runs=[panel(r) if panel else r for r in own], shown=min(len(own), SECTION_RUNS),
                                more="+ %d more" % hidden if hidden > 0 else ""))
            walk(child, depth + 1)

    walk(project_id, 1)
    return out


# ---------------------------------------------------------------- folds

def _pr_state(item):
    d = item.data
    return "draft" if d.get("draft") and d.get("state") == "open" else (d.get("state") or "unknown")


def _counted(states):
    order = []
    for s in states:
        if s not in order:
            order.append(s)
    if len(order) == 1:
        return order[0] if len(states) == 1 else "all %s" % order[0]
    return ", ".join("%d %s" % (states.count(s), s) for s in order)


def pr_fold(prs):
    rows = [ViewRow(item_id=p.id, title=p.title, text=pr_text(p.data).split(" ", 2)[-1] or _pr_state(p), action="Open")
            for p in prs]
    return ViewFold(kind="prs", label="Pull requests", count=len(prs), summary=_counted([_pr_state(p) for p in prs]),
                    rows=rows)


def _in_use(tree, live_cwds):
    path = tree.key.rstrip("/") + "/"
    return any((c.rstrip("/") + "/").startswith(path) for c in live_cwds)


def worktree_fold(trees, live_cwds):
    used = [t for t in trees if _in_use(t, live_cwds)]
    summary = ("%d in use" % len(used)) if used else ("idle" if len(trees) == 1 else "all idle")
    rows = [ViewRow(item_id=t.id, title=t.title, text="in use" if t in used else "idle", action="Show in Finder")
            for t in trees]
    return ViewFold(kind="worktrees", label="Worktrees", count=len(trees), summary=summary, rows=rows)


def _artifact_name(item):
    return "plan page" if item.data.get("plan") else item.title


def artifact_fold(arts):
    arts = sorted(arts, key=lambda a: a.data.get("updated_at") or "", reverse=True)
    newest = arts[0]
    at = clock(newest.data.get("updated_at"))
    rows = [ViewRow(item_id=a.id, title=_artifact_name(a), text="updated %s" % clock(a.data["updated_at"])
                    if a.data.get("updated_at") else "", action="Open") for a in arts]
    return ViewFold(kind="artifacts", label="Artifacts", count=len(arts),
                    summary="%s, updated %s" % (_artifact_name(newest), at) if at else _artifact_name(newest), rows=rows)


def folds(sessions, folded, prs, trees, arts, live_cwds):
    out = []
    if folded and sessions:
        out.append(ViewFold(kind="sessions", label="Sessions", count=len(sessions), summary="none active", rows=[]))
    if prs:
        out.append(pr_fold(prs))
    if trees:
        out.append(worktree_fold(trees, live_cwds))
    if arts:
        out.append(artifact_fold(arts))
    return out


DISMISSED_WORDS = {"session-bg": ("session", "sessions"), "session-interactive": ("session", "sessions"),
                   "night-sprint": ("night run", "night runs"), "night-marathon": ("night run", "night runs"),
                   "pr": ("PR", "PRs"), "worktree": ("worktree", "worktrees"), "artifact": ("artifact", "artifacts")}


def _dismissed_when(stamp, now):
    """'dismissed just now', 'dismissed 2 h ago', or 'dismissed' when the stamp is unknown."""
    when = span(stamp, now)
    return "dismissed" if not when else "dismissed just now" if when == "just now" else "dismissed %s ago" % when


def dismissed_fold(found, now):
    """The "Dismissed" fold: "Dismissed 3 - 1 night run, 2 sessions", a Restore per row; None when empty."""
    if not found:
        return None
    words = [DISMISSED_WORDS.get(i.kind, (i.kind, i.kind))[0] for i in found]
    order = []
    for w in words:
        if w not in order:
            order.append(w)
    plural = {one: many for one, many in DISMISSED_WORDS.values()}
    summary = ", ".join("%d %s" % (words.count(w), w if words.count(w) == 1 else plural.get(w, w)) for w in order)
    rows = [ViewRow(item_id=i.id, title=i.title, text=_join(words[n], _dismissed_when(i.dismissed_at, now)),
                    action="Restore") for n, i in enumerate(found)]
    return ViewFold(kind="dismissed", label="Dismissed", count=len(found), summary=summary, rows=rows)


# ---------------------------------------------------------------- the page

def _header(conn, tree, project):
    crumbs = [{"id": pid, "name": tree.rows[pid]["name"]} for pid in reversed(tree.ancestors(project.id))]
    links = sorted(({"id": pid, "name": tree.rows[pid]["name"]} for pid in project.linked_ids if not tree.hidden(pid)),
                   key=lambda link: (link["name"].lower(), link["id"]))
    taken = set(project.linked_ids) | {project.id, store.INBOX_ID}
    choices = [{"id": p.id, "name": " / ".join(p.path)} for p in model.list_projects(conn, None, False, False)
               if p.id not in taken]
    linked = "Linked: %s" % ", ".join(link["name"] for link in links) if links else ""
    return crumbs, linked, choices, links


def state(conn, project_id, now=None):
    """The whole project view as one ProjectView (what `GET /project?id=` carries)."""
    now = time.time() if now is None else now
    project, runs, sessions, prs, trees, arts, subs, _ = items.status(conn, project_id)
    tree = model.Tree(conn)
    crumbs, linked, choices, links = _header(conn, tree, project)
    rows = [view_session(s, now) for s in sessions]
    folded = not any(r.status == "running" for r in rows)
    live_cwds = [s.data.get("cwd") or "" for s, r in zip(sessions, rows) if r.status == "running"]
    live_cwds = [c for c in live_cwds if os.path.isabs(c)]
    plans = arts
    prs, trees, arts = ([i for i in found if not i.gone] for found in (prs, trees, arts))
    own = [view_run(conn, r, plans) for r in runs if r.project_id == project.id]
    groups = run_groups(tree, project.id, runs, lambda r: view_run(conn, r, plans))
    return ProjectView(project=project, crumbs=crumbs, linked=linked, link_choices=choices,
                       inside=[view_tile(s) for s in subs], runs=own, sub_runs=groups,
                       sessions=rows, sessions_folded=folded, folds=folds(rows, folded, prs, trees, arts, live_cwds),
                       generated_at=store.now_iso(), rules=items.list_rules(conn, project.id),
                       dismissed=dismissed_fold(items.dismissed(conn, project.id), now), links=links)
