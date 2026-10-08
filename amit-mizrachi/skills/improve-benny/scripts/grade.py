#!/usr/bin/env python3
"""Deterministic half of the improve-benny judge step. The judging itself is two Opus subagents.

usage:
  grade.py items  <case dir>                     rubric items in force at the case's bar
  grade.py prompt <case dir> <replay.json>       the filled judge prompt, on stdout
  grade.py record <case dir> <replay.json> <judge-1.json> <judge-2.json> --run <name> [--dry-run]
      merge the two judges (pass only when both pass), print the graded table, and append one
      line to <case dir>/verdicts.jsonl. --dry-run prints the line and appends nothing.

Formats: references/corpus-format.md (rubric, verdicts.jsonl, replay record) and
references/judge-prompt.md (the template and the judge's JSON answer).
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ITEM = re.compile(r"^([a-z0-9][a-z0-9-]*) \| (required|forbidden) \| (all|pre-sql|full) \| (\S.*)$")


def die(msg):
    sys.exit("grade.py: " + msg)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def case_bar(case_dir):
    m = re.search(r"^bar:\s*(\S+)", read(os.path.join(case_dir, "case.md")), re.M)
    if not m:
        die("%s/case.md has no bar" % case_dir)
    return m.group(1)


def items_in_force(case_dir):
    """[(id, kind, text)] for the items graded at the case's bar, in rubric order."""
    bar, out = case_bar(case_dir), []
    for line in read(os.path.join(case_dir, "rubric.txt")).splitlines():
        m = ITEM.match(line)
        if m and m.group(3) in ("all", bar):
            out.append((m.group(1), m.group(2), m.group(4)))
    return out


def section(text, heading, stop):
    m = re.search(r"^%s.*?$(.*?)(?=^%s|\Z)" % (re.escape(heading), re.escape(stop)), text, re.M | re.S)
    return m.group(1).strip() if m else ""


def load_json(path):
    try:
        return json.loads(read(path))
    except ValueError as e:
        die("%s is not JSON: %s" % (path, e))


def tool_lines(replay):
    tools = replay.get("tools") or []
    if not tools:
        return "(no tool calls)"
    lines = ["- %s: %s%s" % (t["name"], t["outcome"], (" - " + t["error"]) if t.get("error") else "")
             for t in tools]
    if replay.get("tools_offered") is not None:
        lines.append("(%s tools were offered in this turn; %s registered tools were dormant)"
                     % (replay["tools_offered"], replay.get("tools_dormant", "?")))
    return "\n".join(lines)


def cmd_prompt(case_dir, replay_path):
    tpl = read(os.path.join(HERE, "..", "references", "judge-prompt.md"))
    m = re.search(r"^<<<PROMPT\n(.*?)^PROMPT>>>", tpl, re.M | re.S)
    if not m:
        die("judge-prompt.md has no <<<PROMPT ... PROMPT>>> block")
    case_md, replay = read(os.path.join(case_dir, "case.md")), load_json(replay_path)
    fill = {
        "CASE_ID": os.path.basename(os.path.normpath(case_dir)),
        "BAR": case_bar(case_dir),
        "MESSAGE": section(case_md, "## Replay message", "## "),
        "REPLY": replay["reply"].strip(),
        "TOOLS": tool_lines(replay),
        "ITEMS": "\n".join("%s | %s | %s" % i for i in items_in_force(case_dir)),
        "GOLD": section(read(os.path.join(case_dir, "gold-answer.md")), "## 2.", "## 3."),
    }
    out = m.group(1)
    for k, v in fill.items():
        out = out.replace("{{%s}}" % k, v)
    sys.stdout.write(out)


def judge_items(path, want):
    j = load_json(path)
    got = {i.get("id"): i for i in j.get("items", [])}
    if set(got) != set(want) or len(got) != len(j.get("items", [])):
        die("%s grades %s, want exactly %s" % (path, sorted(got), sorted(want)))
    for i in got.values():
        if i.get("verdict") not in ("pass", "fail"):
            die("%s: item %s verdict %r is not pass or fail" % (path, i["id"], i.get("verdict")))
    return got


def cmd_record(case_dir, replay_path, j1, j2, run, dry):
    items = items_in_force(case_dir)
    ids = [i[0] for i in items]
    a, b = judge_items(j1, ids), judge_items(j2, ids)
    replay = load_json(replay_path)
    merged, split, fails = {}, [], {}
    for iid, kind, _ in items:
        va, vb = a[iid]["verdict"], b[iid]["verdict"]
        merged[iid] = "pass" if va == vb == "pass" else "fail"
        if va != vb:
            split.append(iid)
        if merged[iid] == "fail":
            fails[iid] = (a[iid] if va == "fail" else b[iid])["reason"]
    passed = all(v == "pass" for v in merged.values())
    line = {
        "utc": replay["utc"],
        "run": run,
        "bar": case_bar(case_dir),
        "benny_session": replay["session"],
        "spec_archive": replay.get("spec_archive"),
        "spec_version": replay.get("spec_version"),
        "tools": ["%s %s" % (t["name"], t["outcome"]) for t in replay.get("tools") or []],
        "items": merged,
        "pass": passed,
        "judges": 2,
        "agreement": "%d/%d" % (len(ids) - len(split), len(ids)),
        "split": split,
        "fails": fails,
        "note": replay.get("note", ""),
    }
    w = max(len(i) for i in ids)
    print("%s - %s (bar %s), judges agree %s" % (
        os.path.basename(os.path.normpath(case_dir)), "PASS" if passed else "FAIL", line["bar"], line["agreement"]))
    for iid, kind, _ in items:
        mark = "split " if iid in split else ""
        print("  %-*s  %-9s %s%s  %s" % (w, iid, kind, mark, merged[iid], fails.get(iid, "")))
    text = json.dumps(line, ensure_ascii=True)
    if dry:
        print(text)
        return
    with open(os.path.join(case_dir, "verdicts.jsonl"), "a", encoding="utf-8") as f:
        f.write(text + "\n")


def main(argv):
    if len(argv) >= 2 and argv[0] == "items":
        for i in items_in_force(argv[1]):
            print("%s | %s | %s" % i)
    elif len(argv) == 3 and argv[0] == "prompt":
        cmd_prompt(argv[1], argv[2])
    elif len(argv) >= 7 and argv[0] == "record" and "--run" in argv:
        run = argv[argv.index("--run") + 1]
        cmd_record(argv[1], argv[2], argv[3], argv[4], run, "--dry-run" in argv)
    else:
        die(__doc__.strip().split("\n\n", 1)[1])


if __name__ == "__main__":
    main(sys.argv[1:])
