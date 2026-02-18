#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR=$(mktemp -d)
ZIP_FILE="$PROJECT_ROOT/lambda.zip"

echo "Installing dependencies..."
pip install -r "$PROJECT_ROOT/bot/requirements.txt" -t "$BUILD_DIR" --quiet

echo "Copying bot code..."
cp "$PROJECT_ROOT/bot/handler.py" "$BUILD_DIR/"

echo "Creating deployment package..."
cd "$BUILD_DIR"
zip -r "$ZIP_FILE" . --quiet

echo "Cleaning up..."
rm -rf "$BUILD_DIR"

echo "Package created: $ZIP_FILE"
echo "Size: $(du -h "$ZIP_FILE" | cut -f1)"
