"""Volumetric fusion of a whole scene into one mesh.

Every keyframe's six camera views are cast into a truncated signed distance
volume (Open3D ScalableTSDFVolume) using the ego poses, then marching cubes
extracts the zero-crossing surface. Two depth sources:

- `camera`: Depth Anything output, made metric with the per-image scale and
  shift fitted to lidar (see backend/app/depth.py). Dense, but only as right
  as the fit.
- `lidar`: the lidar sweep projected into each camera and filled in with
  nearest-neighbour interpolation up to a small pixel radius. Sparse but
  measured.

Objects that move during the scene are masked out of the depth images before
integration, since a moving car smeared over 40 keyframes is not a surface.

The mesh is written as binary PLY with vertex colors; the returned dict is
the JSON sidecar with stats and the per-keyframe ego poses in the scene
frame, which the viewer reads through backend/app/fusion.py.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import numpy as np
import open3d as o3d
from PIL import Image
from scipy.spatial import cKDTree

from app.depth import MIN_DEPTH, DepthCache
from app.nuscenes import CAMERA_CHANNELS, Frame, NuScenes, apply, pose_to_mat

MOVING_THRESHOLD_M = 1.0
DEPTH_TRUNC = {"camera": 40.0, "lidar": 60.0}
LIDAR_FILL_RADIUS_PX = 10.0
MAX_TRIANGLES = 700_000

Progress = Callable[[float, str], None]


def fuse(nusc: NuScenes, depth: DepthCache, scene_token: str, source: str, voxel: float, mask_moving: bool,
         out_ply: Path, progress: Progress) -> dict:
    t0 = time.perf_counter()
    samples = nusc.samples_of_scene[scene_token]
    first = nusc.frame(samples[0]["token"])
    global_to_scene = np.linalg.inv(first.ref_to_global)
    moving = moving_instances(nusc, scene_token) if mask_moving else set()

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
        boxes = moving_boxes(nusc, frame, moving) if moving else []

        for channel in CAMERA_CHANNELS:
            if channel not in frame.camera_sds:
                continue
            sd = frame.camera_sds[channel]
            cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
            K = np.array(cs["camera_intrinsic"])
            cam_to_ref = nusc.sensor_to_ref(frame, sd)
            W, H = sd["width"], sd["height"]

            if source == "camera":
                depth_img = depth.camera_depth(nusc, frame, channel, lidar).metric_depth()
            else:
                depth_img = lidar_depth_image(lidar, K, cam_to_ref, W, H)
            h, w = depth_img.shape
            s = w / W
            Ks = K * s
            Ks[2, 2] = 1.0

            if boxes:
                depth_img = mask_boxes(depth_img, Ks, cam_to_ref, boxes)

            color = np.asarray(
                Image.open(nusc.dataroot / sd["filename"]).convert("RGB").resize((w, h), Image.BILINEAR)
            )
            rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                o3d.geometry.Image(np.ascontiguousarray(color)),
                o3d.geometry.Image(np.ascontiguousarray(depth_img.astype(np.float32))),
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
    mesh = clean(mesh)
    progress(0.95, "writing mesh")
    mesh.compute_vertex_normals()
    o3d.io.write_triangle_mesh(str(out_ply), mesh, write_ascii=False, compressed=False)

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


# ----- pieces ---------------------------------------------------------------


def moving_instances(nusc: NuScenes, scene_token: str) -> set[str]:
    """Instances whose annotated position changes by more than a metre over
    the scene. Parked cars stay; driving cars and walking people go."""
    first: dict[str, np.ndarray] = {}
    span: dict[str, float] = {}
    for sample in nusc.samples_of_scene[scene_token]:
        for ann in nusc.annotations_of_sample.get(sample["token"], []):
            p = np.array(ann["translation"])
            tok = ann["instance_token"]
            if tok not in first:
                first[tok] = p
                span[tok] = 0.0
            else:
                span[tok] = max(span[tok], float(np.linalg.norm(p - first[tok])))
    return {tok for tok, d in span.items() if d > MOVING_THRESHOLD_M}


def moving_boxes(nusc: NuScenes, frame: Frame, moving: set[str]) -> list[tuple[np.ndarray, np.ndarray]]:
    """(ref_to_box 4x4, half sizes) for each moving object in this keyframe."""
    global_to_ref = np.linalg.inv(frame.ref_to_global)
    out = []
    for ann in nusc.annotations_of_sample.get(frame.sample["token"], []):
        if ann["instance_token"] not in moving:
            continue
        box_to_ref = global_to_ref @ pose_to_mat(ann)
        w, l, h = ann["size"]
        half = np.array([l / 2, w / 2, h / 2]) + 0.3  # nuScenes size is (width, length, height)
        out.append((np.linalg.inv(box_to_ref), half))
    return out


def mask_boxes(depth: np.ndarray, Ks: np.ndarray, cam_to_ref: np.ndarray, boxes) -> np.ndarray:
    vs, us = np.nonzero(depth > 0)
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


def lidar_depth_image(lidar: np.ndarray, K: np.ndarray, cam_to_ref: np.ndarray, W: int, H: int,
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


def clean(mesh: o3d.geometry.TriangleMesh) -> o3d.geometry.TriangleMesh:
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
