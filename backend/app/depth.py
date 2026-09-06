"""Depth Anything V2 predictions from the cache, compared with the lidar.

The model predicts relative inverse depth (disparity up to an unknown scale
and shift). To put it in the same space as the lidar we project the lidar
sweep into each image, fit `1/z_lidar ~ scale * pred + shift` by least
squares, and report the error that remains. That residual is the thing a
fine-tuned or radar-corrected model would have to shrink.

Predictions are float16 arrays at half the model input resolution, keyed by
sample_data token, written by compute/depth.py. Nothing here runs the model.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .nuscenes import CAMERA_CHANNELS, Frame, NuScenes

MODEL_INFO = {
    "model": "Depth Anything V2 ViT-B",
    "output": "relative inverse depth, aligned to lidar per image with a scale and shift",
}

MIN_DEPTH = 1.0
MAX_DEPTH = 80.0


class NotComputed(Exception):
    """The cache has no result for this scene or image."""


@dataclass
class CameraDepth:
    channel: str
    sd_token: str
    pred: np.ndarray  # (h, w) float32 relative inverse depth
    scale: float
    shift: float
    n_lidar: int
    abs_rel: float
    rmse: float
    delta1: float
    # lidar samples used for the fit, in image pixels
    u: np.ndarray
    v: np.ndarray
    z_lidar: np.ndarray
    z_pred: np.ndarray

    def metric_depth(self) -> np.ndarray:
        """Predicted depth in metres after the per-image fit. Zero where invalid."""
        disp = self.scale * self.pred + self.shift
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(disp > 1.0 / MAX_DEPTH, 1.0 / disp, 0.0)
        return z.astype(np.float32)


class DepthCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)

    # ----- files --------------------------------------------------------

    def pred_path(self, sd_token: str) -> Path:
        return self.cache_dir / f"{sd_token}.npy"

    def summary_path(self, scene_token: str) -> Path:
        return self.cache_dir / f"scene_{scene_token}.json"

    def has_scene(self, scene_token: str) -> bool:
        return self.summary_path(scene_token).exists()

    def pred(self, sd_token: str) -> np.ndarray:
        """Relative inverse depth at half the model input resolution."""
        path = self.pred_path(sd_token)
        if not path.exists():
            raise NotComputed(f"no depth prediction for image {sd_token}")
        return np.load(path).astype(np.float32)

    def scene_summary(self, scene_token: str) -> dict:
        path = self.summary_path(scene_token)
        if not path.exists():
            raise NotComputed(f"no depth summary for scene {scene_token}")
        return json.loads(path.read_text())

    # ----- comparison with lidar --------------------------------------

    def camera_depth(self, nusc: NuScenes, frame: Frame, channel: str, lidar_ref: np.ndarray) -> CameraDepth:
        sd = frame.camera_sds[channel]
        cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
        pred = self.pred(sd["token"])
        K = np.array(cs["camera_intrinsic"])
        ref_to_cam = np.linalg.inv(nusc.sensor_to_ref(frame, sd))
        W, H = sd["width"], sd["height"]

        pts = lidar_ref[:, :3] @ ref_to_cam[:3, :3].T + ref_to_cam[:3, 3]
        z = pts[:, 2]
        keep = (z > MIN_DEPTH) & (z < MAX_DEPTH)
        pts, z = pts[keep], z[keep]
        u = K[0, 0] * pts[:, 0] / z + K[0, 2]
        v = K[1, 1] * pts[:, 1] / z + K[1, 2]
        inside = (u >= 0) & (u < W) & (v >= 0) & (v < H)
        u, v, z = u[inside], v[inside], z[inside]

        ph, pw = pred.shape
        pu = np.clip((u * pw / W).astype(int), 0, pw - 1)
        pv = np.clip((v * ph / H).astype(int), 0, ph - 1)
        d_pred = pred[pv, pu]
        d_gt = 1.0 / z

        scale, shift = fit_scale_shift(d_pred, d_gt)
        with np.errstate(divide="ignore"):
            z_pred = 1.0 / np.maximum(scale * d_pred + shift, 1e-6)
        z_pred = np.clip(z_pred, 0, MAX_DEPTH * 2)
        ratio = np.maximum(z_pred / z, z / z_pred)
        return CameraDepth(
            channel=channel,
            sd_token=sd["token"],
            pred=pred,
            scale=float(scale),
            shift=float(shift),
            n_lidar=int(len(z)),
            abs_rel=float(np.mean(np.abs(z_pred - z) / z)) if len(z) else float("nan"),
            rmse=float(np.sqrt(np.mean((z_pred - z) ** 2))) if len(z) else float("nan"),
            delta1=float(np.mean(ratio < 1.25)) if len(z) else float("nan"),
            u=u.astype(np.float32),
            v=v.astype(np.float32),
            z_lidar=z.astype(np.float32),
            z_pred=z_pred.astype(np.float32),
        )

    def frame_depth(self, nusc: NuScenes, frame: Frame) -> list[CameraDepth]:
        lidar = nusc.read_lidar(frame)
        return [self.camera_depth(nusc, frame, ch, lidar) for ch in CAMERA_CHANNELS if ch in frame.camera_sds]

    def depth_cloud(self, nusc: NuScenes, frame: Frame, cams: list[CameraDepth], stride: int = 3) -> np.ndarray:
        """Unproject each camera's fitted depth into the reference frame.
        Returns (N, 7) float32: x y z r g b camera_index."""
        parts = []
        for idx, cd in enumerate(cams):
            sd = frame.camera_sds[cd.channel]
            cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
            K = np.array(cs["camera_intrinsic"])
            cam_to_ref = nusc.sensor_to_ref(frame, sd)
            depth = cd.metric_depth()[::stride, ::stride]
            ph, pw = cd.pred.shape
            H, W = sd["height"], sd["width"]
            img = Image.open(nusc.dataroot / sd["filename"]).convert("RGB").resize((pw, ph), Image.BILINEAR)
            rgb = np.asarray(img, dtype=np.float32)[::stride, ::stride] / 255.0

            vs, us = np.mgrid[0:ph:stride, 0:pw:stride]
            u = (us + 0.5) * W / pw
            v = (vs + 0.5) * H / ph
            valid = (depth > MIN_DEPTH) & (depth < MAX_DEPTH)
            z = depth[valid]
            x = (u[valid] - K[0, 2]) * z / K[0, 0]
            y = (v[valid] - K[1, 2]) * z / K[1, 1]
            cam_pts = np.stack([x, y, z], axis=1)
            ref = cam_pts @ cam_to_ref[:3, :3].T + cam_to_ref[:3, 3]
            out = np.empty((len(ref), 7), dtype=np.float32)
            out[:, :3] = ref
            out[:, 3:6] = rgb[valid]
            out[:, 6] = idx
            parts.append(out)
        return np.concatenate(parts) if parts else np.empty((0, 7), dtype=np.float32)

    def summarize_scene(self, nusc: NuScenes, scene_token: str) -> dict:
        """Per-keyframe error for a whole scene, from cached predictions. The
        compute CLI writes the result next to them as the scene summary."""
        frames = []
        for sample in nusc.samples_of_scene[scene_token]:
            cams = self.frame_depth(nusc, nusc.frame(sample["token"]))
            z = np.concatenate([c.z_lidar for c in cams])
            zp = np.concatenate([c.z_pred for c in cams])
            ratio = np.maximum(zp / z, z / zp)
            frames.append({
                "token": sample["token"],
                "abs_rel": float(np.mean(np.abs(zp - z) / z)),
                "rmse": float(np.sqrt(np.mean((zp - z) ** 2))),
                "delta1": float(np.mean(ratio < 1.25)),
                "n_lidar": int(len(z)),
                "cameras": {c.channel: c.abs_rel for c in cams},
            })
        return {
            "scene_token": scene_token,
            "frames": frames,
            "abs_rel": float(np.mean([f["abs_rel"] for f in frames])),
            "rmse": float(np.mean([f["rmse"] for f in frames])),
            "delta1": float(np.mean([f["delta1"] for f in frames])),
        }

    def colorized_png(self, pred: np.ndarray, width: int | None) -> bytes:
        """Relative inverse depth as an image: warm near, cool far."""
        lo, hi = np.percentile(pred, [1, 99])
        t = np.clip((pred - lo) / max(hi - lo, 1e-6), 0, 1)
        rgb = depth_palette(1.0 - t)  # palette is indexed by normalized depth, so invert disparity
        img = Image.fromarray(rgb, "RGB")
        if width:
            img = img.resize((width, round(img.height * width / img.width)), Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, "PNG", compress_level=3)
        return buf.getvalue()


def fit_scale_shift(d_pred: np.ndarray, d_gt: np.ndarray) -> tuple[float, float]:
    """Least squares d_gt ~ scale * d_pred + shift, with one pass of outlier
    rejection at three sigma."""
    if len(d_pred) < 10:
        return 1.0, 0.0
    A = np.stack([d_pred, np.ones_like(d_pred)], axis=1)
    sol, *_ = np.linalg.lstsq(A, d_gt, rcond=None)
    resid = d_gt - A @ sol
    keep = np.abs(resid) < 3 * resid.std() + 1e-9
    if keep.sum() >= 10:
        sol, *_ = np.linalg.lstsq(A[keep], d_gt[keep], rcond=None)
    return float(sol[0]), float(sol[1])


_PALETTE = np.array([
    [255, 190, 90],
    [255, 110, 120],
    [170, 100, 220],
    [80, 140, 255],
    [120, 220, 255],
], dtype=np.float32)


def depth_palette(t: np.ndarray) -> np.ndarray:
    """t in [0,1], 0 = near. Same stops as the frontend depth overlay."""
    s = t * (len(_PALETTE) - 1)
    i = np.clip(np.floor(s).astype(int), 0, len(_PALETTE) - 2)
    f = (s - i)[..., None]
    rgb = _PALETTE[i] * (1 - f) + _PALETTE[i + 1] * f
    return rgb.astype(np.uint8)
