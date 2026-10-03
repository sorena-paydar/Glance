#!/bin/sh
# Glance installer for macOS and Linux:
#
#   curl -fsSL https://sorena-paydar.github.io/Glance/install.sh | sh
#
# Installs uv if needed, installs the `glance` command, then starts guided setup.
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

# uv downloads Python 3.12 by itself if it isn't installed.
uv tool install --force --python 3.12 "$SOURCE"
uv tool update-shell >/dev/null 2>&1 || true

BIN="$(uv tool dir --bin)"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) PATH="$BIN:$PATH"; export PATH ;;
esac

say "==> Glance installed. Run 'glance' any time to start it."

if [ -z "${GLANCE_NO_SETUP:-}" ] && [ -t 1 ] && (: </dev/tty) 2>/dev/null; then
  say "==> Starting setup"
  exec glance </dev/tty
fi
