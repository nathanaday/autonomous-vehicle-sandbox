"""Gaussian splats from the cache.

compute/splat_export.py runs Depth Anything 3 and writes, per keyframe and
option set, a 3DGS PLY plus a JSON of stats. This module names and reads
those files; the key function is shared with the exporter.
"""

from __future__ import annotations

import json
from pathlib import Path


def splat_key(sample_token: str, views: int, posed: bool) -> str:
    return f"{sample_token[:12]}_v{views}_{'posed' if posed else 'unposed'}"


class SplatCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)

    def ply_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.ply"

    def meta_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def has_scene(self, sample_tokens: list[str]) -> bool:
        return any(self.meta_path(splat_key(t, 6, True)).exists() for t in sample_tokens)

    def sample_status(self, sample_token: str, views: int, posed: bool) -> dict:
        """The splat's stats when computed, else state 'missing'."""
        key = splat_key(sample_token, views, posed)
        meta = self.meta_path(key)
        if meta.exists():
            return {**json.loads(meta.read_text()), "key": key, "state": "ready"}
        return {"key": key, "state": "missing"}

    def scene_status(self, scene_token: str, sample_tokens: list[str], views: int, posed: bool) -> dict:
        keyframes = []
        for tok in sample_tokens:
            key = splat_key(tok, views, posed)
            keyframes.append({"token": tok, "key": key, "ready": self.meta_path(key).exists()})
        return {
            "scene_token": scene_token,
            "views": views,
            "posed": posed,
            "keyframes": keyframes,
            "n_ready": sum(k["ready"] for k in keyframes),
            "n_total": len(keyframes),
        }
