#!/bin/sh
# Glance installer for macOS and Linux:
#
#   curl -fsSL https://sorena-paydar.github.io/Glance/install.sh | sh
#
# Installs uv if needed, installs the `glance` command, adds Glance to the desktop,
# then starts guided setup.
# Set GLANCE_NO_SETUP=1 to skip setup.
set -eu

SOURCE="${GLANCE_SOURCE:-glance[tray] @ https://github.com/sorena-paydar/Glance/archive/refs/heads/main.zip}"

say() { printf '%s\n' "$*"; }

say "==> Installing Glance"

if ! command -v uv >/dev/null 2>&1; then
  say "==> Installing uv (Python package manager)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  for dir in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    if [ -x "$dir/uv" ]; then PATH="$dir:$PATH"; fi
  done
  export PATH
fi

# Use uv's standalone Python: Homebrew's framework Python relaunches itself as
# "Python.app", so macOS would check Python's permissions instead of Glance's.
uv tool install --force --managed-python --python 3.12 "$SOURCE"
uv tool update-shell >/dev/null 2>&1 || true

BIN="$(uv tool dir --bin)"
NEW_PATH=""
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) PATH="$BIN:$PATH"; export PATH; NEW_PATH=1 ;;
esac

glance desktop || say "(Could not add Glance to the desktop; run 'glance desktop' later.)"
say "==> Glance installed. Open it from your Desktop, or run 'glance'."
if [ -n "$NEW_PATH" ]; then
  say "    (Open a new terminal window to use the 'glance' command.)"
fi

if [ -n "${GLANCE_NO_SETUP:-}" ]; then
  exit 0
fi
if [ "$(uname -s)" = "Darwin" ] && [ -d "$HOME/Applications/Glance.app" ]; then
  # Setup continues in the app, so macOS grants permissions to Glance itself.
  say "==> Opening Glance"
  open "$HOME/Applications/Glance.app"
elif [ -t 1 ] && (: </dev/tty) 2>/dev/null; then
  say "==> Starting setup"
  exec glance </dev/tty
fi
