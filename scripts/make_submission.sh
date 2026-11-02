#!/usr/bin/env bash
# Build the single submission file <roll_number>.zip:
#   the source tree exactly as in the commit tagged "final" (git archive), which contains
#   report/report.pdf and README.md, plus the scanned handwritten reflection <roll_number>.pdf.
#
#   scripts/make_submission.sh <roll_number> [path/to/<roll_number>.pdf]
set -euo pipefail
cd "$(dirname "$0")/.."
ROLL=${1:?usage: scripts/make_submission.sh <roll_number> [path/to/<roll_number>.pdf]}
REFLECTION=${2:-$ROLL.pdf}
REF=${REF:-final}

[[ "$ROLL" =~ ^[A-Za-z0-9]+$ ]] || { echo "the roll number must contain only letters and digits"; exit 1; }
[ -f "$REFLECTION" ] || { echo "missing the scanned handwritten reflection: $REFLECTION"; exit 1; }
[ "$(basename "$REFLECTION")" = "$ROLL.pdf" ] || { echo "the reflection must be named exactly $ROLL.pdf"; exit 1; }
git rev-parse -q --verify "refs/tags/$REF" >/dev/null || { echo "tag $REF does not exist"; exit 1; }

tmp=$(mktemp -d)
git archive "$REF" | tar -x -C "$tmp"
for f in report/report.pdf README.md AI_USE.md Makefile; do
  [ -f "$tmp/$f" ] || { echo "$f is missing from $REF"; exit 1; }
done
cp "$REFLECTION" "$tmp/$ROLL.pdf"
rm -f "$ROLL.zip"
(cd "$tmp" && zip -qrX "$OLDPWD/$ROLL.zip" .)
rm -rf "$tmp"
echo "wrote $ROLL.zip ($(du -h "$ROLL.zip" | cut -f1)) from tag $REF ($(git rev-parse --short "$REF"))"
unzip -l "$ROLL.zip" | tail -1
