"""Export a nuScenes scene in the COLMAP layout the official 3D Gaussian
Splatting trainer reads. Runs in the viewer's environment: numpy and Pillow
only, no model.

    uv run --project backend python compute/gs3d/export.py --scene scene-0061 [--sweeps] [--no-mask]

Writes data/gs3d/<scene>_<kf|sweeps>_m<0|1>/:
  images/                    the camera images. PNG with an alpha channel where a
                             moving object or the ego car's own body is masked
                             out, otherwise the JPEG as is. The trainer takes
                             alpha as a loss mask.
  sparse/0/cameras.txt       one PINHOLE camera per channel
  sparse/0/images.txt        world-to-camera pose of every image, world being the
                             scene frame: the ego frame of the first keyframe
  sparse/0/points3D.ply      the lidar sweeps of every keyframe, static returns
                             only, coloured from the cameras: the initial Gaussians
  depths/<name>.png          Depth Anything V2 inverse depth, 16-bit, and
  sparse/0/depth_params.json its scale and shift to lidar per image, for the
                             trainer's depth regularisation. Written only when the
                             depth cache has a prediction for every image.
  scene.json                 what was exported, plus the per-keyframe ego poses in
                             the scene frame; train.py copies it into the result.

Poses and intrinsics come from the dataset, so there is no COLMAP run. The
nuScenes camera frame is already x right, y down, z forward, and the images
are undistorted, which is what PINHOLE means.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.depth import DepthCache, fit_scale_shift  # noqa: E402
from app.nuscenes import CAMERA_CHANNELS, NuScenes, apply, pose_to_mat  # noqa: E402

DATA = ROOT / "data"
DATAROOT = Path(os.environ.get("NUSCENES_DATAROOT", DATA / "nuscenes"))
DEPTH_CACHE = Path(os.environ.get("DEPTH_CACHE", DATA / "cache" / "depth"))
EXPORT_DIR = Path(os.environ.get("GS3D_EXPORT", DATA / "gs3d"))

MOVING_THRESHOLD_M = 1.0
BOX_MARGIN_M = 0.4  # around annotated boxes, since they are tight and a sweep's box is interpolated
BOX_SAMPLE_M = 0.25  # spacing of the points that stand in for a box when projecting it
INTERPOLATE_MAX_S = 0.6  # a sweep this far from an instance's nearest annotation gets no box
MIN_DEPTH, MAX_DEPTH = 1.0, 60.0
VOXEL_M = 0.15
# lidar returns from the ego car itself, in the ego frame
EGO_BODY = np.array([[-1.5, -1.5, -1.0], [4.0, 1.5, 2.5]])
# the ego car's own body in the bottom of an image: rows from here down are masked
EGO_BODY_ROWS = {"CAM_BACK": 815}


# ----- small geometry ---------------------------------------------------


def mat_to_quat_wxyz(R: np.ndarray) -> np.ndarray:
    """Rotation matrix to unit quaternion, the branch chosen for stability."""
    m = R
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        q = [0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s]
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s]
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s]
    q = np.array(q)
    return q / np.linalg.norm(q)


def slerp(q0: np.ndarray, q1: np.ndarray, f: float) -> np.ndarray:
    q0, q1 = np.array(q0, float), np.array(q1, float)
    d = float(np.dot(q0, q1))
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + f * (q1 - q0)
    else:
        th = np.arccos(d)
        q = (np.sin((1 - f) * th) * q0 + np.sin(f * th) * q1) / np.sin(th)
    return q / np.linalg.norm(q)


def convex_hull(pts: np.ndarray) -> np.ndarray:
    """Andrew's monotone chain on (N,2) points; returns the hull in order."""
    pts = np.unique(pts, axis=0)
    if len(pts) < 3:
        return pts
    order = np.lexsort((pts[:, 1], pts[:, 0]))
    pts = pts[order]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def project(K: np.ndarray, pts_cam: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    z = pts_cam[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u = K[0, 0] * pts_cam[:, 0] / z + K[0, 2]
        v = K[1, 1] * pts_cam[:, 1] / z + K[1, 2]
    return u, v, z


# ----- moving objects ---------------------------------------------------


class MovingBoxes:
    """The annotated boxes of the instances that move during the scene, at
    any time. Keyframes have annotations; a sweep between two keyframes gets
    each instance's box interpolated between its two annotations."""

    def __init__(self, nusc: NuScenes, scene_token: str):
        moving = nusc.moving_instances(scene_token, MOVING_THRESHOLD_M)
        self.tracks: dict[str, list[dict]] = {}
        for sample in nusc.samples_of_scene[scene_token]:
            for ann in nusc.annotations_of_sample.get(sample["token"], []):
                if ann["instance_token"] in moving:
                    self.tracks.setdefault(ann["instance_token"], []).append({**ann, "t": sample["timestamp"] / 1e6})
        for track in self.tracks.values():
            track.sort(key=lambda a: a["t"])
        self.count = len(self.tracks)

    def at(self, t_s: float) -> list[tuple[np.ndarray, np.ndarray]]:
        """(box_to_global 4x4, half sizes with margin) for each moving object at time t."""
        out = []
        for track in self.tracks.values():
            after = next((i for i, a in enumerate(track) if a["t"] >= t_s), None)
            if after is None:
                a = track[-1]
                if t_s - a["t"] > INTERPOLATE_MAX_S:
                    continue
                rec = a
            elif after == 0 or track[after]["t"] == t_s:
                a = track[after]
                if a["t"] - t_s > INTERPOLATE_MAX_S:
                    continue
                rec = a
            else:
                a, b = track[after - 1], track[after]
                f = (t_s - a["t"]) / (b["t"] - a["t"])
                rec = {
                    "translation": (1 - f) * np.array(a["translation"]) + f * np.array(b["translation"]),
                    "rotation": slerp(a["rotation"], b["rotation"], f),
                    "size": a["size"],
                }
            w, l, h = rec["size"]
            half = np.array([l / 2, w / 2, h / 2]) + BOX_MARGIN_M  # nuScenes size is (width, length, height)
            out.append((pose_to_mat(rec), half))
        return out


def box_points(half: np.ndarray) -> np.ndarray:
    """A grid of points filling the box, in box coordinates. Projecting a
    grid instead of the eight corners keeps a box that crosses the camera
    plane well behaved: the points behind the camera are dropped and the
    hull of the rest is the visible part."""
    axes = [np.linspace(-h, h, max(2, int(np.ceil(2 * h / BOX_SAMPLE_M)) + 1)) for h in half]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


def mask_image(alpha: Image.Image, K: np.ndarray, global_to_cam: np.ndarray, boxes) -> int:
    """Paint the projection of each box black on the alpha image. Returns
    how many boxes touched the image."""
    W, H = alpha.size
    draw = ImageDraw.Draw(alpha)
    hits = 0
    for box_to_global, half in boxes:
        pts = apply(global_to_cam @ box_to_global, box_points(half))
        pts = pts[pts[:, 2] > 0.2]
        if len(pts) < 3:
            continue
        u, v, _ = project(K, pts)
        inside = (u > -W) & (u < 2 * W) & (v > -H) & (v < 2 * H)
        if inside.sum() < 3:
            continue
        hull = convex_hull(np.stack([u[inside], v[inside]], axis=1))
        if len(hull) < 3:
            continue
        if hull[:, 0].max() < 0 or hull[:, 0].min() >= W or hull[:, 1].max() < 0 or hull[:, 1].min() >= H:
            continue
        draw.polygon([tuple(p) for p in hull], fill=0)
        hits += 1
    return hits


def points_in_boxes(pts: np.ndarray, boxes, global_to_pts: np.ndarray) -> np.ndarray:
    """Boolean mask of the points (in the frame global_to_pts maps into) that
    lie inside any box."""
    hit = np.zeros(len(pts), dtype=bool)
    for box_to_global, half in boxes:
        local = apply(np.linalg.inv(global_to_pts @ box_to_global), pts)
        hit |= np.all(np.abs(local) <= half, axis=1)
    return hit


# ----- the export -------------------------------------------------------


def camera_views(nusc: NuScenes, scene: dict, sweeps: bool) -> list[dict]:
    """Every camera image to train on, in time order, with its pose."""
    samples = nusc.samples_of_scene[scene["token"]]
    sample_tokens = {s["token"] for s in samples}
    views = []
    for sample in samples:
        for ch, sd in nusc.keyframe_sd[sample["token"]].items():
            if ch in CAMERA_CHANNELS:
                views.append({"sd": sd, "channel": ch, "keyframe": True})
    if sweeps:
        for sd in nusc.table["sample_data"]:
            if sd["is_key_frame"] or sd["fileformat"] != "jpg" or sd["sample_token"] not in sample_tokens:
                continue
            ch = nusc.channel_of_cs[sd["calibrated_sensor_token"]]
            if ch in CAMERA_CHANNELS:
                views.append({"sd": sd, "channel": ch, "keyframe": False})
    views.sort(key=lambda v: (v["sd"]["timestamp"], v["channel"]))
    t0 = views[0]["sd"]["timestamp"]
    for v in views:
        sd = v["sd"]
        cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
        v["cam_to_global"] = pose_to_mat(nusc.get("ego_pose", sd["ego_pose_token"])) @ pose_to_mat(cs)
        v["K"] = np.array(cs["camera_intrinsic"], dtype=np.float64)
        v["t_s"] = sd["timestamp"] / 1e6
        v["name"] = f"{(sd['timestamp'] - t0) // 1000:06d}_{v['channel']}"
        v["cs_token"] = sd["calibrated_sensor_token"]
    return views


def write_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray) -> None:
    rec = np.zeros(len(xyz), dtype=[("x", "f4"), ("y", "f4"), ("z", "f4"), ("nx", "f4"), ("ny", "f4"), ("nz", "f4"),
                                    ("red", "u1"), ("green", "u1"), ("blue", "u1")])
    rec["x"], rec["y"], rec["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    rec["red"], rec["green"], rec["blue"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(rec)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property float nx\nproperty float ny\nproperty float nz\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(rec.tobytes())


def export_scene(nusc: NuScenes, depth: DepthCache, scene: dict, sweeps: bool, mask_moving: bool, out: Path) -> dict:
    t_start = time.perf_counter()
    name = f"{scene['name']}_{'sweeps' if sweeps else 'kf'}_m{int(mask_moving)}"
    out = out / name
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)
    (out / "sparse" / "0").mkdir(parents=True)
    (out / "depths").mkdir()

    samples = nusc.samples_of_scene[scene["token"]]
    first = nusc.frame(samples[0]["token"])
    global_to_scene = np.linalg.inv(first.ref_to_global)
    boxes = MovingBoxes(nusc, scene["token"]) if mask_moving else None
    views = camera_views(nusc, scene, sweeps)
    missing = [v for v in views if not (nusc.dataroot / v["sd"]["filename"]).exists()]
    if missing:
        raise SystemExit(f"{scene['name']}: {len(missing)} camera files are not on disk, first {missing[0]['sd']['filename']}. "
                         "The dataset bundle carries keyframes only; sweeps need the full nuScenes mini.")
    print(f"{name}: {len(views)} images, {sum(v['keyframe'] for v in views)} of them keyframes"
          + (f", {boxes.count} moving objects" if boxes else ""))

    # ----- cameras.txt: one per calibrated sensor -----
    cameras: dict[str, int] = {}
    with open(out / "sparse" / "0" / "cameras.txt", "w") as f:
        f.write("# CAMERA_ID MODEL WIDTH HEIGHT PARAMS[]\n")
        for v in views:
            if v["cs_token"] in cameras:
                continue
            cameras[v["cs_token"]] = len(cameras) + 1
            K, sd = v["K"], v["sd"]
            f.write(f"{cameras[v['cs_token']]} PINHOLE {sd['width']} {sd['height']} {K[0, 0]:.6f} {K[1, 1]:.6f} {K[0, 2]:.6f} {K[1, 2]:.6f}\n")

    # ----- the initial points: every keyframe's lidar, static, coloured -----
    xyz_all, rgb_all = [], []
    lidar_scene: dict[str, np.ndarray] = {}  # per keyframe, static points in the scene frame, for the depth fit
    for sample in samples:
        frame = nusc.frame(sample["token"])
        pts = nusc.read_lidar(frame)[:, :3]
        body = np.all((pts >= EGO_BODY[0]) & (pts <= EGO_BODY[1]), axis=1)
        pts = pts[~body]
        if boxes:
            pts = pts[~points_in_boxes(pts, boxes.at(sample["timestamp"] / 1e6), np.linalg.inv(frame.ref_to_global))]
        ref_to_scene = global_to_scene @ frame.ref_to_global
        lidar_scene[sample["token"]] = apply(ref_to_scene, pts)

        rgb = np.full((len(pts), 3), -1, dtype=np.int16)
        for ch in CAMERA_CHANNELS:
            sd = frame.camera_sds.get(ch)
            if sd is None:
                continue
            cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
            K = np.array(cs["camera_intrinsic"])
            cam = apply(np.linalg.inv(nusc.sensor_to_ref(frame, sd)), pts)
            u, v, z = project(K, cam)
            bottom = EGO_BODY_ROWS.get(ch, sd["height"])
            ok = (rgb[:, 0] < 0) & (z > MIN_DEPTH) & (z < MAX_DEPTH) & (u >= 0) & (u < sd["width"]) & (v >= 0) & (v < bottom)
            if not ok.any():
                continue
            img = np.asarray(Image.open(nusc.dataroot / sd["filename"]).convert("RGB"))
            rgb[ok] = img[v[ok].astype(int), u[ok].astype(int)]
        seen = rgb[:, 0] >= 0
        xyz_all.append(lidar_scene[sample["token"]][seen])
        rgb_all.append(rgb[seen].astype(np.uint8))
    xyz = np.concatenate(xyz_all)
    rgb = np.concatenate(rgb_all)
    n_raw = len(xyz)
    _, keep = np.unique(np.floor(xyz / VOXEL_M).astype(np.int64), axis=0, return_index=True)
    xyz, rgb = xyz[np.sort(keep)], rgb[np.sort(keep)]
    write_ply(out / "sparse" / "0" / "points3D.ply", xyz, rgb)
    print(f"{name}: {len(xyz):,} initial points from {n_raw:,} coloured lidar returns")

    # ----- images.txt, the images with their masks, the depth priors -----
    keyframe_times = np.array([s["timestamp"] / 1e6 for s in samples])
    depth_params: dict[str, dict] = {}
    depth_missing = 0
    n_masked = 0
    view_meta = []
    with open(out / "sparse" / "0" / "images.txt", "w") as f:
        f.write("# IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID NAME\n#   POINTS2D[] as (X, Y, POINT3D_ID)\n")
        for i, v in enumerate(views, 1):
            sd, K = v["sd"], v["K"]
            cam_to_scene = global_to_scene @ v["cam_to_global"]
            w2c = np.linalg.inv(cam_to_scene)
            q = mat_to_quat_wxyz(w2c[:3, :3])
            t = w2c[:3, 3]

            src = nusc.dataroot / sd["filename"]
            alpha = Image.new("L", (sd["width"], sd["height"]), 255)
            masked = False
            if v["channel"] in EGO_BODY_ROWS:
                ImageDraw.Draw(alpha).rectangle([0, EGO_BODY_ROWS[v["channel"]], sd["width"], sd["height"]], fill=0)
                masked = True
            if boxes and mask_image(alpha, K, np.linalg.inv(v["cam_to_global"]), boxes.at(v["t_s"])):
                masked = True
                n_masked += 1
            if masked:
                img = Image.open(src).convert("RGB")
                img.putalpha(alpha)
                img.save(out / "images" / f"{v['name']}.png", optimize=False)
            else:
                shutil.copyfile(src, out / "images" / f"{v['name']}.jpg")
            ext = "png" if masked else "jpg"
            f.write(f"{i} {q[0]:.9f} {q[1]:.9f} {q[2]:.9f} {q[3]:.9f} {t[0]:.6f} {t[1]:.6f} {t[2]:.6f} {cameras[v['cs_token']]} {v['name']}.{ext}\n\n")

            # depth prior: the cached prediction, normalised to 16 bits, and its
            # fit to the lidar of the nearest keyframe (exact for keyframe views)
            if depth.pred_path(sd["token"]).exists():
                pred = depth.pred(sd["token"])
                top = float(pred.max()) or 1.0
                Image.fromarray(np.clip(pred / top * 65535, 0, 65535).astype(np.uint16)).save(out / "depths" / f"{v['name']}.png")
                nearest = samples[int(np.argmin(np.abs(keyframe_times - v["t_s"])))]
                cam = apply(w2c, lidar_scene[nearest["token"]])
                u, vv, z = project(K, cam)
                ok = (z > MIN_DEPTH) & (z < MAX_DEPTH) & (u >= 0) & (u < sd["width"]) & (vv >= 0) & (vv < sd["height"])
                ph, pw = pred.shape
                pu = np.clip((u[ok] * pw / sd["width"]).astype(int), 0, pw - 1)
                pv = np.clip((vv[ok] * ph / sd["height"]).astype(int), 0, ph - 1)
                scale, shift = fit_scale_shift(pred[pv, pu] / top, 1.0 / z[ok])
                depth_params[v["name"]] = {"scale": scale if scale > 0 else 0.0, "offset": shift if scale > 0 else 0.0}
            else:
                depth_missing += 1
            view_meta.append({"name": v["name"], "sd_token": sd["token"], "sample_token": sd["sample_token"],
                              "channel": v["channel"], "keyframe": v["keyframe"], "masked": masked})
            if i % 60 == 0 or i == len(views):
                print(f"{name}: {i}/{len(views)} images written", flush=True)

    depth_available = depth_missing == 0
    if depth_available:
        (out / "sparse" / "0" / "depth_params.json").write_text(json.dumps(depth_params, indent=1))
    else:
        shutil.rmtree(out / "depths")
        print(f"{name}: no depth prior, {depth_missing} images have no Depth Anything prediction in the cache"
              + (" (sweeps are not in the depth cache)" if sweeps else " (run: make compute TASK=depth)"))

    poses = []
    for sample in samples:
        frame = nusc.frame(sample["token"])
        poses.append({"token": sample["token"], "ego_to_scene": (global_to_scene @ frame.ref_to_global).tolist()})

    meta = {
        "scene_token": scene["token"],
        "scene_name": scene["name"],
        "images": "sweeps" if sweeps else "kf",
        "mask_moving": mask_moving,
        "moving_instances": boxes.count if boxes else 0,
        "n_images": len(views),
        "n_keyframe_images": sum(v["keyframe"] for v in views),
        "n_masked_images": n_masked,
        "n_points": int(len(xyz)),
        "n_points_raw": int(n_raw),
        "depth_prior_available": depth_available,
        "export_seconds": round(time.perf_counter() - t_start, 1),
        "poses": poses,
        "views": view_meta,
    }
    (out / "scene.json").write_text(json.dumps(meta))
    print(f"{name}: exported to {out} in {meta['export_seconds']} s")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", action="append", default=[], help="scene name, e.g. scene-0061; repeatable")
    ap.add_argument("--all-scenes", action="store_true", help="every scene on disk")
    ap.add_argument("--sweeps", action="store_true", help="add the 12 Hz camera sweeps to the 2 Hz keyframes")
    ap.add_argument("--no-mask", action="store_true", help="keep moving objects instead of masking them out")
    ap.add_argument("--out", type=Path, default=EXPORT_DIR, help=f"export root (default {EXPORT_DIR})")
    args = ap.parse_args()

    if not (DATAROOT / "v1.0-mini" / "scene.json").exists():
        raise SystemExit(f"nuScenes v1.0-mini not found at {DATAROOT}. Run 'make data' first.")
    nusc = NuScenes(DATAROOT)
    by_name = {s["name"]: s for s in nusc.table["scene"]}
    if args.all_scenes:
        scenes = list(by_name.values())
    else:
        missing = [n for n in args.scene if n not in by_name]
        if missing or not args.scene:
            raise SystemExit(f"choose --scene from {', '.join(by_name)}, or --all-scenes")
        scenes = [by_name[n] for n in args.scene]
    depth = DepthCache(DEPTH_CACHE)
    for scene in scenes:
        export_scene(nusc, depth, scene, args.sweeps, not args.no_mask, args.out)


if __name__ == "__main__":
    main()
