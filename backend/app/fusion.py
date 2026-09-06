"""Volumetric fusion of a whole scene into one mesh.

Every keyframe's six camera views are cast into a truncated signed distance
volume (Open3D ScalableTSDFVolume) using the ego poses, then marching cubes
extracts the zero-crossing surface. Two depth sources:

- `camera`: Depth Anything output, made metric with the per-image scale and
  shift fitted to lidar (see depth.py). Dense, but only as right as the fit.
- `lidar`: the lidar sweep projected into each camera and filled in with
  nearest-neighbour interpolation up to a small pixel radius. Sparse but
  measured.

Objects that move during the scene are masked out of the depth images before
integration, since a moving car smeared over 40 keyframes is not a surface.

Meshes are built in a background thread and cached under the fusion cache
directory as binary PLY with vertex colors, plus a JSON sidecar with stats
and the per-keyframe ego poses in the scene frame.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import open3d as o3d
from PIL import Image
from scipy.spatial import cKDTree

from .depth import DepthEstimator, MIN_DEPTH
from .nuscenes import CAMERA_CHANNELS, Frame, NuScenes, apply, pose_to_mat

SOURCES = ("camera", "lidar")
VOXELS = (0.15, 0.2, 0.3)
MOVING_THRESHOLD_M = 1.0
DEPTH_TRUNC = {"camera": 40.0, "lidar": 60.0}
LIDAR_FILL_RADIUS_PX = 10.0
MAX_TRIANGLES = 700_000


class FusionBuilder:
    def __init__(self, nusc: NuScenes, depth_model: DepthEstimator, cache_dir: Path):
        self.nusc = nusc
        self.depth_model = depth_model
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ----- public -----------------------------------------------------

    @staticmethod
    def key(scene_token: str, source: str, voxel: float, mask_moving: bool) -> str:
        return f"{scene_token[:12]}_{source}_v{voxel:g}_m{int(mask_moving)}"

    def status(self, scene_token: str, source: str, voxel: float, mask_moving: bool) -> dict:
        key = self.key(scene_token, source, voxel, mask_moving)
        meta = self.cache_dir / f"{key}.json"
        if meta.exists():
            return {"key": key, "state": "ready", **json.loads(meta.read_text())}
        with self._lock:
            job = self._jobs.get(key)
            if job is None:
                job = {"state": "running", "progress": 0.0, "message": "queued", "started": time.time()}
                self._jobs[key] = job
                threading.Thread(
                    target=self._run, args=(key, scene_token, source, voxel, mask_moving), daemon=True
                ).start()
        return {"key": key, **{k: v for k, v in job.items() if k != "started"}}

    def mesh_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.ply"

    # ----- build ------------------------------------------------------

    def _run(self, key: str, scene_token: str, source: str, voxel: float, mask_moving: bool) -> None:
        job = self._jobs[key]

        def progress(p: float, msg: str) -> None:
            job["progress"] = round(p, 3)
            job["message"] = msg

        try:
            meta = self.fuse(scene_token, source, voxel, mask_moving, key, progress)
            (self.cache_dir / f"{key}.json").write_text(json.dumps(meta))
        except Exception as e:  # surfaced to the UI, not swallowed
            job["state"] = "error"
            job["message"] = f"{type(e).__name__}: {e}"
            return
        with self._lock:
            self._jobs.pop(key, None)

    def fuse(self, scene_token: str, source: str, voxel: float, mask_moving: bool, key: str, progress) -> dict:
        t0 = time.perf_counter()
        nusc = self.nusc
        samples = nusc.samples_of_scene[scene_token]
        first = nusc.frame(samples[0]["token"])
        global_to_scene = np.linalg.inv(first.ref_to_global)
        moving = self._moving_instances(scene_token) if mask_moving else set()

        volume = o3d.pipelines.integration.ScalableTSDFVolume(
            voxel_length=voxel,
            sdf_trunc=4 * voxel,
            color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8,
        )

        poses = []
        views = 0
        for i, sample in enumerate(samples):
            progress(0.8 * i / len(samples), f"integrating keyframe {i + 1} of {len(samples)}")
            frame = nusc.frame(sample["token"])
            ref_to_scene = global_to_scene @ frame.ref_to_global
            poses.append({"token": sample["token"], "ego_to_scene": ref_to_scene.tolist()})
            lidar = nusc.read_lidar(frame)
            boxes = self._moving_boxes(frame, moving) if moving else []

            for channel in CAMERA_CHANNELS:
                if channel not in frame.camera_sds:
                    continue
                sd = frame.camera_sds[channel]
                cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
                K = np.array(cs["camera_intrinsic"])
                cam_to_ref = nusc.sensor_to_ref(frame, sd)
                W, H = sd["width"], sd["height"]

                if source == "camera":
                    cd = self.depth_model.camera_depth(nusc, frame, channel, lidar)
                    depth = cd.metric_depth()
                else:
                    depth = self._lidar_depth_image(lidar, K, cam_to_ref, W, H)
                h, w = depth.shape
                s = w / W
                Ks = K * s
                Ks[2, 2] = 1.0

                if boxes:
                    depth = self._mask_boxes(depth, Ks, cam_to_ref, boxes)

                color = np.asarray(
                    Image.open(nusc.dataroot / sd["filename"]).convert("RGB").resize((w, h), Image.BILINEAR)
                )
                rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                    o3d.geometry.Image(np.ascontiguousarray(color)),
                    o3d.geometry.Image(np.ascontiguousarray(depth.astype(np.float32))),
                    depth_scale=1.0,
                    depth_trunc=DEPTH_TRUNC[source],
                    convert_rgb_to_intensity=False,
                )
                intrinsic = o3d.camera.PinholeCameraIntrinsic(w, h, Ks[0, 0], Ks[1, 1], Ks[0, 2], Ks[1, 2])
                cam_to_scene = ref_to_scene @ cam_to_ref
                volume.integrate(rgbd, intrinsic, np.linalg.inv(cam_to_scene))
                views += 1

        progress(0.85, "extracting surface")
        mesh = volume.extract_triangle_mesh()
        raw_triangles = len(mesh.triangles)
        mesh = self._clean(mesh)
        progress(0.95, "writing mesh")
        mesh.compute_vertex_normals()
        o3d.io.write_triangle_mesh(str(self.mesh_path(key)), mesh, write_ascii=False, compressed=False)

        bbox = mesh.get_axis_aligned_bounding_box()
        return {
            "scene_token": scene_token,
            "source": source,
            "voxel": voxel,
            "mask_moving": mask_moving,
            "moving_instances": len(moving),
            "keyframes": len(samples),
            "views": views,
            "vertices": len(mesh.vertices),
            "triangles": len(mesh.triangles),
            "raw_triangles": raw_triangles,
            "seconds": round(time.perf_counter() - t0, 1),
            "bounds_min": bbox.min_bound.tolist(),
            "bounds_max": bbox.max_bound.tolist(),
            "poses": poses,
        }

    # ----- pieces -----------------------------------------------------

    def _moving_instances(self, scene_token: str) -> set[str]:
        """Instances whose annotated position changes by more than a metre
        over the scene. Parked cars stay; driving cars and walking people go."""
        first: dict[str, np.ndarray] = {}
        span: dict[str, float] = {}
        for sample in self.nusc.samples_of_scene[scene_token]:
            for ann in self.nusc.annotations_of_sample.get(sample["token"], []):
                p = np.array(ann["translation"])
                tok = ann["instance_token"]
                if tok not in first:
                    first[tok] = p
                    span[tok] = 0.0
                else:
                    span[tok] = max(span[tok], float(np.linalg.norm(p - first[tok])))
        return {tok for tok, d in span.items() if d > MOVING_THRESHOLD_M}

    def _moving_boxes(self, frame: Frame, moving: set[str]) -> list[tuple[np.ndarray, np.ndarray]]:
        """(ref_to_box 4x4, half sizes) for each moving object in this keyframe."""
        global_to_ref = np.linalg.inv(frame.ref_to_global)
        out = []
        for ann in self.nusc.annotations_of_sample.get(frame.sample["token"], []):
            if ann["instance_token"] not in moving:
                continue
            box_to_ref = global_to_ref @ pose_to_mat(ann)
            w, l, h = ann["size"]
            half = np.array([l / 2, w / 2, h / 2]) + 0.3  # nuScenes size is (width, length, height)
            out.append((np.linalg.inv(box_to_ref), half))
        return out

    def _mask_boxes(self, depth: np.ndarray, Ks: np.ndarray, cam_to_ref: np.ndarray, boxes) -> np.ndarray:
        h, w = depth.shape
        valid = depth > 0
        vs, us = np.nonzero(valid)
        z = depth[vs, us]
        x = (us + 0.5 - Ks[0, 2]) * z / Ks[0, 0]
        y = (vs + 0.5 - Ks[1, 2]) * z / Ks[1, 1]
        ref = apply(cam_to_ref, np.stack([x, y, z], axis=1))
        hit = np.zeros(len(ref), dtype=bool)
        for ref_to_box, half in boxes:
            local = apply(ref_to_box, ref)
            hit |= np.all(np.abs(local) <= half, axis=1)
        out = depth.copy()
        out[vs[hit], us[hit]] = 0.0
        return out

    def _lidar_depth_image(self, lidar: np.ndarray, K: np.ndarray, cam_to_ref: np.ndarray, W: int, H: int,
                           scale: float = 462 / 1600) -> np.ndarray:
        """Lidar projected into the camera and filled in by nearest neighbour
        within LIDAR_FILL_RADIUS_PX, at the same resolution as the depth maps."""
        w, h = round(W * scale), round(H * scale)
        ref_to_cam = np.linalg.inv(cam_to_ref)
        pts = apply(ref_to_cam, lidar[:, :3])
        z = pts[:, 2]
        keep = (z > MIN_DEPTH) & (z < DEPTH_TRUNC["lidar"])
        pts, z = pts[keep], z[keep]
        u = (K[0, 0] * pts[:, 0] / z + K[0, 2]) * scale
        v = (K[1, 1] * pts[:, 1] / z + K[1, 2]) * scale
        inside = (u >= 0) & (u < w) & (v >= 0) & (v < h)
        u, v, z = u[inside], v[inside], z[inside]
        depth = np.zeros((h, w), dtype=np.float32)
        if len(z) < 10:
            return depth
        tree = cKDTree(np.stack([u, v], axis=1))
        gv, gu = np.mgrid[0:h, 0:w]
        dist, idx = tree.query(np.stack([gu.ravel() + 0.5, gv.ravel() + 0.5], axis=1),
                               distance_upper_bound=LIDAR_FILL_RADIUS_PX)
        ok = np.isfinite(dist)
        depth.ravel()[ok] = z[idx[ok]]
        return depth

    @staticmethod
    def _clean(mesh: o3d.geometry.TriangleMesh) -> o3d.geometry.TriangleMesh:
        """Drop tiny floating fragments and decimate to a browser-friendly size."""
        mesh.remove_degenerate_triangles()
        mesh.remove_unreferenced_vertices()
        if len(mesh.triangles) == 0:
            return mesh
        clusters, sizes, _ = mesh.cluster_connected_triangles()
        clusters = np.asarray(clusters)
        sizes = np.asarray(sizes)
        small = sizes[clusters] < 60
        mesh.remove_triangles_by_mask(small)
        mesh.remove_unreferenced_vertices()
        if len(mesh.triangles) > MAX_TRIANGLES:
            mesh = mesh.simplify_quadric_decimation(MAX_TRIANGLES)
        return mesh

