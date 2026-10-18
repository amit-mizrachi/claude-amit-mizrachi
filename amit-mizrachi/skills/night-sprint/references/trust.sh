#!/usr/bin/env bash
# night-sprint workspace trust - let `claude --bg` start in the folders a run creates.
#
#   trust.sh <DIR> [DIR ...]
#
# bootstrap.sh runs it on a research sprint's <WS>/work, and launch.sh runs it before every
# `claude --bg` whose folder belongs to the run (see launch.sh for which folders those are).
# Never point it at a folder the run did not create, and never at the user's repo: the user has
# already opened that one in Claude Code.
#
# WHY. `claude --bg` refuses an untrusted folder - "Workspace not trusted. Run `claude` in <dir>
# once and accept the trust prompt, then retry." - and a background run has nobody to accept a
# dialog. Every product-research run stalled on its first ticket this way, because bootstrap.sh
# makes <WS>/work a new git repo each run; on 2026-10-16 that cost about 16 hours before the
# conductor set the flag itself. Trusting a parent folder does not help: Claude Code looks for
# trust from the session's folder upwards only as far as the git root, and <WS>/work is a git
# root of its own. Only an entry for the exact folder works.
#
# HOW. Set `projects[<dir>].hasTrustDialogAccepted` in the global config, which is what accepting
# the dialog does. The write is atomic (temp file + rename, same mode) and is read back, because
# a running Claude Code process can save the same file at the same moment and drop the key. Both
# the logical and the physical path are trusted, so a symlinked folder (/tmp on macOS) is covered.
# A folder already trusted costs one read and no write.
#
# Exit 0: every folder is trusted. Exit 1: refused or could not write - the message says what to
# run by hand instead.

set -uo pipefail

[ $# -ge 1 ] || { echo "usage: trust.sh <DIR> [DIR ...]" >&2; exit 1; }

CONFIG="${CLAUDE_CONFIG_DIR:-$HOME}/.claude.json"

paths=()
for d in "$@"; do
  [ -d "$d" ] || { echo "trust: no folder at $d" >&2; exit 1; }
  logical="$(cd "$d" && pwd)"
  physical="$(cd "$d" && pwd -P)"
  for p in "$logical" "$physical"; do
    case "$p" in
      /|"$HOME"|"$HOME"/.claude|"$HOME"/.claude/*)
        echo "trust: refusing $p - only a folder the run created may be trusted this way" >&2
        exit 1 ;;
    esac
  done
  paths+=("$logical")
  [ "$physical" != "$logical" ] && paths+=("$physical")
done

python3 - "$CONFIG" "${paths[@]}" <<'PY'
import json, os, sys, tempfile, time

config, paths = sys.argv[1], sys.argv[2:]

def load():
    try:
        with open(config) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}

def untrusted(cfg):
    projects = cfg.get("projects") or {}
    return [p for p in paths if (projects.get(p) or {}).get("hasTrustDialogAccepted") is not True]

for attempt in range(3):
    cfg = load()
    todo = untrusted(cfg)
    if not todo:
        break
    projects = cfg.setdefault("projects", {})
    for p in todo:
        projects.setdefault(p, {})["hasTrustDialogAccepted"] = True
    mode = os.stat(config).st_mode & 0o777 if os.path.exists(config) else 0o600
    fd, tmp = tempfile.mkstemp(prefix=".claude.json.", dir=os.path.dirname(config) or ".")
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh, indent=2)
    os.chmod(tmp, mode)
    os.replace(tmp, config)
    time.sleep(1)

left = untrusted(load())
if left:
    sys.stderr.write("trust: could not keep the trust flag for: %s\n" % " ".join(left))
    sys.exit(1)
PY
rc=$?
if [ $rc -ne 0 ]; then
  echo "trust: do it by hand instead - for each folder, run \`claude\` in it, accept the trust dialog, then /exit:" >&2
  for d in "$@"; do echo "  cd $(cd "$d" && pwd) && claude" >&2; done
fi
exit $rc
