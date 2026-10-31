#!/usr/bin/env bash
# night-sprint workspace bootstrap - build a workspace that cannot be half-assembled.
#
#   bootstrap.sh <WORKSPACE> <SKILL_REFERENCES_DIR>
#
# Run once at kickoff, AFTER writing <WORKSPACE>/facts.env. It:
#   1. copies every script and template into the workspace and makes the scripts executable;
#   2. derives the one-value files the scripts read from facts.env, so the two can never drift;
#   3. verifies every script the sprint depends on is present and every required fact is set,
#      and fails loudly if not.
# In a multi-repo sprint (MULTI_REPO=1) step 2 also reads <WORKSPACE>/repos/<key>.env for every
# key in REPOS and derives <WORKSPACE>/repos/<key>/ plus <WORKSPACE>/REPOS.md. See multi-repo.md.
#
# WHY IT IS A SCRIPT. The workspace copies exist so that editing the skill cannot change a
# sprint already running, which is right - and it means kickoff has to copy the correct set.
# Four scripts now `source "$WS/agents.sh"`, so a workspace missing that one file has a
# launcher, a reviver, a runner and a closer that all fail on their first line, at 3am, with
# nobody awake. The same applies to `classify-error.sh`: miss it and the sprint silently loses
# its ability to tell a spending cap from a dropped socket, which is the single most expensive
# misclassification it can make. Neither is something to leave to a checklist.

set -uo pipefail

WS="${1:?usage: bootstrap.sh <WORKSPACE> <SKILL_REFERENCES_DIR>}"
REF="${2:?usage: bootstrap.sh <WORKSPACE> <SKILL_REFERENCES_DIR>}"

[ -d "$REF" ] || { echo "bootstrap: no references dir at $REF" >&2; exit 1; }

mkdir -p "$WS/state" "$WS/tickets"

# --- the scripts the sprint runs. agents.sh is sourced by five of them; classify-error.sh is
#     what makes recovery correct rather than merely persistent.
SCRIPTS="agents.sh repos.sh launch.sh advance.sh watch.sh runner.sh revive.sh close.sh classify-error.sh context-used.sh schedule.sh land.sh accept.sh render.sh research-check.sh trust.sh"
# --- the templates. continuation-prompt.md stays a template on purpose: each session that
#     hands off fills its own copy for its successor.
TEMPLATES="continuation-prompt.md implementer-prompt.md review-find-prompt.md review-fix-prompt.md test-prompt.md plan-template.md ci-prompt.md"
# --- research mode (MODE=research in facts.env): the same runner, research templates. Copied in
#     every mode so one list stays the truth; a code sprint simply never renders them.
TEMPLATES="$TEMPLATES research-ticket-prompt.md research-continuation-prompt.md research-review-find-prompt.md research-review-fix-prompt.md research-synth-prompt.md research-plan-template.md"

missing=""
for f in $SCRIPTS $TEMPLATES; do
  if [ -f "$REF/$f" ]; then
    cp "$REF/$f" "$WS/$f"
  else
    missing="$missing $f"
  fi
done
if [ -n "$missing" ]; then
  echo "bootstrap: FAILED - missing from $REF:$missing" >&2
  exit 1
