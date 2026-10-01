#!/usr/bin/env bash
# night-sprint research verify - the research mode's VERIFY. Is every claim tied to a source?
#
#   research-check.sh <WORKSPACE>            # every findings file in the worktree
#   research-check.sh <WORKSPACE> --final    # also the artifact and its published URL
#
# Exit 0 and a last line of PASS when everything holds; exit 1 and FAIL lines naming the file
# and the rule otherwise.
#
# WHY A SCRIPT. A code sprint has a test suite to stop a session calling broken work done. A
# research session has nothing like it, and the failure it invites is the quiet one: a
# confident paragraph with no source behind it, written at 3am, read in the morning as fact.
# This cannot tell whether a source says what the finding claims - REVIEW-FINAL does that -
# but it can make every claim name its evidence, which is what makes that review possible.
#
# A findings file is <WORKTREE>/findings/<NN>-<slug>.md with these sections, in any order:
#   ## Answer     the direct answer to the ticket's question
#   ## Findings   one bullet per claim; each ends in [S<n>] citations, or [INFERENCE]
#   ## Gaps       what could not be found or reached (may say "None")
#   ## Sources    one bullet per source: - [S<n>] <title> - <https://... | connector:<Name> <ref> | repo:<path>:<line> @<sha>> - accessed <YYYY-MM-DD>

set -uo pipefail

WS="${1:?usage: research-check.sh <WORKSPACE> [--final]}"
FINAL=0
[ "${2:-}" = "--final" ] && FINAL=1

WT="$(tr -d '[:space:]' < "$WS/WORKTREE" 2>/dev/null)"
[ -n "$WT" ] && [ -d "$WT" ] || { echo "FAIL no worktree recorded in $WS/WORKTREE"; exit 1; }

python3 - "$WS" "$WT" "$FINAL" <<'PY'
import glob, os, re, sys

ws, wt, final = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
fails = []

def sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1).strip().lower()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out

files = sorted(glob.glob(os.path.join(wt, "findings", "*.md")))
if not files:
    fails.append("no findings files under %s/findings/" % wt)

for path in files:
    name = os.path.relpath(path, wt)
    sec = sections(open(path, encoding="utf-8").read())
    for need in ("answer", "findings", "gaps", "sources"):
        if need not in sec:
            fails.append("%s: no '## %s' section" % (name, need.capitalize()))
    if "findings" not in sec or "sources" not in sec:
        continue

    defined = {}
    for line in sec["sources"]:
        m = re.match(r"^\s*[-*]\s*\[(S\d+)\]\s*(.*)$", line)
        if m:
            defined[m.group(1)] = m.group(2)
    if not defined:
        fails.append("%s: '## Sources' lists no [S<n>] entries" % name)
    for sid, rest in defined.items():
        if not re.search(r"https?://|connector:|repo:\S", rest):
            fails.append("%s: %s has no locator (an https:// URL, connector:<Name> <ref>, or repo:<path>:<line> @<sha>)" % (name, sid))

    bullets = [l for l in sec["findings"] if re.match(r"^\s*[-*]\s+\S", l)]
    if not bullets:
        fails.append("%s: '## Findings' has no bullets" % name)
    cited = set()
    for b in bullets:
        ids = re.findall(r"\[(S\d+)\]", b)
        if not ids and "[INFERENCE]" not in b:
            fails.append("%s: uncited finding: %s" % (name, b.strip()[:90]))
        cited |= set(ids)
    for line in sec.get("answer", []):
        cited |= set(re.findall(r"\[(S\d+)\]", line))
    for sid in sorted(cited - set(defined)):
        fails.append("%s: cites %s but '## Sources' does not define it" % (name, sid))

if final:
    art = os.path.join(ws, "artifact", "index.html")
    if not os.path.isfile(art) or os.path.getsize(art) == 0:
        fails.append("no artifact at %s" % art)
    elif os.path.getsize(art) > 16 * 1024 * 1024:
        fails.append("artifact is over the 16MB page limit")
    url_file = os.path.join(ws, "state", "ARTIFACT.url")
    url = open(url_file).read().strip() if os.path.isfile(url_file) else ""
    if not url:
        fails.append("no published URL in state/ARTIFACT.url (write LOCAL-ONLY <path> if publishing failed)")

for f in fails:
    print("FAIL " + f)
print("PASS %d findings files" % len(files) if not fails else "FAIL %d problems" % len(fails))
sys.exit(1 if fails else 0)
PY
