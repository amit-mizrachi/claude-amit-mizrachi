#!/usr/bin/env bash
# A stand-in for the `claude` CLI, so the recovery paths can be tested without a live harness.
#
# Put its directory first on PATH and point MOCK_STATE at a scratch directory:
#   MOCK_STATE=/tmp/x PATH="$(dirname mock)/bin:$PATH"
#
# State it reads and writes under $MOCK_STATE:
#   agents.json   the array `claude agents --json` returns. Tests write this.
#   launches      one line per `--bg` invocation: `<name> <resumed-sid>`. Tests read this.
#   next-sid      the sessionId the NEXT --bg launch should register (default: a fresh uuid-ish)
#   register      if 1, a --bg launch appends its new session to agents.json. Default 1.
#
# It supports only what the sprint's scripts actually call: `agents --json`, `stop`, and
# `--bg --resume`. Anything else exits 0 quietly so a stray call cannot fail a test for the
# wrong reason.

set -uo pipefail

S="${MOCK_STATE:?mock-claude needs MOCK_STATE}"
mkdir -p "$S"
[ -f "$S/agents.json" ] || printf '[]' > "$S/agents.json"

case "${1:-}" in
  agents)
    cat "$S/agents.json"
    exit 0
    ;;
  stop)
    printf '%s\n' "stop ${2:-}" >> "$S/stops"
    exit 0
    ;;
esac

# A --bg launch. Pull out -n <name> and --resume <sid>; ignore the rest.
name=""
resumed=""
prev=""
for a in "$@"; do
  case "$prev" in
    -n|--name) name="$a" ;;
    --resume)  resumed="$a" ;;
  esac
  prev="$a"
done

[ -n "$name" ] || exit 0

new_sid="$(cat "$S/next-sid" 2>/dev/null || echo)"
[ -n "$new_sid" ] || new_sid="mock-$(( $(wc -l < "$S/launches" 2>/dev/null || echo 0) + 1 ))-$name"
rm -f "$S/next-sid"

printf '%s %s %s\n' "$name" "${resumed:-none}" "$new_sid" >> "$S/launches"

if [ "$(cat "$S/register" 2>/dev/null || echo 1)" = "1" ]; then
  python3 - "$S/agents.json" "$name" "$new_sid" <<'PY'
import json, sys
path, name, sid = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    rows = json.load(open(path))
except Exception:
    rows = []
rows.append({"sessionId": sid, "id": sid[:8], "name": name,
             "state": "working", "status": "idle", "pid": None,
             "startedAt": 1000 + len(rows)})
json.dump(rows, open(path, "w"))
PY
fi
exit 0
