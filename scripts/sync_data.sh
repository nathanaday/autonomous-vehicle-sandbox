#!/usr/bin/env bash
# Download the data bundle from GitHub releases, verify it, and extract it
# into data/. Safe to rerun: finished downloads are resumed or skipped.
#
#   scripts/sync_data.sh            # download, verify, extract
#   KEEP_PARTS=1 scripts/sync_data.sh   # keep the downloaded parts afterwards
#
# Needs curl and shasum (macOS) or sha256sum (Linux). About 4.6 GB download
# and 6 GB extracted; keep 11 GB free while it runs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$ROOT/data.manifest"
DATA="$ROOT/data"
DL="$DATA/downloads"

[ -f "$MANIFEST" ] || { echo "no data.manifest at $ROOT" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }
if command -v shasum >/dev/null; then sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
elif command -v sha256sum >/dev/null; then sha() { sha256sum "$1" | cut -d' ' -f1; }
else echo "shasum or sha256sum is required" >&2; exit 1; fi

url_base=""; archive=""; archive_sha=""; archive_size=""
parts=(); part_shas=()
while read -r key a b c; do
  case "$key" in
    url_base) url_base="$a" ;;
    archive) archive="$a"; archive_sha="$b"; archive_size="$c" ;;
    part) parts+=("$a"); part_shas+=("$b") ;;
  esac
done < <(grep -v '^#' "$MANIFEST")
[ -n "$url_base" ] && [ ${#parts[@]} -gt 0 ] || { echo "data.manifest is incomplete" >&2; exit 1; }

if [ -f "$DATA/nuscenes/v1.0-mini/scene.json" ] && [ -d "$DATA/models" ] && [ -d "$DATA/cache" ]; then
  echo "data/ already contains the dataset, model and cache. Nothing to do."
  echo "Delete data/nuscenes, data/models or data/cache to force a fresh sync."
  exit 0
fi

mkdir -p "$DL"
echo "Downloading ${#parts[@]} parts from $url_base"
for i in "${!parts[@]}"; do
  name="${parts[$i]}"; want="${part_shas[$i]}"; dest="$DL/$name"
  if [ -f "$dest" ] && [ "$(sha "$dest")" = "$want" ]; then
    echo "  $name  already downloaded and verified"
    continue
  fi
  echo "  $name"
  curl -L --fail --retry 5 --retry-delay 3 -C - -o "$dest" "$url_base/$name" || {
    # curl exits 33 when a completed file cannot be resumed; treat as done and verify below
    [ -f "$dest" ] || exit 1
  }
  got="$(sha "$dest")"
  if [ "$got" != "$want" ]; then
    echo "checksum mismatch for $name" >&2
    echo "  expected $want" >&2
    echo "  got      $got" >&2
    echo "Delete $dest and rerun." >&2
    exit 1
  fi
done

echo "Joining and verifying the archive ($archive_size bytes) ..."
joined="$DL/$archive"
cat "${parts[@]/#/$DL/}" > "$joined"
got="$(sha "$joined")"
if [ "$got" != "$archive_sha" ]; then
  echo "archive checksum mismatch: expected $archive_sha, got $got" >&2
  rm -f "$joined"
  exit 1
fi

echo "Extracting into data/ ..."
tar -xzf "$joined" -C "$DATA"
rm -f "$joined"
if [ -z "${KEEP_PARTS:-}" ]; then rm -f "${parts[@]/#/$DL/}"; fi

ok=1
for path in nuscenes/v1.0-mini/scene.json nuscenes/samples/CAM_FRONT models/depth-anything-v2 cache/depth; do
  if [ -e "$DATA/$path" ]; then echo "  ok  data/$path"; else echo "  missing  data/$path" >&2; ok=0; fi
done
[ "$ok" = 1 ] || { echo "extraction is incomplete" >&2; exit 1; }
echo "Done. Run 'make backend' and 'make frontend', or 'make demo'."
