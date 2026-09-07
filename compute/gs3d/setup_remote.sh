#!/usr/bin/env bash
# Set up a CUDA machine (tested against Lambda's Ubuntu 22.04 images) to run
# the official 3D Gaussian Splatting trainer. Installs into the directory
# that holds this script's parent, so with the layout make gs3d-push creates:
#
#   ~/av-gs3d/gs3d/setup_remote.sh   this script, train.py
#   ~/av-gs3d/gaussian-splatting/    the official repository with its CUDA extensions built
#   ~/av-gs3d/.venv/                 Python 3.11 with torch for the machine's CUDA
#   ~/av-gs3d/export/, runs/, cache/ scenes in, results out
#
# Safe to rerun: each step is skipped when its result exists.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$ROOT/gaussian-splatting"
VENV="$ROOT/.venv"
GS_COMMIT="${GS_COMMIT:-main}"

command -v nvidia-smi >/dev/null || { echo "nvidia-smi not found: this needs an NVIDIA GPU machine" >&2; exit 1; }
if ! command -v nvcc >/dev/null; then
  if [ -x /usr/local/cuda/bin/nvcc ]; then
    export PATH="/usr/local/cuda/bin:$PATH"
  else
    echo "nvcc not found; the rasteriser is a CUDA extension and needs the toolkit (apt install cuda-toolkit-12-x, or a Lambda Stack image)" >&2
    exit 1
  fi
fi
CUDA_VERSION="$(nvcc --version | sed -n 's/.*release \([0-9]*\)\.\([0-9]*\).*/\1\2/p')"
case "$CUDA_VERSION" in
  118) TORCH_INDEX="https://download.pytorch.org/whl/cu118" ;;
  121|122|123) TORCH_INDEX="https://download.pytorch.org/whl/cu121" ;;
  124|125) TORCH_INDEX="https://download.pytorch.org/whl/cu124" ;;
  126|127) TORCH_INDEX="https://download.pytorch.org/whl/cu126" ;;
  *) TORCH_INDEX="https://download.pytorch.org/whl/cu128" ;;
esac
echo "CUDA toolkit $CUDA_VERSION, torch wheels from $TORCH_INDEX"
nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader

if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -d "$REPO" ]; then
  git clone --recursive https://github.com/graphdeco-inria/gaussian-splatting.git "$REPO"
  (cd "$REPO" && git checkout -q "$GS_COMMIT" && git submodule update --init --recursive)
fi
(cd "$REPO" && echo "gaussian-splatting at $(git rev-parse --short HEAD)")

if [ ! -x "$VENV/bin/python" ]; then
  uv venv --python 3.11 "$VENV"
fi
"$VENV/bin/python" -c "import torch" 2>/dev/null || \
  uv pip install --python "$VENV/bin/python" torch torchvision --index-url "$TORCH_INDEX"
uv pip install --python "$VENV/bin/python" ninja plyfile tqdm opencv-python-headless joblib

# The three CUDA extensions build against the venv's torch, for this GPU only.
export TORCH_CUDA_ARCH_LIST="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1)"
for sub in diff-gaussian-rasterization simple-knn fused-ssim; do
  mod="${sub//-/_}"
  [ "$sub" = "simple-knn" ] && mod="simple_knn._C"
  [ "$sub" = "diff-gaussian-rasterization" ] && mod="diff_gaussian_rasterization"
  if ! "$VENV/bin/python" -c "import $mod" 2>/dev/null; then
    echo "building $sub for sm_$TORCH_CUDA_ARCH_LIST ..."
    uv pip install --python "$VENV/bin/python" --no-build-isolation "$REPO/submodules/$sub"
  fi
done

mkdir -p "$ROOT/export" "$ROOT/runs" "$ROOT/cache/gs3d"
"$VENV/bin/python" - <<'EOF'
import torch, diff_gaussian_rasterization, simple_knn._C, fused_ssim  # noqa
print(f"torch {torch.__version__}, cuda {torch.version.cuda}, {torch.cuda.get_device_name(0)}: ready")
EOF
echo "Train with: $VENV/bin/python $ROOT/gs3d/train.py export/<scene>"
