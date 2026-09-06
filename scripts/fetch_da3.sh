#!/usr/bin/env bash
# Download the Depth Anything 3 checkpoint used by the Gaussian splat view.
# 6.8 GB from Hugging Face; resumes if interrupted. CC BY-NC 4.0 license.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="DA3NESTED-GIANT-LARGE-1.1"
DEST="$ROOT/data/models/da3/$NAME"
BASE="https://huggingface.co/depth-anything/$NAME/resolve/main"
mkdir -p "$DEST"
curl -sL --fail -o "$DEST/config.json" "$BASE/config.json"
curl -L --fail --retry 5 --retry-delay 3 -C - -o "$DEST/model.safetensors" "$BASE/model.safetensors"
echo "Depth Anything 3 checkpoint at $DEST"
