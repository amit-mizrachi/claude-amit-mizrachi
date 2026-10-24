"""Run readers: every night-sprint and night-marathon workspace, summarised as one record.

A record says what the run is (`kind`, `slug`, repo, branch, worktree), where it stands
(`status`, `reason`, `progress` "T03 of 5", `stage`, `stages`), and what belongs to it, so the
reconcile can attach children: its session ids, its slugs (session titles `ns-<slug>-<TAG>`),
its branches (`<BRANCH>` and per-ticket `<BRANCH>--<TAG>`), its worktrees (`<WORKTREE>`,
per-ticket `<WORKTREE>-<TAG>`, `state/<TAG>.cwd`) and its artifacts (`state/ARTIFACT.url`).

Status words: needs-you, blocked, running, paused, pending, done, unknown. An old-format
workspace (no `.next` files) and one that fails to read are `unknown`, never dropped.
`changed_at` is the newest change to the run's state files (an EVENTS.log line, a `.status` file
rewritten): a mark-done made before it is out of date (`items.marked_done`).

Built on `readers.workspace` (night-watch's readers). Only READS files.
"""

import glob
import os
import re

from . import commands
from .git import Read
from .sessions import iso
from .workspace import Sprint, World, facts, mtime, read1, tag_state, walk_chain

TICKET = re.compile(r"^T\d+$")
CI_PASS = re.compile(r"^PASS at ([0-9a-f]{7,40})\b")
NO_CI = re.compile(r"\bno CI\b|\b0 checks\b|\bno checks\b", re.I)


def _one_line(ws, name, fallback=""):
    return read1(os.path.join(ws, name)) or fallback


def _ci_red(sp):
    """True for a FAIL acceptance verdict that the CI ticket did not overrule. accept.sh writes FAIL
    whenever `gh pr checks` exits 1, which it also does on a PR with no checks at all; the CI ticket
    runs later and writes "PASS at <sha>" to state/CI.summary when nothing at that head is red."""
    if sp.acceptance != "FAIL":
        return False
    words = sp.acceptance_line.split(" ")
    sha, passed = words[1] if len(words) > 1 else "", CI_PASS.match(sp.ci_summary)
    return not (sha and passed and (sha.startswith(passed.group(1)) or passed.group(1).startswith(sha)))


def _sprint_status(sp):
    """(status, reason) for one sprint workspace."""
    if not sp.stages:
        return "unknown", "old format: no .next files"
    if glob.glob(os.path.join(sp.state, "*.waiting-on-user")):
        return "needs-you", "waiting on you"
    if sp.paused and sp.paused.split(" ")[0].lower().startswith("auth"):
        return "needs-you", "login needed"
    for stage in sp.stages:
        if stage.status == "blocked":
            return "blocked", re.sub(r"^BLOCKED:?\s*", "", stage.detail, flags=re.I) or "blocked"
    if _ci_red(sp):                                # night-watch's two other "needs you" alerts
        return "needs-you", "CI red"
    if sp.finished:
        return "done", "no CI" if NO_CI.search(sp.ci_summary) else ""
    if sp.started and not sp.runner:               # nothing advances, revives or resumes a pause
        return "needs-you", "runner stopped"
    if sp.paused:
        return "paused", "waiting for capacity"
    return ("running", "") if sp.started else ("pending", "")


def _progress(sp, facts_env):
    """{"current", "index", "total", "text"} over the ticket stages (T01..Tnn), or None."""
    tickets = [s for s in sp.stages if TICKET.match(s.name)]
    if not tickets:
        return None
    try:
        total = max(len(tickets), int(facts_env.get("TOTAL") or 0))
    except ValueError:
        total = len(tickets)
    current = next((s for s in tickets if s.status == "running"), None) \
        or next((s for s in tickets if s.status not in ("done", "skipped")), None) or tickets[-1]
    index = tickets.index(current) + 1
    return {"current": current.name, "index": index, "total": total, "text": "%s of %d" % (current.name, total)}


def _current_stage(sp):
    cur = sp.current() or next((s for s in sp.stages if s.status not in ("done", "skipped")), None)
    return cur.name if cur else (sp.stages[-1].name if sp.stages else "")


def _stages(sp):
    return [{"name": s.name, "status": s.status} for s in sp.stages]


def _changed_at(state_dirs):
    """The newest mtime of any EVENTS.log or `<TAG>.status` file in `state_dirs`, as ISO, or ""."""
    stamps = [mtime(os.path.join(d, "EVENTS.log")) for d in state_dirs]
    stamps += [mtime(f) for d in state_dirs for f in glob.glob(os.path.join(d, "*.status"))]
    return iso(max(stamps or [0]))


