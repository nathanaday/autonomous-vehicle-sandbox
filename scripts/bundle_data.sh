#!/usr/bin/env bash
# Pack data/ into split .tar.gz bundles for a GitHub release and update
# data.manifest.
#
#   scripts/bundle_data.sh <release-tag> [dataset] [depth] [fusion] [splat] [gs3d] [occ3d]   # default: all six
#   SCENES="scene-0061 scene-0103" scripts/bundle_data.sh data-v3 splat
#
# Bundles hold only the listed scenes (default: the three in SCENES below):
#   dataset  the nuScenes tables and each scene's keyframe files, no sweeps
#   depth    Depth Anything predictions and per-scene summaries
#   fusion   fused meshes
#   splat    Gaussian splats
#   gs3d     trained Gaussian splats
#   occ3d    Occ3D-nuScenes occupancy labels
# scripts/list_files.py chooses the files. Each bundle's parts stay under
# GitHub's 2 GB per-file limit and go to data/bundle/<name>/. The manifest
# keeps its lines for bundles not rebuilt, with the release URL they were
# uploaded to, so one bundle can be re-released under a new tag without
# touching the others. Afterwards, upload the parts to the release named by
# the tag (the script prints the command), then commit data.manifest.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:-}"
[ -n "$TAG" ] || { echo "usage: scripts/bundle_data.sh <release-tag> [dataset] [depth] [fusion] [splat] [gs3d] [occ3d]" >&2; exit 1; }
shift
SCENES="${SCENES:-scene-0061 scene-0103 scene-1094}"
REPO_URL="https://github.com/nathanaday/autonomous-vehicle-sandbox"
URL_BASE="$REPO_URL/releases/download/$TAG"
OUT="$ROOT/data/bundle"
MANIFEST="$ROOT/data.manifest"
PART_SIZE="1900m"

sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
size() { stat -f %z "$1" 2>/dev/null || stat -c %s "$1"; }

bundles=("$@")
[ ${#bundles[@]} -gt 0 ] || bundles=(dataset depth fusion splat gs3d occ3d)
for b in "${bundles[@]}"; do
  case "$b" in dataset|depth|fusion|splat|gs3d|occ3d) ;; *) echo "unknown bundle '$b'" >&2; exit 1 ;; esac
done

cd "$ROOT/data"
new_lines="$(mktemp)"
for b in "${bundles[@]}"; do
  name="av-sandbox-$b.tar.gz"
  dir="$OUT/$b"
  rm -rf "$dir" && mkdir -p "$dir"
  list="$dir/files.txt"
  # shellcheck disable=SC2086
  (cd "$ROOT" && uv run --project backend python scripts/list_files.py "$b" $SCENES) > "$list"
  echo "$b: archiving $(wc -l < "$list" | tr -d ' ') files for $SCENES ..."
  COPYFILE_DISABLE=1 tar --exclude '.DS_Store' -cf - -T "$list" | gzip -1 > "$dir/$name"
  rm "$list"
  echo "$b: splitting into $PART_SIZE parts ..."
  (cd "$dir" && split -b "$PART_SIZE" -a 2 "$name" "$name.part-")
  echo "bundle $b $name $(sha "$dir/$name") $(size "$dir/$name") $URL_BASE" >> "$new_lines"
  for p in "$dir/$name".part-*; do
    echo "part $b $(basename "$p") $(sha "$p") $(size "$p")" >> "$new_lines"
  done
  rm "$dir/$name"
done

# keep the manifest lines of bundles that were not rebuilt
kept="$(mktemp)"
if [ -f "$MANIFEST" ]; then
  grep -v '^#' "$MANIFEST" | awk -v names=" ${bundles[*]} " 'index(names, " " $2 " ") == 0' > "$kept" || true
fi
{
  echo "# Data bundles for autonomous-vehicle-sandbox. Read by scripts/sync_data.sh."
  echo "# Regenerate a bundle with scripts/bundle_data.sh <tag> <bundle>."
  echo "# bundle <name> <archive> <sha256> <bytes> <release url>"
  echo "# part <name> <file> <sha256> <bytes>"
  for b in dataset depth fusion splat gs3d occ3d; do
    awk -v b="$b" '$2 == b' "$kept" "$new_lines"
  done
} > "$MANIFEST"
rm -f "$kept" "$new_lines"

echo
cat "$MANIFEST"
echo
echo "Upload the parts to the '$TAG' release, then commit data.manifest:"
echo "  gh release create $TAG --title 'Data bundles $TAG' --notes 'See DETAILS.md, Data.'   # once per tag"
for b in "${bundles[@]}"; do
  echo "  gh release upload $TAG data/bundle/$b/*.part-*"
done
