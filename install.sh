#!/usr/bin/env bash
# localcode installer — sets up the `localcode` command and runs first-time setup.
set -e

echo "🐙 installing localcode…"

PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "error: python3 is required." >&2
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"

# Prefer pipx (isolated), fall back to pip --user.
if command -v pipx >/dev/null 2>&1; then
  echo "→ installing with pipx"
  pipx install --force "$HERE"
else
  echo "→ installing with pip (--user)"
  "$PY" -m pip install --user --break-system-packages -e "$HERE" 2>/dev/null \
    || "$PY" -m pip install --user -e "$HERE"
fi

echo
echo "✓ installed. running first-time setup…"
echo
# Run the setup wizard so the user configures their model/key right away.
if command -v localcode >/dev/null 2>&1; then
  localcode setup || true
  echo
  echo "done — start it any time with:  localcode"
else
  echo "installed, but 'localcode' isn't on your PATH yet."
  echo "add your user bin dir to PATH (e.g. ~/.local/bin), then run:  localcode setup"
fi
