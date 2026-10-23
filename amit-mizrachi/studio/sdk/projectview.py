"""The studio's project view (`#/p/<id>`): header, sub-project tiles, run panels, sessions, folds.

Every rule the project view shows lives here, not in the web server or the page script:
- Runs are ranked as on the card (needs-you > blocked > running > paused > latest); a run panel
  offers Open plan (it has a plan page), Open PR (it has a PR) and Open in Terminal (a session of
  it is still listed by `claude agents`).
- A bg session still listed opens ("Open in Terminal"); an interactive or removed one resumes.
- Sessions fold into "Everything else" when none is active; PRs, worktrees and artifacts always do.
- Gone PRs, worktrees and artifacts are left out; gone sessions show greyed, "(removed)".
"""

import os
import time

from . import cache, items, model, store
from .actions import run_session
from .home import GLYPHS, WORDS, _progress_text, _stage_bar, clock, pr_text
from .results import ProjectView, ViewFold, ViewRow, ViewRun, ViewSession, ViewTile

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
    if run.status in ("needs-you", "blocked"):
        return run.reason
    current = (run.progress or {}).get("current") or ""
    stage = run.stage if run.stage and run.stage != current else ""
    return _join(stage, _progress_text(run))


def view_run(conn, run, arts):
    live = run_session(conn, run.item_id) if not run.gone else None
    has_plan = any(a.workspace_item_id == run.item_id for a in arts) or bool(run.artifact_url)
    started = clock(run.started_at) if run.status != "done" else ""
    return ViewRun(item_id=run.item_id, title=run.title, status=run.status, glyph=GLYPHS.get(run.status, "?"),
                   word=WORDS.get(run.status, run.status.title()), detail=_detail(run),
                   bar=_stage_bar(run) if run.status != "needs-you" else [],
                   started="started %s" % started if started else "", pr=pr_text(run.pr),
                   has_plan=has_plan, has_pr=bool(run.pr and run.pr.get("url")),
                   terminal_item_id=live["id"] if live else None, gone=run.gone)


def _runs_text(n):
    return "%d run%s" % (n, "" if n == 1 else "s")


def view_tile(sub):
    if not sub.runs:
        status, text = "pending", "no runs"
    elif sub.runs_active:
        status, text = sub.top_status, "%s, %d active" % (_runs_text(sub.runs), sub.runs_active)
    elif sub.top_status == "done":
        status, text = "done", "%s done" % _runs_text(sub.runs)
    else:
        status, text = sub.top_status or "unknown", _runs_text(sub.runs)
    glyph = "\u00b7" if status == "pending" else GLYPHS.get(status, "?")
    return ViewTile(project_id=sub.project.id, name=sub.project.name, status=status, glyph=glyph, text=text)


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


# ---------------------------------------------------------------- the page

def _header(conn, tree, project):
    crumbs = [{"id": pid, "name": tree.rows[pid]["name"]} for pid in reversed(tree.ancestors(project.id))]
    linked = [tree.rows[pid]["name"] for pid in project.linked_ids if not tree.hidden(pid)]
    taken = set(project.linked_ids) | {project.id, store.INBOX_ID}
    choices = [{"id": p.id, "name": " / ".join(p.path)} for p in model.list_projects(conn, None, False, False)
               if p.id not in taken]
    return crumbs, "Linked: %s" % ", ".join(sorted(linked, key=str.lower)) if linked else "", choices


def state(conn, project_id, now=None):
    """The whole project view as one ProjectView (what `GET /project?id=` carries)."""
    now = time.time() if now is None else now
    project, runs, sessions, prs, trees, arts, subs, _ = items.status(conn, project_id)
    tree = model.Tree(conn)
    crumbs, linked, choices = _header(conn, tree, project)
    rows = [view_session(s, now) for s in sessions]
    folded = not any(r.status == "running" for r in rows)
    live_cwds = [s.data.get("cwd") or "" for s, r in zip(sessions, rows) if r.status == "running"]
    live_cwds = [c for c in live_cwds if os.path.isabs(c)]
    prs, trees, arts = ([i for i in found if not i.gone] for found in (prs, trees, arts))
    return ProjectView(project=project, crumbs=crumbs, linked=linked, link_choices=choices,
                       inside=[view_tile(s) for s in subs], runs=[view_run(conn, r, arts) for r in runs],
                       sessions=rows, sessions_folded=folded, folds=folds(rows, folded, prs, trees, arts, live_cwds),
                       generated_at=store.now_iso())
