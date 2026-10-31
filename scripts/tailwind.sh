#!/usr/bin/env bash
# Linux/macOS/CI equivalent of tailwind.ps1. Usage: scripts/tailwind.sh [--watch]
set -euo pipefail
VERSION="${TAILWIND_VERSION:-v4.3.3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="$ROOT/.tools"; EXE="$TOOLS/tailwindcss"
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  ASSET="tailwindcss-linux-x64" ;;
  Linux-aarch64) ASSET="tailwindcss-linux-arm64" ;;
  Darwin-arm64)  ASSET="tailwindcss-macos-arm64" ;;
  Darwin-x86_64) ASSET="tailwindcss-macos-x64" ;;
  *) echo "unsupported platform"; exit 1 ;;
esac
if [ ! -x "$EXE" ]; then
  mkdir -p "$TOOLS"
  curl -sSL "https://github.com/tailwindlabs/tailwindcss/releases/download/$VERSION/$ASSET" -o "$EXE"
  chmod +x "$EXE"
fi
"$EXE" -i "$ROOT/app/static/src/input.css" -o "$ROOT/app/static/css/app.css" --minify "$@"
