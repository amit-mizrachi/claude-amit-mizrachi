#!/usr/bin/env bash
# Static check of the improve-benny corpus: layout, rubric format, verdict history, no emails.
# Format spec: references/corpus-format.md. Usage: bash tests/check.sh [corpus dir]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 - "${1:-$here/corpus}" <<'PY'
import json, os, re, sys

corpus = sys.argv[1]
fails = []
ITEM = re.compile(r"^([a-z0-9][a-z0-9-]*) \| (required|forbidden) \| (all|pre-sql|full) \| (\S.*)$")
CASE_ID = re.compile(r"^(acct-[0-9]+|synth)-[a-z0-9][a-z0-9-]*$")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
FILES = ("case.md", "gold-answer.md", "rubric.txt", "verdicts.jsonl")

def frontmatter(path):
    txt = open(path, encoding="utf-8").read()
    if not txt.startswith("---\n"):
        return None
    head = txt[4:].split("\n---", 1)[0]
    return dict(l.split(":", 1) for l in head.splitlines() if ":" in l)

cases = sorted(d for d in os.listdir(corpus)
               if os.path.isdir(os.path.join(corpus, d)) and not d.startswith("_"))
for case in cases:
    d = os.path.join(corpus, case)
    if not CASE_ID.match(case):
        fails.append("%s: case id must be acct-<id>-<slug> or synth-<slug>" % case)
    have = sorted(f for f in os.listdir(d) if not f.startswith("."))
    if have != sorted(FILES):
        fails.append("%s: files must be exactly %s, found %s" % (case, ", ".join(FILES), ", ".join(have)))
        continue
    fm = frontmatter(os.path.join(d, "case.md"))
    if fm is None:
        fails.append("%s/case.md: no frontmatter" % case)
    else:
        if fm.get("id", "").strip() != case:
            fails.append("%s/case.md: id must equal the folder name" % case)
        if fm.get("bar", "").strip() not in ("pre-sql", "full"):
            fails.append("%s/case.md: bar must be pre-sql or full" % case)
        if case.startswith("acct-") and fm.get("account", "").strip() != case.split("-")[1]:
            fails.append("%s/case.md: account must match the case id" % case)
    if "## Replay message" not in open(os.path.join(d, "case.md"), encoding="utf-8").read():
        fails.append("%s/case.md: needs a '## Replay message' section" % case)
    if frontmatter(os.path.join(d, "gold-answer.md")) is None:
        fails.append("%s/gold-answer.md: no frontmatter" % case)
    ids, kinds = set(), set()
    for n, line in enumerate(open(os.path.join(d, "rubric.txt"), encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        m = ITEM.match(line)
        if not m:
            fails.append("%s/rubric.txt:%d: want 'id | required|forbidden | all|pre-sql|full | text'" % (case, n))
            continue
        if m.group(1) in ids:
            fails.append("%s/rubric.txt:%d: duplicate id %s" % (case, n, m.group(1)))
        ids.add(m.group(1))
        kinds.add(m.group(2))
    if kinds != {"required", "forbidden"}:
        fails.append("%s/rubric.txt: needs at least one required and one forbidden item" % case)
    for n, line in enumerate(open(os.path.join(d, "verdicts.jsonl"), encoding="utf-8"), 1):
        if not line.strip():
            continue
        try:
            v = json.loads(line)
        except ValueError:
            fails.append("%s/verdicts.jsonl:%d: not JSON" % (case, n))
            continue
        for k in ("utc", "run", "bar", "items", "pass"):
            if k not in v:
                fails.append("%s/verdicts.jsonl:%d: missing %s" % (case, n, k))
        if not set(v.get("items", {})) <= ids:
            fails.append("%s/verdicts.jsonl:%d: grades items not in rubric.txt" % (case, n))
    for f in FILES:
        for n, line in enumerate(open(os.path.join(d, f), encoding="utf-8"), 1):
            for e in EMAIL.findall(line):
                fails.append("%s/%s:%d: email address %s" % (case, f, n, e))

if fails:
    print("corpus check: FAIL (%d)" % len(fails))
    print("\n".join(fails))
    sys.exit(1)
print("corpus check: ok (%d cases)" % len(cases))
PY
