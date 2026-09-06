#!/usr/bin/env bash
# Pack data/ into a split .tar.gz for a GitHub release and write data.manifest.
#
#   scripts/bundle_data.sh [release-tag]
#
# Bundles data/nuscenes, data/models and data/cache. Skips data/downloads and
# the bundle output itself. Parts stay under GitHub's 2 GB per-file limit.
# Afterwards, upload every data/bundle/*.part-* file to the release named by
# the tag, then commit data.manifest.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:-data-v1}"
REPO_URL="https://github.com/nathanaday/autonomous-vehicle-sandbox"
OUT="$ROOT/data/bundle"
NAME="av-sandbox-data.tar.gz"
PART_SIZE="1900m"

cd "$ROOT/data"
for d in nuscenes models cache; do
  [ -d "$d" ] || { echo "missing data/$d" >&2; exit 1; }
done

rm -rf "$OUT" && mkdir -p "$OUT"
echo "Archiving data/{nuscenes,models,cache} ..."
COPYFILE_DISABLE=1 tar --exclude '.DS_Store' -cf - nuscenes models cache | gzip -1 > "$OUT/$NAME"

echo "Splitting into $PART_SIZE parts ..."
(cd "$OUT" && split -b "$PART_SIZE" -a 2 "$NAME" "$NAME.part-")

sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
size() { stat -f %z "$1" 2>/dev/null || stat -c %s "$1"; }

{
  echo "# Data bundle for autonomous-vehicle-sandbox. Read by scripts/sync_data.sh."
  echo "# Regenerate with scripts/bundle_data.sh; edit url_base if the release moves."
  echo "url_base $REPO_URL/releases/download/$TAG"
  echo "archive $NAME $(sha "$OUT/$NAME") $(size "$OUT/$NAME")"
  for p in "$OUT/$NAME".part-*; do
    echo "part $(basename "$p") $(sha "$p") $(size "$p")"
  done
} > "$ROOT/data.manifest"

rm "$OUT/$NAME"
echo
cat "$ROOT/data.manifest"
echo
echo "Upload these to the '$TAG' release at $REPO_URL/releases:"
ls -lh "$OUT"
