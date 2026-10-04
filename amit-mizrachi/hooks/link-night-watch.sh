#!/usr/bin/env bash
#
# Put `night-watch` on the PATH of a normal terminal, not only inside Claude Code.
#
# Fires on SessionStart. Claude Code already puts this plugin's bin/ on PATH for its own Bash
# tool, but a terminal you open yourself never sees that. So this links bin/night-watch into the
# first bin directory that is already on your PATH and that you can write: ~/.local/bin, ~/bin,
# /opt/homebrew/bin, /usr/local/bin. If none of them is on PATH, it uses ~/.local/bin anyway.
#
# It runs at every session start because a plugin update installs into a new versioned directory
# and removes the old one, which would leave the link pointing at nothing. Re-linking is one
# readlink when nothing changed.
#
# It never replaces a real file called night-watch, or a link to something that is not this
# plugin's copy. It prints nothing: SessionStart stdout goes into the session's context.

SRC="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}/bin/night-watch"
[ -f "$SRC" ] || exit 0
chmod +x "$SRC" 2>/dev/null

# Ours: a link to some version of this plugin's night-watch, or a link whose target is gone.
ours_or_free() {
  local target="$1" dest
  [ -e "$target" ] || [ -L "$target" ] || return 0
  [ -L "$target" ] || return 1
  dest="$(readlink "$target")"
  case "$dest" in
    */amit-mizrachi/bin/night-watch|*/amit-mizrachi/*/bin/night-watch) return 0 ;;
  esac
  [ -e "$target" ] || return 0
  return 1
}

link_into() {
  local target="$1/night-watch"
  ours_or_free "$target" || return 1
  [ "$(readlink "$target" 2>/dev/null)" = "$SRC" ] && return 0
  ln -sfn "$SRC" "$target" 2>/dev/null
}

for dir in "$HOME/.local/bin" "$HOME/bin" /opt/homebrew/bin /usr/local/bin; do
  case ":$PATH:" in *":$dir:"*) ;; *) continue ;; esac
  [ -d "$dir" ] && [ -w "$dir" ] || continue
  link_into "$dir"   # refuses when somebody's own night-watch is here; leave it first on PATH
  exit 0
done

mkdir -p "$HOME/.local/bin" 2>/dev/null && link_into "$HOME/.local/bin"
exit 0
