#!/usr/bin/env bash
# night-sprint prompt renderer - fill a template mechanically, and refuse a half-filled one.
#
#   render.sh <WORKSPACE> <TEMPLATE> <OUT> [EXTRA_VARS_FILE ...]
#   render.sh <WORKSPACE> --check <FILE>        # just report unfilled slots, fill nothing
#
# Reads KEY=VALUE lines from <WS>/facts.env, then from each EXTRA_VARS_FILE in order (later
# wins), and replaces every `<KEY>` token in the template. Then it looks for any remaining
# `<UPPER_CASE>` token and FAILS if it finds one.
#
# WHY A SCRIPT DOES THIS. Kickoff used to author every prompt by hand, and one night that
# came to 22 prompts and 29,266 words - written by a model, from a 10,000-word skill, mostly
# re-typing the same repo path, toolchain line, verify command, branch and thresholds into
# each one. All of that is substitution, which is the cheapest possible thing to get wrong
# and the cheapest possible thing to automate. An unfilled `<VERIFY>` is a session that wakes
# at 3am not knowing how to check its own work, so the check at the end is the point of this
# script as much as the substitution is.
#
# The model still writes the parts that are actually judgement: the ticket's scope, its
# acceptance criteria, its gotchas, the golden path. Those go in the per-tag vars file.
#
# Only UPPER_CASE tokens are slots. Lower-case angle brackets in the templates are prose
# addressed to the session - `<what is wrong>`, `<owner/repo>` - and are left alone.

set -uo pipefail

WS="${1:?usage: render.sh <WORKSPACE> <TEMPLATE> <OUT> [VARS...] | render.sh <WS> --check <FILE>}"
shift

if [ "${1:-}" = "--check" ]; then
  shift
  FILE="${1:?usage: render.sh <WS> --check <FILE>}"
  python3 - "$FILE" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
left = sorted(set(re.findall(r'<([A-Z][A-Z0-9_]*)>', src)))
if left:
    print("unfilled: " + " ".join("<%s>" % s for s in left))
    raise SystemExit(1)
print("ok - no unfilled slots")
PY
  exit $?
fi

TEMPLATE="${1:?usage: render.sh <WORKSPACE> <TEMPLATE> <OUT> [VARS...]}"
OUT="${2:?usage: render.sh <WORKSPACE> <TEMPLATE> <OUT> [VARS...]}"
shift 2

[ -f "$TEMPLATE" ] || { echo "render: no template at $TEMPLATE" >&2; exit 1; }

VARS=""
[ -f "$WS/facts.env" ] && VARS="$WS/facts.env"
for extra in "$@"; do
  [ -f "$extra" ] || { echo "render: no vars file at $extra" >&2; exit 1; }
  VARS="$VARS $extra"
done

# shellcheck disable=SC2086
python3 - "$TEMPLATE" "$OUT" $VARS <<'PY'
import re, sys

template, out = sys.argv[1], sys.argv[2]
vals = {}
for path in sys.argv[3:]:
    for raw in open(path):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            vals[key] = value.strip()

src = open(template).read()
# Longest key first, so <TAG> never eats the front of <TAG_TITLE>.
for key in sorted(vals, key=len, reverse=True):
    src = src.replace("<%s>" % key, vals[key])

open(out, "w").write(src)

left = sorted(set(re.findall(r'<([A-Z][A-Z0-9_]*)>', src)))
if left:
    sys.stderr.write(
        "render: WROTE %s but it still has unfilled slots: %s\n"
        "        A session that starts with one of these does not know how to do its job.\n"
        % (out, " ".join("<%s>" % s for s in left)))
    raise SystemExit(2)
print("render: %s -> %s (%d slots filled)" % (template.split("/")[-1], out, len(vals)))
PY
