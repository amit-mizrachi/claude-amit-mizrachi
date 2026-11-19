#!/usr/bin/env bash
# night-sprint retro digest - one cheap page per session of the night, for the RETRO ticket.
#
#   retro-digest.sh <WORKSPACE> [OUT]
#
# The retro's primary sources are the night's transcripts, and they are far too big to read: a
# single implementer's can pass 10 MB. Read whole, three of them fill the retro's window before
# it has found anything. This script reads every one for it and keeps only what a retrospective
# acts on:
#   - tool calls by name            -> tool economy
#   - the largest tool results      -> expensive calls worth streamlining
#   - files read three times or more -> a navigation pointer was missing
#   - failed tool calls, with text  -> mistakes an automated check could have caught
# It finds each session from state/<TAG>.session (full or short id) under the Claude projects
# folder, `$CLAUDE_CONFIG_DIR/projects` (default `~/.claude/projects`). A tag whose transcript
# is gone gets one line saying so. Writes OUT (default <WS>/state/RETRO.digest.md), prints its path.

set -uo pipefail

WS="${1:?usage: retro-digest.sh <WORKSPACE> [OUT]}"
OUT="${2:-$WS/state/RETRO.digest.md}"
PROJECTS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"

python3 - "$WS/state" "$PROJECTS" "$OUT" <<'PY'
import collections, glob, json, os, re, sys

state, projects, out = sys.argv[1:4]

def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""

def brief(name, inp):
    if not isinstance(inp, dict):
        return name
    for key in ("file_path", "command", "pattern", "query", "url", "skill", "prompt"):
        if inp.get(key):
            return "%s %s" % (name, re.sub(r"\s+", " ", str(inp[key]))[:90])
    return name

def natural(tag):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", tag)]

lines = ["# Night sprint transcript digest", "",
         "One block per session. Read a transcript itself only for an incident named here or in EVENTS.log.", ""]
for sf in sorted(glob.glob(os.path.join(state, "*.session")),
                 key=lambda p: natural(os.path.basename(p))):
    tag = os.path.basename(sf)[:-len(".session")]
    sid = open(sf).read().strip()
    hits = [] if not sid or sid == "unresolved" else glob.glob(os.path.join(projects, "*", sid + "*.jsonl"))
    if not hits:
        lines += ["## %s" % tag, "no transcript found for session `%s`" % (sid or "-"), ""]
        continue
    path = max(hits, key=os.path.getmtime)
    calls, names, sizes, reads, errors, turns = {}, collections.Counter(), [], collections.Counter(), [], 0
    for raw in open(path, errors="replace"):
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        if rec.get("type") == "assistant":
            turns += 1
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                name, inp = b.get("name", "?"), b.get("input") or {}
                calls[b.get("id")] = brief(name, inp)
                names[name] += 1
                if name == "Read" and isinstance(inp, dict) and inp.get("file_path"):
                    reads[inp["file_path"]] += 1
            elif b.get("type") == "tool_result":
                body = text_of(b.get("content"))
                what = calls.get(b.get("tool_use_id"), "?")
                sizes.append((len(body), what))
                if b.get("is_error"):
                    errors.append("%s -> %s" % (what, re.sub(r"\s+", " ", body)[:160]))
    sizes.sort(reverse=True)
    lines += ["## %s" % tag, "`%s` - %d assistant turns, %d tool calls, %d KB of tool results"
              % (path, turns, sum(names.values()), sum(s for s, _ in sizes) // 1024)]
    lines.append("- calls: " + (", ".join("%s %d" % kv for kv in names.most_common(8)) or "none"))
    for size, what in sizes[:3]:
        lines.append("- large result: %d KB from `%s`" % (size // 1024, what))
    for f, n in sorted(reads.items(), key=lambda kv: -kv[1]):
        if n >= 3:
            lines.append("- read %d times: `%s`" % (n, f))
    lines.append("- failed calls: %d" % len(errors))
    for e in errors[:5]:
        lines.append("  - `%s`" % e)
    lines.append("")

os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
with open(out, "w") as fh:
    fh.write("\n".join(lines))
print(out)
PY
