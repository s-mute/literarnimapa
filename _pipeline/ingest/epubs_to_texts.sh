#!/usr/bin/env bash
# Convert all .epub files in a folder to plain text files.
#
# Usage:
#   ./ingest/epubs_to_texts.sh <epub_dir> <output_dir>
#   ./ingest/epubs_to_texts.sh epubs/ texts/

set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <epub_dir> <output_dir>" >&2
    exit 1
fi

EPUB_DIR="$1"
OUT_DIR="$2"

if [[ ! -d "$EPUB_DIR" ]]; then
    echo "Error: directory not found: $EPUB_DIR" >&2
    exit 1
fi

if ! command -v pandoc &>/dev/null; then
    echo "Error: pandoc is not installed." >&2
    echo "  macOS:  brew install pandoc" >&2
    echo "  Linux:  apt install pandoc  or  https://pandoc.org/installing.html" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

count=0
skipped=0

for epub in "$EPUB_DIR"/*.epub; do
    [[ -f "$epub" ]] || { echo "No .epub files found in $EPUB_DIR" >&2; exit 0; }

    basename="${epub##*/}"
    stem="${basename%.epub}"
    out="$OUT_DIR/$stem.txt"

    if [[ -f "$out" ]]; then
        echo "Skipping (already exists): $out" >&2
        (( skipped++ )) || true
        continue
    fi

    echo "Converting: $basename → $stem.txt" >&2
    pandoc --to plain --wrap=none "$epub" -o "$out"
    (( count++ )) || true
done

echo "" >&2
echo "Done: $count converted, $skipped skipped → $OUT_DIR" >&2