def _sessions(state_dir):
    out = []
    for path in sorted(glob.glob(os.path.join(state_dir, "*.session"))):
        sid = read1(path).split(" ")[0]
        if sid and sid not in out:
            out.append(sid)
    return out


def _joins(ws, sp_dirs):
    """What belongs to the run: sessions, branches, worktrees, from every sprint dir it holds."""
    out = {"sessions": [], "branches": [], "worktrees": [], "repo_slugs": []}

    def add(key, value):
        if value and value not in out[key]:
            out[key].append(value)

    for sd in sp_dirs:
        env = facts(sd)
        branch = _one_line(sd, "BRANCH", env.get("BRANCH", ""))
        tree = _one_line(sd, "WORKTREE", env.get("WORKTREE", ""))
        add("repo_slugs", env.get("REPO_SLUG", ""))
        add("branches", branch)
        add("worktrees", tree)
        state = os.path.join(sd, "state")
        for sid in _sessions(state):
            add("sessions", sid)
        tags = set(walk_chain(state))
        tags |= {os.path.basename(p).rsplit(".", 1)[0] for p in glob.glob(os.path.join(state, "*.cwd"))}
        for tag in sorted(tags):
            if branch:
                add("branches", "%s--%s" % (branch, tag))
            if tree:
                add("worktrees", "%s-%s" % (tree, tag))
            add("worktrees", read1(os.path.join(state, tag + ".cwd")))
    for sid in _sessions(os.path.join(ws, "phases", "state")):
        add("sessions", sid)
    return out


def _artifacts(ws, sp_dirs, marathon):
    out = []
    for sd in sp_dirs:
        path = os.path.join(sd, "state", "ARTIFACT.url")
        text = read1(path)
        if not text:
            continue
        local = text.startswith("LOCAL-ONLY ")
        out.append({"key": text[len("LOCAL-ONLY "):].strip() if local else text,
                    "url": "" if local else text, "file": text[len("LOCAL-ONLY "):].strip() if local else "",
                    "updated_at": iso(mtime(path)), "plan": bool(marathon and sd == ws),
                    "workspace": ws})
    return out


def _base(ws, kind, env):
    repo_path = env.get("REPO_PATH", "")
    return {
        "path": ws, "slug": os.path.basename(ws), "kind": kind,
        "mode": _one_line(ws, "MODE", env.get("MODE", "code")),
        "repo": env.get("REPO", "") or (os.path.basename(repo_path) if repo_path else ""),
        "repo_slug": env.get("REPO_SLUG", ""), "repo_path": repo_path,
        "branch": _one_line(ws, "BRANCH", env.get("BRANCH", "")),
        "worktree": _one_line(ws, "WORKTREE", env.get("WORKTREE", "")),
        "slugs": [s for s in {os.path.basename(ws), env.get("SLUG", "")} if s],
        "error": "",
    }


def read_sprint(ws, world):
    """One night-sprint workspace as a record."""
    env = facts(ws)
    rec = _base(ws, "night-sprint", env)
    sp = Sprint(ws, world)
    rec["status"], rec["reason"] = _sprint_status(sp)
    rec.update(progress=_progress(sp, env), stage=_current_stage(sp), stages=_stages(sp),
               pr_url=sp.pr, acceptance=sp.acceptance,
               started_at=iso(sp.started_at()), updated_at=iso(sp.last_event or mtime(sp.state)),
               changed_at=_changed_at([sp.state]))
    rec.update(_joins(ws, [ws]))
    rec["artifacts"] = _artifacts(ws, [ws], False)
    return rec


