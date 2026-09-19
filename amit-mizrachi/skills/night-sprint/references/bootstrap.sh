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
#
# WHY IT IS A SCRIPT. The workspace copies exist so that editing the skill cannot change a
# sprint already running, which is right - and it means kickoff has to copy the correct set.
# Four scripts now `source "$WS/agents.sh"`, so a workspace missing that one file has a
# launcher, a reviver, a runner and a handback that all fail on their first line, at 3am, with
# nobody awake. The same applies to `classify-error.sh`: miss it and the sprint silently loses
# its ability to tell a spending cap from a dropped socket, which is the single most expensive
# misclassification it can make. Neither is something to leave to a checklist.

set -uo pipefail

WS="${1:?usage: bootstrap.sh <WORKSPACE> <SKILL_REFERENCES_DIR>}"
REF="${2:?usage: bootstrap.sh <WORKSPACE> <SKILL_REFERENCES_DIR>}"

[ -d "$REF" ] || { echo "bootstrap: no references dir at $REF" >&2; exit 1; }

mkdir -p "$WS/state" "$WS/tickets"

# --- the scripts the sprint runs. agents.sh is sourced by four of them; classify-error.sh is
#     what makes recovery correct rather than merely persistent.
SCRIPTS="agents.sh launch.sh advance.sh watch.sh revive.sh classify-error.sh context-used.sh handback.sh accept.sh render.sh"
# --- the templates. continuation-prompt.md stays a template on purpose: each session that
#     hands off fills its own copy for its successor.
TEMPLATES="continuation-prompt.md implementer-prompt.md review-find-prompt.md review-fix-prompt.md test-prompt.md wizard-prompt.md plan-template.md"

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
derive = ["WORKTREE", "SLUG", "BRANCH", "VERIFY", "PERMISSION_MODE",
          "CONTEXT_WINDOW", "WARN_AT_USED", "RELAY_AT_USED", "CEILING_USED"]
# Needed by the prompt templates; an unset one is a session that cannot do its job.
required = ["REPO", "REPO_PATH", "REPO_SLUG", "SLUG", "USER", "WS", "WORKTREE", "BRANCH",
            "BASE", "TOOLCHAIN", "VERIFY", "FORMAT_CHECK", "CONTEXT_WINDOW",
            "WARN_AT_USED", "RELAY_AT_USED", "CEILING_USED"]
defaults = {"PERMISSION_MODE": "auto", "CONTEXT_WINDOW": "200000",
            "WARN_AT_USED": "20", "RELAY_AT_USED": "30", "CEILING_USED": "60"}

vals = {}
for raw in open(os.path.join(ws, "facts.env")):
    line = raw.rstrip("\n")
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    k = k.strip()
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", k):
        vals[k] = v.strip()

for k, v in defaults.items():
    vals.setdefault(k, v)

absent = [k for k in required if not vals.get(k)]
if absent:
    sys.stderr.write("bootstrap: FAILED - facts.env is missing or empty for: %s\n"
                     % " ".join(absent))
    raise SystemExit(1)

for k in derive:
    with open(os.path.join(ws, k), "w") as fh:
        fh.write(vals[k] + "\n")

print("bootstrap: %d facts, %d one-value files derived" % (len(vals), len(derive)))
PY
rc=$?
[ $rc -eq 0 ] || exit $rc

: > "$WS/state/EVENTS.log"
printf '%s bootstrap workspace ready\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$WS/state/EVENTS.log"
echo "bootstrap: $WS ready - $(printf '%s\n' $SCRIPTS | wc -l | tr -d ' ') scripts, $(printf '%s\n' $TEMPLATES | wc -l | tr -d ' ') templates"
