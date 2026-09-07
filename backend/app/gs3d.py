"""Trained Gaussian splats of whole scenes from the cache.

compute/gs3d/train.py runs the official 3D Gaussian Splatting trainer on a
scene exported by compute/gs3d/export.py and writes one 3DGS PLY per scene
and option set, in the scene frame (the ego frame of the first keyframe),
with a JSON sidecar of stats and the per-keyframe ego poses in that frame.
This module only names and reads those files.
"""

from __future__ import annotations

import json
from pathlib import Path

IMAGE_SETS = ("kf", "sweeps")


def gs3d_key(scene_token: str, images: str, mask_moving: bool, depth_prior: bool) -> str:
    return f"{scene_token[:12]}_{images}_m{int(mask_moving)}_d{int(depth_prior)}"


def gs3d_label(meta: dict) -> str:
    parts = ["keyframes" if meta["images"] == "kf" else "keyframes + sweeps"]
    parts.append("masked" if meta["mask_moving"] else "unmasked")
    parts.append("depth prior" if meta["depth_prior"] else "no depth prior")
    return ", ".join(parts)


class Gs3dCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)

    def ply_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.ply"

    def meta_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def has_scene(self, scene_token: str) -> bool:
        return any(self.cache_dir.glob(f"{scene_token[:12]}_*.json"))

    def variants(self, scene_token: str) -> list[dict]:
        """Every trained splat of the scene, each with its stats, poses and
        state 'ready'. Sorted so keyframes-only, masked, with depth prior
        comes first when it exists."""
        out = []
        for path in sorted(self.cache_dir.glob(f"{scene_token[:12]}_*.json")):
            meta = json.loads(path.read_text())
            if not self.ply_path(path.stem).exists():
                continue
            out.append({**meta, "key": path.stem, "label": gs3d_label(meta), "state": "ready"})
        out.sort(key=lambda m: (m["images"] != "kf", not m["mask_moving"], not m["depth_prior"]))
        return out
