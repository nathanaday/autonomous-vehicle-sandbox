#!/usr/bin/env bash
# Download data bundles from GitHub releases, verify them, and extract them
# into data/. Safe to rerun: finished downloads are resumed or skipped, and a
# bundle already on disk is left alone.
#
#   scripts/sync_data.sh                  # the dataset bundle, required
#   scripts/sync_data.sh depth splat      # the optional bundles
#   KEEP_PARTS=1 scripts/sync_data.sh     # keep the downloaded parts afterwards
#
# Bundles, from data.manifest: dataset (nuScenes v1.0-mini), depth (Depth
# Anything V2 checkpoint, depth and fusion caches), splat (Depth Anything 3
# checkpoint, splat cache). Needs curl and shasum (macOS) or sha256sum (Linux),
# and free disk of about twice a bundle's size while it extracts.
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

# A file whose presence means the bundle is installed.
marker() {
  case "$1" in
    dataset) echo "nuscenes/v1.0-mini/scene.json" ;;
    depth) echo "models/depth-anything-v2/depth_anything_v2_vitb.pth" ;;
    splat) echo "models/da3/DA3NESTED-GIANT-LARGE-1.1/model.safetensors" ;;
    *) echo "unknown bundle '$1'; choose from dataset, depth, splat" >&2; exit 1 ;;
  esac
}

manifest_lines() { grep -v '^#' "$MANIFEST" | awk -v k="$1" -v b="$2" '$1 == k && $2 == b'; }

sync_bundle() {
  local bundle="$1"
  local mark; mark="$(marker "$bundle")"
  if [ -e "$DATA/$mark" ]; then
    echo "$bundle: already installed (data/$mark exists)"
    return
  fi
  local archive archive_sha archive_size url_base
  read -r _ _ archive archive_sha archive_size url_base < <(manifest_lines bundle "$bundle")
  [ -n "${archive:-}" ] || { echo "$bundle: not in data.manifest" >&2; exit 1; }
  local parts=() part_shas=()
  while read -r _ _ name want _; do parts+=("$name"); part_shas+=("$want"); done < <(manifest_lines part "$bundle")
  [ ${#parts[@]} -gt 0 ] || { echo "$bundle: no parts in data.manifest" >&2; exit 1; }

  mkdir -p "$DL"
  echo "$bundle: downloading ${#parts[@]} parts from $url_base"
  local i name want dest got
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

  echo "$bundle: joining and verifying the archive ($archive_size bytes) ..."
  local joined="$DL/$archive"
  cat "${parts[@]/#/$DL/}" > "$joined"
  got="$(sha "$joined")"
  if [ "$got" != "$archive_sha" ]; then
    echo "archive checksum mismatch: expected $archive_sha, got $got" >&2
    rm -f "$joined"
    exit 1
  fi

  echo "$bundle: extracting into data/ ..."
  mkdir -p "$DATA"
  tar -xzf "$joined" -C "$DATA"
  rm -f "$joined"
  if [ -z "${KEEP_PARTS:-}" ]; then rm -f "${parts[@]/#/$DL/}"; fi
  [ -e "$DATA/$mark" ] || { echo "$bundle: extraction is incomplete, data/$mark is missing" >&2; exit 1; }
  echo "$bundle: ok, data/$mark"
}

bundles=("$@")
[ ${#bundles[@]} -gt 0 ] || bundles=(dataset)
for b in "${bundles[@]}"; do marker "$b" >/dev/null; done
for b in "${bundles[@]}"; do sync_bundle "$b"; done
echo "Done. Restart the backend if it is running, or run 'make backend' and 'make frontend', or 'make demo'."
