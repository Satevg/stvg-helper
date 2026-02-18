#!/usr/bin/env bash
set -euo pipefail

FILE_PATH=$(cat | jq -r '.tool_input.file_path // empty')

if [[ "$FILE_PATH" != *.py ]]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
make lint