#!/usr/bin/env bash
# Download the model checkpoints the compute CLI needs into data/models.
# Only for computing new results; viewing the data bundles needs no model.
#
#   scripts/fetch_models.sh          # both
#   scripts/fetch_models.sh depth    # Depth Anything V2 ViT-B, 372 MB, Apache 2.0
#   scripts/fetch_models.sh splat    # Depth Anything 3 nested Giant + Large, 6.8 GB, CC BY-NC 4.0
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS="$ROOT/data/models"
which="${1:-all}"

fetch() { curl -L --fail --retry 5 --retry-delay 3 -C - -o "$2" "$1" || [ -f "$2" ]; }

if [ "$which" = all ] || [ "$which" = depth ]; then
  dest="$MODELS/depth-anything-v2"
  mkdir -p "$dest"
  fetch "https://huggingface.co/depth-anything/Depth-Anything-V2-Base/resolve/main/depth_anything_v2_vitb.pth" \
    "$dest/depth_anything_v2_vitb.pth"
  echo "Depth Anything V2 checkpoint at $dest"
fi
if [ "$which" = all ] || [ "$which" = splat ]; then
  name="DA3NESTED-GIANT-LARGE-1.1"
  dest="$MODELS/da3/$name"
  base="https://huggingface.co/depth-anything/$name/resolve/main"
  mkdir -p "$dest"
  fetch "$base/config.json" "$dest/config.json"
  fetch "$base/model.safetensors" "$dest/model.safetensors"
  echo "Depth Anything 3 checkpoint at $dest"
fi
