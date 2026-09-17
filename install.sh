#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"

[[ -x "$REPO_DIR/bin/claude-or" ]] || chmod +x "$REPO_DIR/bin/claude-or"
command -v python3 >/dev/null 2>&1 || {
  echo "install.sh: python3 is required" >&2
  exit 1
}

mkdir -p "$BIN_DIR"
ln -sfn "$REPO_DIR/bin/claude-or" "$BIN_DIR/claude-or"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "Add $BIN_DIR to PATH, for example:"
  echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
fi

echo "Installed $BIN_DIR/claude-or -> $REPO_DIR/bin/claude-or"
echo
echo "Next:"
echo "  claude-or key"
echo "  claude-or"
echo
echo "Do not export ANTHROPIC_BASE_URL in your shell profile."
echo "That would hijack every \`claude\` session. This tool uses an isolated profile."
