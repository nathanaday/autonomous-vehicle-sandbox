"""Stock Depth Anything V2 on nuScenes camera frames.

The model predicts relative inverse depth (disparity up to an unknown scale
and shift). To put it in the same space as the lidar we project the lidar
sweep into each image, fit `1/z_lidar ~ scale * pred + shift` by least
squares, and report the error that remains. That residual is the thing a
fine-tuned or radar-corrected model would have to shrink.

Predictions are cached on disk as float16 arrays at half the model input
resolution, keyed by sample_data token.
"""

from __future__ import annotations

import io
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from .depth_anything_v2.dpt import DepthAnythingV2
from .nuscenes import CAMERA_CHANNELS, Frame, NuScenes

MODEL_CONFIGS = {
    "vits": {"encoder": "vits", "features": 64, "out_channels": [48, 96, 192, 384]},
    "vitb": {"encoder": "vitb", "features": 128, "out_channels": [96, 192, 384, 768]},
    "vitl": {"encoder": "vitl", "features": 256, "out_channels": [256, 512, 1024, 1024]},
}

ENCODER_NAMES = {"vits": "ViT-S", "vitb": "ViT-B", "vitl": "ViT-L"}

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

MIN_DEPTH = 1.0
MAX_DEPTH = 80.0


def pick_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def input_size(width: int, height: int, short_side: int = 518) -> tuple[int, int]:
    """Official preprocessing: scale so the short side is 518, round both sides
    to a multiple of the 14 px patch."""
    scale = short_side / min(width, height)
    w = int(round(width * scale / 14)) * 14
    h = int(round(height * scale / 14)) * 14
    return w, h


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


class DepthEstimator:
    def __init__(self, checkpoint: Path, cache_dir: Path, encoder: str = "vitb"):
        self.checkpoint = Path(checkpoint)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.encoder = encoder
        self.device = pick_device()
        self._model: DepthAnythingV2 | None = None
        self._lock = threading.Lock()
        self.last_inference_s: float | None = None

    @property
    def available(self) -> bool:
        return self.checkpoint.exists()

    def info(self) -> dict:
        return {
            "model": f"Depth Anything V2 {ENCODER_NAMES.get(self.encoder, self.encoder)}",
            "checkpoint": self.checkpoint.name,
            "available": self.available,
            "device": str(self.device),
            "output": "relative inverse depth, aligned to lidar per image with a scale and shift",
            "last_inference_s": self.last_inference_s,
        }

    def _load(self) -> DepthAnythingV2:
        if self._model is None:
            model = DepthAnythingV2(**MODEL_CONFIGS[self.encoder])
            model.load_state_dict(torch.load(self.checkpoint, map_location="cpu"))
            self._model = model.to(self.device).eval()
        return self._model

    def _cache_path(self, sd_token: str) -> Path:
        return self.cache_dir / f"{sd_token}.npy"

    def predict(self, sd_token: str, image_path: Path) -> np.ndarray:
        """Relative inverse depth at half the model input resolution."""
        cached = self._cache_path(sd_token)
        if cached.exists():
            return np.load(cached).astype(np.float32)
        with self._lock:
            if cached.exists():
                return np.load(cached).astype(np.float32)
            model = self._load()
            img = Image.open(image_path).convert("RGB")
            w, h = input_size(*img.size)
            x = np.asarray(img.resize((w, h), Image.BICUBIC), dtype=np.float32) / 255.0
            x = (x - IMAGENET_MEAN) / IMAGENET_STD
            t = torch.from_numpy(x.transpose(2, 0, 1)).unsqueeze(0).to(self.device)
            t0 = time.perf_counter()
            with torch.no_grad():
                pred = model(t)  # (1, h, w)
                pred = torch.nn.functional.interpolate(
                    pred.unsqueeze(1), size=(h // 2, w // 2), mode="bilinear", align_corners=False
                ).squeeze()
            out = pred.float().cpu().numpy()
            self.last_inference_s = round(time.perf_counter() - t0, 3)
            # write then rename so a concurrent reader never sees a partial file
            tmp = cached.with_suffix(".tmp.npy")
            np.save(tmp, out.astype(np.float16))
            tmp.replace(cached)
            return out

    # ----- comparison with lidar --------------------------------------

    def camera_depth(self, nusc: NuScenes, frame: Frame, channel: str, lidar_ref: np.ndarray) -> CameraDepth:
        sd = frame.camera_sds[channel]
        cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
        pred = self.predict(sd["token"], nusc.dataroot / sd["filename"])
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

    def scene_summary(self, nusc: NuScenes, scene_token: str) -> dict:
        """Per-keyframe error for a whole scene, cached as JSON next to the
        predictions. First call runs inference for any uncached image."""
        cached = self.cache_dir / f"scene_{scene_token}.json"
        if cached.exists():
            return json.loads(cached.read_text())
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
        out = {
            "scene_token": scene_token,
            "frames": frames,
            "abs_rel": float(np.mean([f["abs_rel"] for f in frames])),
            "rmse": float(np.mean([f["rmse"] for f in frames])),
            "delta1": float(np.mean([f["delta1"] for f in frames])),
        }
        tmp = cached.with_suffix(".tmp")
        tmp.write_text(json.dumps(out))
        tmp.replace(cached)
        return out

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