fi
chmod +x "$WS"/*.sh

# --- derive the one-value files. The scripts read these rather than parsing facts.env, so
#     deriving them here is what keeps one source of truth. PERMISSION_MODE defaults to `auto`:
#     the only mode that neither stalls on a shell prompt nor needs a disclaimer nobody can
#     accept on the user's behalf.
[ -f "$WS/facts.env" ] || { echo "bootstrap: no $WS/facts.env - write it before bootstrapping" >&2; exit 1; }

python3 - "$WS" <<'PY'
import os, re, sys

ws = sys.argv[1]
# Read by the scripts as bare one-value files.
derive = ["WORKTREE", "SLUG", "BRANCH", "VERIFY", "FORMAT_CHECK", "PERMISSION_MODE", "MODE",
          "CONTEXT_WINDOW", "WARN_AT_USED", "RELAY_AT_USED", "CEILING_USED", "BLITZ", "MAX_PARALLEL"]
# Needed by the prompt templates; an unset one is a session that cannot do its job.
required = ["REPO", "REPO_PATH", "REPO_SLUG", "SLUG", "USER", "WS", "WORKTREE", "BRANCH",
            "BASE", "TOOLCHAIN", "VERIFY", "FORMAT_CHECK", "CONTEXT_WINDOW",
            "WARN_AT_USED", "RELAY_AT_USED", "CEILING_USED"]
# Research mode has no repo, no toolchain and no CI, so it needs a different set: the question
# and the sources in place of the repo facts. See research-mode.md.
required_research = ["SLUG", "USER", "WS", "WORKTREE", "BRANCH", "VERIFY", "RESEARCH_TITLE",
                     "QUESTION", "DECISION", "AUDIENCE", "SOURCES", "CONTEXT_WINDOW",
                     "WARN_AT_USED", "RELAY_AT_USED", "CEILING_USED"]
# BLITZ=1 runs tickets side by side on a dependency graph (schedule.sh, land.sh); MAX_PARALLEL
# caps how many write at once. Off unless the invocation says `speed: blitz`.
# A multi-repo sprint (MULTI_REPO=1) keeps every per-repo fact in <WS>/repos/<key>.env, one file
# per key in REPOS, and nothing per-repo in facts.env, so there is one place each fact lives.
# See multi-repo.md.
required_multi = ["SLUG", "USER", "WS", "REPOS", "CONTEXT_WINDOW",
                  "WARN_AT_USED", "RELAY_AT_USED", "CEILING_USED"]
per_repo = ["REPO", "REPO_PATH", "REPO_SLUG", "WORKTREE", "BRANCH", "BASE", "TOOLCHAIN",
            "VERIFY", "FORMAT_CHECK"]
# Read by the scripts as bare one-value files under <WS>/repos/<key>/.
derive_repo = ["WORKTREE", "BRANCH", "BASE", "REPO_SLUG", "VERIFY", "FORMAT_CHECK"]
defaults = {"PERMISSION_MODE": "auto", "MODE": "code", "CONTEXT_WINDOW": "200000",
            "BLITZ": "0", "MAX_PARALLEL": "3",
            "WARN_AT_USED": "20", "RELAY_AT_USED": "30", "CEILING_USED": "60"}

def read_env(path):
    out = {}
    for raw in open(path):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", k):
            out[k] = v.strip()
    return out

def fail(msg):
    sys.stderr.write("bootstrap: FAILED - %s\n" % msg)
    raise SystemExit(1)

vals = read_env(os.path.join(ws, "facts.env"))

for k, v in defaults.items():
    vals.setdefault(k, v)

if vals["MODE"] not in ("code", "research"):
    sys.stderr.write("bootstrap: FAILED - MODE must be code or research, got %r\n" % vals["MODE"])
    raise SystemExit(1)
multi = vals.get("MULTI_REPO", "").lower() in ("1", "yes", "true", "on")
keys = vals.get("REPOS", "").split()
if multi and vals["MODE"] == "research":
    fail("MULTI_REPO is for code sprints; research mode has no repo")
if len(keys) > 1 and not multi:
    fail("REPOS names %d repos but MULTI_REPO is not set - set MULTI_REPO=1" % len(keys))
if vals["MODE"] == "research":
    required = required_research
elif multi:
    required = required_multi
absent = [k for k in required if not vals.get(k)]
if absent:
    sys.stderr.write("bootstrap: FAILED - facts.env is missing or empty for: %s\n"
                     % " ".join(absent))
    raise SystemExit(1)

repos = {}
if multi:
    if len(keys) < 2:
        fail("MULTI_REPO=1 needs at least two keys in REPOS, got %r" % vals.get("REPOS", ""))
    if len(set(keys)) != len(keys):
        fail("REPOS names a key twice: %s" % " ".join(keys))
    stray = [k for k in per_repo if k in vals]
    if stray:
        fail("per-repo facts belong in repos/<key>.env, not facts.env: %s" % " ".join(stray))
    for key in keys:
        # No hyphen: the runner matches a tag's sessions by name prefix plus "-", so a key
        # `shapes` would make CI-shapes claim the sessions of CI-shapes-internal.
        if not re.fullmatch(r"[a-z][a-z0-9]*", key):
            fail("repo key %r must be lower case letters and digits, starting with a letter" % key)
        path = os.path.join(ws, "repos", key + ".env")
        if not os.path.isfile(path):
            fail("no %s for repo key %s" % (path, key))
        rv = read_env(path)
        absent = [k for k in per_repo if not rv.get(k)]
        if absent:
            fail("%s is missing or empty for: %s" % (path, " ".join(absent)))
        if rv.get("REPO_KEY", key) != key:
            fail("%s says REPO_KEY=%s" % (path, rv["REPO_KEY"]))
        if "REPO_KEY" not in rv:
            # The templates' multi-repo blocks name the key as <REPO_KEY>.
            with open(path, "a") as fh:
                fh.write("REPO_KEY=%s\n" % key)
        repos[key] = rv
    worktrees = [repos[k]["WORKTREE"] for k in keys]
    if len(set(worktrees)) != len(worktrees):
        fail("two repos share a worktree: %s" % " ".join(worktrees))
    for key in keys:
        d = os.path.join(ws, "repos", key)
        os.makedirs(d, exist_ok=True)
        for k in derive_repo:
            with open(os.path.join(d, k), "w") as fh:
                fh.write(repos[key][k] + "\n")
    # A tag with no state/<TAG>.repo (TEST, FIX-TEST) runs in the first repo's worktree.
    for k in ("WORKTREE", "BRANCH", "VERIFY", "FORMAT_CHECK"):
        vals[k] = repos[keys[0]][k]
    # Not "REPOS": on a case-insensitive disk (macOS) that IS the repos/ directory.
    with open(os.path.join(ws, "REPO_KEYS"), "w") as fh:
        fh.write(" ".join(keys) + "\n")
    # One table every session can read to find a sibling repo's tree.
    with open(os.path.join(ws, "REPOS.md"), "w") as fh:
        fh.write("| Key | Repo | Worktree | Branch | Base |\n|---|---|---|---|---|\n")
        for key in keys:
            r = repos[key]
            fh.write("| %s | %s | %s | %s | %s |\n"
                     % (key, r["REPO_SLUG"], r["WORKTREE"], r["BRANCH"], r["BASE"]))

for k in derive:
    if k not in vals:  # FORMAT_CHECK in research mode: there is no repo CI to match
        continue
    with open(os.path.join(ws, k), "w") as fh:
        fh.write(vals[k] + "\n")

print("bootstrap: %d facts, %d one-value files derived%s"
      % (len(vals), len(derive), (", %d repos" % len(repos)) if repos else ""))
PY
rc=$?
[ $rc -eq 0 ] || exit $rc

# Resolve the {{#BLITZ}} / {{^BLITZ}} blocks in every copied template once, now that facts.env
# says which mode this is. A session that fills a template by hand (a continuation) then never
# sees a marker, and render.sh finds nothing left to decide.
for f in $TEMPLATES; do
  bash "$WS/render.sh" "$WS" --blocks "$WS/$f" || { echo "bootstrap: FAILED - $f has a broken {{block}}" >&2; exit 1; }
done

# --- research mode: the worktree is a local git repo with no remote. Sessions commit their
#     findings there, which is what gives the runner a HEAD to diff and the reviver a log to
#     read. There is no PR to open, so the runner's one-time NEEDS-PR ask is pre-answered.
if [ "$(tr -d '[:space:]' < "$WS/MODE")" = "research" ]; then
  WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"
  BR="$(tr -d '[:space:]' < "$WS/BRANCH")"
  if ! git -C "$WT" rev-parse --git-dir >/dev/null 2>&1; then
    mkdir -p "$WT/findings" \
      && git -C "$WT" init -q -b "$BR" \
      && git -C "$WT" config user.name "night-sprint" \
      && git -C "$WT" config user.email "night-sprint@localhost" \
      && git -C "$WT" commit -q --allow-empty -m "research workspace" \
      || { echo "bootstrap: FAILED - could not create the research repo at $WT" >&2; exit 1; }
  fi
  # `claude --bg` refuses an untrusted folder, and <WS>/work is a new git root on every run, so no
  # parent folder's trust covers it. Without this T01 never starts. launch.sh checks again before
  # every launch. A failure is a loud warning, not a stop: the launch then fails or succeeds
  # exactly as it did before this step existed, and launch.sh tries once more.
  bash "$WS/trust.sh" "$WT" || echo "bootstrap: WARNING - could not mark $WT trusted; T01 may fail with 'Workspace not trusted'" >&2
  : > "$WS/state/.pr-asked"
fi

: > "$WS/state/EVENTS.log"
printf '%s bootstrap workspace ready\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$WS/state/EVENTS.log"
echo "bootstrap: $WS ready - $(printf '%s\n' $SCRIPTS | wc -l | tr -d ' ') scripts, $(printf '%s\n' $TEMPLATES | wc -l | tr -d ' ') templates"
