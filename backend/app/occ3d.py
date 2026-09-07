"""Occ3D-nuScenes semantic occupancy labels.

Occ3D (Tian et al., 2023) adds a dense occupancy label to every nuScenes
keyframe: a 200 x 200 x 16 grid of 0.4 m voxels in the ego frame, covering
-40..40 m in x and y and -1..5.4 m in z, each voxel one of 17 semantic
classes or `free`, with two visibility masks. The labels come from the
CVPR 2023 occupancy challenge release as `gts/<scene name>/<sample
token>/labels.npz`; this module reads that layout under `data/occ3d`.

The grid is indexed [x, y, z]. Voxel (i, j, k) is centred at
ORIGIN + VOXEL * (i + 0.5, j + 0.5, k + 0.5). Against the lidar sweep the
x and y axes match the viewer's ego frame; the labelled road surface sits
about 0.6 m lower than the lidar's road returns, and the grid is shown as
published, so the stats report that offset per keyframe.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

GRID = (200, 200, 16)
VOXEL = 0.4
ORIGIN = (-40.0, -40.0, -1.0)
FREE = 17

# Class ids 0-16 follow nuScenes-lidarseg's evaluation classes; 17 is free.
CLASSES = [
    {"id": 0, "name": "others", "color": "#9AA5B4"},
    {"id": 1, "name": "barrier", "color": "#E8D25A"},
    {"id": 2, "name": "bicycle", "color": "#C8A6FF"},
    {"id": 3, "name": "bus", "color": "#6FA8FF"},
    {"id": 4, "name": "car", "color": "#5FD3C4"},
    {"id": 5, "name": "construction vehicle", "color": "#F0A05A"},
    {"id": 6, "name": "motorcycle", "color": "#B37DFF"},
    {"id": 7, "name": "pedestrian", "color": "#FF7A6B"},
    {"id": 8, "name": "traffic cone", "color": "#FFE08A"},
    {"id": 9, "name": "trailer", "color": "#8FBCE6"},
    {"id": 10, "name": "truck", "color": "#43B8E8"},
    {"id": 11, "name": "drivable surface", "color": "#3F4D61"},
    {"id": 12, "name": "other flat", "color": "#5C6C82"},
    {"id": 13, "name": "sidewalk", "color": "#8494A8"},
    {"id": 14, "name": "terrain", "color": "#8FA86B"},
    {"id": 15, "name": "manmade", "color": "#C2B8A3"},
    {"id": 16, "name": "vegetation", "color": "#5FB86A"},
    {"id": 17, "name": "free", "color": "#000000"},
]
GROUND_CLASSES = (11, 12, 13, 14)

# Packed voxel byte: bits 0-4 the class id, bit 5 seen by the lidar, bit 6
# seen by a camera. Free voxels keep their masks, so the unobserved region
# can be drawn too.
LIDAR_BIT = 1 << 5
CAMERA_BIT = 1 << 6


class Occ3dLabels:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, scene_name: str, sample_token: str) -> Path:
        return self.root / "gts" / scene_name / sample_token / "labels.npz"

    def has_scene(self, scene_name: str, sample_tokens: list[str]) -> bool:
        return any(self.path(scene_name, t).exists() for t in sample_tokens)

    def load(self, scene_name: str, sample_token: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(semantics, mask_lidar, mask_camera), each uint8 of shape GRID."""
        return _load(self.path(scene_name, sample_token))

    def packed(self, scene_name: str, sample_token: str) -> bytes:
        sem, ml, mc = self.load(scene_name, sample_token)
        return (sem | (ml << 5) | (mc << 6)).astype(np.uint8).tobytes()

    def scene_status(self, scene_name: str, sample_tokens: list[str]) -> dict:
        """Which keyframes have a label file, with the count of occupied
        voxels in each, for the timeline."""
        keyframes = []
        for tok in sample_tokens:
            p = self.path(scene_name, tok)
            n = int((_load(p)[0] != FREE).sum()) if p.exists() else 0
            keyframes.append({"token": tok, "ready": p.exists(), "n_occupied": n})
        return {
            "scene_name": scene_name,
            "keyframes": keyframes,
            "n_ready": sum(k["ready"] for k in keyframes),
            "n_total": len(keyframes),
            "grid": {"shape": list(GRID), "voxel": VOXEL, "origin": list(ORIGIN)},
            "classes": CLASSES,
        }

    def stats(self, scene_name: str, sample_token: str, lidar: np.ndarray) -> dict:
        """Per-class voxel counts, visibility totals, and how the keyframe's
        lidar sweep (N x 3, ego frame) lands in the grid."""
        sem, ml, mc = self.load(scene_name, sample_token)
        occupied = sem != FREE
        counts = np.bincount(sem.ravel(), minlength=18)
        counts_cam = np.bincount(sem[mc == 1].ravel(), minlength=18)
        counts_lidar = np.bincount(sem[ml == 1].ravel(), minlength=18)

        idx = np.floor((lidar[:, :3] - ORIGIN) / VOXEL).astype(int)
        inside = (idx >= 0).all(1) & (idx < GRID).all(1)
        idx = idx[inside]
        labels = sem[idx[:, 0], idx[:, 1], idx[:, 2]]
        seen = ml[idx[:, 0], idx[:, 1], idx[:, 2]]

        return {
            "token": sample_token,
            "n_occupied": int(occupied.sum()),
            "n_free": int((~occupied).sum()),
            "n_lidar_visible": int(ml.sum()),
            "n_camera_visible": int(mc.sum()),
            "n_occupied_lidar_visible": int((occupied & (ml == 1)).sum()),
            "n_occupied_camera_visible": int((occupied & (mc == 1)).sum()),
            "class_counts": counts.tolist(),
            "class_counts_camera": counts_cam.tolist(),
            "class_counts_lidar": counts_lidar.tolist(),
            "lidar": {
                "n": int(len(lidar)),
                "n_in_grid": int(inside.sum()),
                "hit_occupied": float((labels != FREE).mean()) if len(labels) else 0.0,
                "hit_observed": float(seen.mean()) if len(seen) else 0.0,
                "ground_offset_m": _ground_offset(sem, lidar[inside]),
            },
        }


@lru_cache(maxsize=256)
def _load(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    d = np.load(path)
    return d["semantics"], d["mask_lidar"], d["mask_camera"]


def _ground_offset(sem: np.ndarray, lidar: np.ndarray) -> float | None:
    """Median over columns of (centre of the lowest drivable voxel) minus
    (mean lidar height of the low returns in that column)."""
    xs, ys, zs = np.nonzero(sem == 11)
    if not len(xs):
        return None
    col = xs * GRID[1] + ys
    lowest = np.full(GRID[0] * GRID[1], 99, dtype=int)
    np.minimum.at(lowest, col, zs)

    low = lidar[lidar[:, 2] < 1.0]
    ij = np.floor((low[:, :2] - ORIGIN[:2]) / VOXEL).astype(int)
    pcol = ij[:, 0] * GRID[1] + ij[:, 1]
    zsum = np.zeros(GRID[0] * GRID[1])
    n = np.zeros(GRID[0] * GRID[1])
    np.add.at(zsum, pcol, low[:, 2])
    np.add.at(n, pcol, 1)

    both = (lowest < 99) & (n >= 3)
    if both.sum() < 20:
        return None
    label_z = ORIGIN[2] + VOXEL * (lowest[both] + 0.5)
    return float(np.median(label_z - zsum[both] / n[both]))
