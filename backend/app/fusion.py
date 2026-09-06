"""Fused scene meshes from the cache.

compute/fusion.py casts every keyframe's camera views into a TSDF volume and
writes one binary PLY per scene and option set, with a JSON sidecar holding
stats and the per-keyframe ego poses in the scene frame. This module only
names and reads those files.
"""

from __future__ import annotations

import json
from pathlib import Path

SOURCES = ("camera", "lidar")
VOXELS = (0.15, 0.2, 0.3)


def fusion_key(scene_token: str, source: str, voxel: float, mask_moving: bool) -> str:
    return f"{scene_token[:12]}_{source}_v{voxel:g}_m{int(mask_moving)}"


class FusionCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)

    def mesh_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.ply"

    def meta_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def has_scene(self, scene_token: str) -> bool:
        return any(self.cache_dir.glob(f"{scene_token[:12]}_*.json"))

    def status(self, scene_token: str, source: str, voxel: float, mask_moving: bool) -> dict:
        key = fusion_key(scene_token, source, voxel, mask_moving)
        meta = self.meta_path(key)
        if meta.exists():
            return {"key": key, "state": "ready", **json.loads(meta.read_text())}
        return {"key": key, "state": "missing"}
