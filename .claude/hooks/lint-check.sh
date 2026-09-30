#!/usr/bin/env bash
set -e

# Claude Code passes event details as JSON over stdin
INPUT=$(cat)

# Extract tool name and file path or command from stdin
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Determine modified files via git status if path isn't directly passed
MODIFIED_FILES=$(git status --porcelain | awk '{print $2}')

STATUS=0

# Check for TypeScript changes (.ts, .tsx)
if echo "$MODIFIED_FILES" | grep -qE '\.(ts|tsx)$'; then
  echo "TypeScript changes detected. Running pnpm lint..."
  pnpm -r lint || STATUS=1
fi

# Check for Python changes (.py)
if echo "$MODIFIED_FILES" | grep -qE '\.py$'; then
  echo "Python changes detected. Running ruff check and format..."
  uvx ruff check . || STATUS=1
  uvx ruff format --check . || STATUS=1
fi

exit $STATUS