def read_marathon(ws, world):
    """One night-marathon workspace (research, plan, your picks, build) as a record."""
    env = facts(ws)
    rec = _base(ws, "night-marathon", env)
    pstate = os.path.join(ws, "phases", "state")
    builds = [d for d in sorted(glob.glob(os.path.join(ws, "build*"))) if os.path.isdir(os.path.join(d, "state"))]
    research = Sprint(ws, world)
    synth = [s for s in research.stages if s.name == "SYNTH"]
    research_done = all(s.status in ("done", "skipped") for s in research.stages if s.name != "SYNTH")
    plan_done = bool(synth) and synth[0].status == "done"
    picks_waiting = (env.get("MARATHON_MODE") == "review" and
                     (bool(glob.glob(os.path.join(pstate, "*.waiting-on-user"))) or
                      (plan_done and not builds and tag_state(pstate, "CONDUCTOR")[0] != "done")))
    stages = [{"name": "Research", "status": "done" if research.stages and research_done else
               ("running" if research.started else "pending")},
              {"name": "Plan", "status": synth[0].status if synth else "pending"}]
    if env.get("MARATHON_MODE") == "review":
        stages.append({"name": "Your picks", "status": "waiting" if picks_waiting else ("done" if builds else "pending")})
    build_sprints = [Sprint(b, world) for b in builds if walk_chain(os.path.join(b, "state"))]
    for b in build_sprints:
        stages.append({"name": "Build" if os.path.basename(b.ws) == "build" else "Build " + os.path.basename(b.ws)[6:],
                       "status": "done" if b.finished else ("running" if b.started else "pending")})
    if not build_sprints:
        stages.append({"name": "Build", "status": "pending"})
    every = [research] + build_sprints
    blocked = [(s, sp) for sp in every for s in sp.stages if s.status == "blocked"]
    if picks_waiting:
        status, reason = "needs-you", "plan gate"
    elif blocked:
        status, reason = "blocked", re.sub(r"^BLOCKED:?\s*", "", blocked[0][0].detail, flags=re.I) or "blocked"
    elif all(st["status"] in ("done", "skipped") for st in stages):
        status, reason = "done", ""
    elif any(st["status"] != "pending" for st in stages):
        status, reason = "running", ""
    else:
        status, reason = "pending", ""
    build = build_sprints[-1] if build_sprints else None
    current = next((st["name"] for st in stages if st["status"] not in ("done", "skipped")), stages[-1]["name"])
    starts = [sp.started_at() for sp in every if sp.started_at()]
    acts = [mtime(os.path.join(pstate, "EVENTS.log"))] + [sp.last_event for sp in every]
    rec.update(status=status, reason=reason, stages=stages, stage=current,
               progress=_progress(build, facts(build.ws)) if build else None,
               pr_url=build.pr if build else "", acceptance=build.acceptance if build else "",
               started_at=iso(min(starts) if starts else 0), updated_at=iso(max(acts)),
               changed_at=_changed_at([pstate] + [sp.state for sp in every]))
    for b in builds:                     # the build sprint names the repo, branch and worktree
        build_rec = _base(b, "night-sprint", facts(b))
        for key in ("repo", "repo_slug", "repo_path", "branch", "worktree"):
            rec[key] = build_rec[key] or rec[key]
        rec["slugs"] = sorted(set(rec["slugs"]) | set(build_rec["slugs"]) - {os.path.basename(b)})
    rec.update(_joins(ws, [ws] + builds))
    rec["artifacts"] = _artifacts(ws, [ws] + builds, True)
    return rec


def read_workspace(ws, world):
    """One workspace as a record, or None when the folder is no workspace. A read that raises
    is a record with status `unknown` and the error, so one odd folder never hides the rest."""
    try:
        if os.path.exists(os.path.join(ws, "phases", "PHASE_CHAIN")):
            return read_marathon(ws, world)
        if os.path.isdir(os.path.join(ws, "state")):
            return read_sprint(ws, world)
        return None
    except Exception as exc:  # noqa: BLE001 - one bad workspace must not take the scan down
        return unknown_workspace(ws, "could not read: %s" % type(exc).__name__, str(exc)[:300])


def unknown_workspace(ws, reason, error=""):
    """A record for a folder whose status can't be read: kept, listed, status `unknown`."""
    rec = _base(ws, "night-sprint", facts(ws))
    rec.update(status="unknown", reason=reason, error=error, progress=None, stage="", stages=[], pr_url="",
               acceptance="", started_at="", updated_at=iso(mtime(ws)), sessions=[], branches=[],
               worktrees=[], repo_slugs=[], artifacts=[])
    return rec


def discover(extra=()):
    """Every workspace under the roots, plus `extra` folders added by hand (status `unknown`
    when they hold no workspace). ok is False only when a root exists and can't be listed."""
    world, records, errors, seen = World(), [], [], set()
    for root in commands.roots():
        if not os.path.isdir(root):
            continue
        try:
            names = sorted(os.listdir(root))
        except OSError as exc:
            errors.append("could not list %s: %s" % (root, exc))
            continue
        for name in names:
            ws = os.path.join(root, name)
            if os.path.isdir(ws):
                rec = read_workspace(ws, world)
                if rec is not None:
                    records.append(rec)
                    seen.add(ws)
    for ws in extra:
        if ws in seen or not os.path.isdir(ws):
            continue
        records.append(read_workspace(ws, world) or unknown_workspace(ws, "no state folder"))
    return Read(not errors, records, "; ".join(errors))
