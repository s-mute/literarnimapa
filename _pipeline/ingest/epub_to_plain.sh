#!/usr/bin/env bash
# Convert epub to plain text suitable for poem_segment.py.
# Strips all formatting, preserves line structure.
#
# Usage:
#   ./ingest/epub_to_plain.sh input.epub > output.txt
#   ./ingest/epub_to_plain.sh input.epub output.txt

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <input.epub> [output.txt]" >&2
    exit 1
fi

EPUB="$1"
OUTPUT="${2:-}"

if [[ ! -f "$EPUB" ]]; then
    echo "Error: file not found: $EPUB" >&2
    exit 1
fi

if ! command -v pandoc &>/dev/null; then
    echo "Error: pandoc is not installed." >&2
    echo "  macOS:  brew install pandoc" >&2
    echo "  Linux:  apt install pandoc  or  https://pandoc.org/installing.html" >&2
    exit 1
fi

if [[ -n "$OUTPUT" ]]; then
    pandoc --to plain --wrap=none "$EPUB" -o "$OUTPUT"
    echo "Written: $OUTPUT" >&2
else
    pandoc --to plain --wrap=none "$EPUB"
fi
