#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-$HOME/.local/bin}"
COMMANDS=(zcode-review zcode-review-watch)

mkdir -p "$TARGET_DIR"
for command in "${COMMANDS[@]}"; do
    chmod +x "$SOURCE_DIR/$command"
    ln -sf "$SOURCE_DIR/$command" "$TARGET_DIR/$command"
    echo "linked $TARGET_DIR/$command"
done

case ":$PATH:" in
    *":$TARGET_DIR:"*) ;;
    *) echo "add to PATH: export PATH=\"$TARGET_DIR:\$PATH\"" ;;
esac
