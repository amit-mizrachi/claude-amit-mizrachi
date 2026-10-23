#!/usr/bin/env bash
#
# Put `night-watch` and `project-studio` on the PATH of a normal terminal, not only inside Claude Code.
#
# Fires on SessionStart. Claude Code already puts this plugin's bin/ on PATH for its own Bash
# tool, but a terminal you open yourself never sees that. So this links each of bin/night-watch
# and bin/project-studio into the first bin directory that is already on your PATH and that you
# can write: ~/.local/bin, ~/bin, /opt/homebrew/bin, /usr/local/bin. If none of them is on PATH,
# it uses ~/.local/bin anyway.
#
# It runs at every session start because a plugin update installs into a new versioned directory
# and removes the old one, which would leave the links pointing at nothing. Re-linking is one
# readlink per name when nothing changed.
#
# It never replaces a real file with one of these names, or a link to something that is not this
# plugin's copy. It prints nothing: SessionStart stdout goes into the session's context.

BIN="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}/bin"
NAMES="night-watch project-studio"

# Ours: a link to some version of this plugin's <name>, or a link whose target is gone.
ours_or_free() {
  local target="$1" name="$2" dest
  [ -e "$target" ] || [ -L "$target" ] || return 0
  [ -L "$target" ] || return 1
  dest="$(readlink "$target")"
  case "$dest" in
    */amit-mizrachi/bin/"$name"|*/amit-mizrachi/*/bin/"$name") return 0 ;;
  esac
  [ -e "$target" ] || return 0
  return 1
}

# Link every name into $1; a name somebody else owns there is left alone (theirs stays first on PATH).
link_into() {
  local dir="$1" name src target
  for name in $NAMES; do
    src="$BIN/$name"
    [ -f "$src" ] || continue
    chmod +x "$src" 2>/dev/null
    target="$dir/$name"
    ours_or_free "$target" "$name" || continue
    [ "$(readlink "$target" 2>/dev/null)" = "$src" ] && continue
    ln -sfn "$src" "$target" 2>/dev/null
  done
}

for dir in "$HOME/.local/bin" "$HOME/bin" /opt/homebrew/bin /usr/local/bin; do
  case ":$PATH:" in *":$dir:"*) ;; *) continue ;; esac
  [ -d "$dir" ] && [ -w "$dir" ] || continue
  link_into "$dir"
  exit 0
done

mkdir -p "$HOME/.local/bin" 2>/dev/null && link_into "$HOME/.local/bin"
exit 0
