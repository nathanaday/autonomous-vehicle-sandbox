"""HTTP API for the nuScenes viewer.

Run from `backend/` with `uv run uvicorn app.main:app --reload`.
Everything large lives under `../data/` (see README, "Data"). Override the
locations with NUSCENES_DATAROOT, DEPTH_ANYTHING_CHECKPOINT and DEPTH_CACHE.
If `../frontend/dist` exists it is served at `/`.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .depth import DepthEstimator
from .fusion import SOURCES, VOXELS, FusionBuilder
from .nuscenes import NuScenes
from .splat import SplatBuilder

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DATAROOT = Path(os.environ.get("NUSCENES_DATAROOT", DATA / "nuscenes"))
FRONTEND_DIST = ROOT / "frontend" / "dist"
DEPTH_CHECKPOINT = Path(os.environ.get(
    "DEPTH_ANYTHING_CHECKPOINT", DATA / "models" / "depth-anything-v2" / "depth_anything_v2_vitb.pth"))
DEPTH_CACHE = Path(os.environ.get("DEPTH_CACHE", DATA / "cache" / "depth"))
FUSION_CACHE = Path(os.environ.get("FUSION_CACHE", DATA / "cache" / "fusion"))
SPLAT_CACHE = Path(os.environ.get("SPLAT_CACHE", DATA / "cache" / "splat"))
DA3_MODEL_DIR = Path(os.environ.get("DA3_MODEL_DIR", DATA / "models" / "da3" / "DA3NESTED-GIANT-LARGE-1.1"))

nusc = NuScenes(DATAROOT)
depth_model = DepthEstimator(DEPTH_CHECKPOINT, DEPTH_CACHE)
fusion = FusionBuilder(nusc, depth_model, FUSION_CACHE)
splats = SplatBuilder(SPLAT_CACHE, DA3_MODEL_DIR)
app = FastAPI(title="nuScenes sandbox")


def _get(table: str, token: str) -> dict:
    try:
        return nusc.get(table, token)
    except KeyError:
        raise HTTPException(404, f"no {table} with token {token}")


@app.get("/api/scenes")
def scenes():
    return [nusc.scene_summary(s) for s in nusc.table["scene"]]


@app.get("/api/scenes/{scene_token}")
def scene(scene_token: str):
    _get("scene", scene_token)
    return nusc.scene_detail(scene_token)


@app.get("/api/samples/{sample_token}")
def sample(sample_token: str):
    _get("sample", sample_token)
    return nusc.frame_detail(sample_token)


@app.get("/api/samples/{sample_token}/lidar.bin")
def lidar(sample_token: str):
    """Float32 little-endian, 5 per point: x y z intensity ring (ref ego frame)."""
    _get("sample", sample_token)
    pts = nusc.read_lidar(nusc.frame(sample_token))
    return Response(pts.tobytes(), media_type="application/octet-stream",
                    headers={"X-Stride": "5", "Cache-Control": "max-age=3600"})


@app.get("/api/samples/{sample_token}/radar.bin")
def radar(sample_token: str):
    """Float32 little-endian, 8 per point: x y z vx vy rcs dyn_prop channel."""
    _get("sample", sample_token)
    pts = nusc.read_all_radar(nusc.frame(sample_token))
    return Response(pts.tobytes(), media_type="application/octet-stream",
                    headers={"X-Stride": "8", "Cache-Control": "max-age=3600"})


@lru_cache(maxsize=2048)
def _resized_jpeg(filename: str, width: int) -> bytes:
    img = Image.open(DATAROOT / filename)
    if width < img.width:
        img = img.resize((width, round(img.height * width / img.width)), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


@app.get("/api/image/{sd_token}")
def image(sd_token: str, w: int | None = Query(None, ge=64, le=1600)):
    sd = _get("sample_data", sd_token)
    if sd["fileformat"] != "jpg":
        raise HTTPException(400, "not an image")
    headers = {"Cache-Control": "max-age=86400"}
    if w is None:
        return FileResponse(DATAROOT / sd["filename"], media_type="image/jpeg", headers=headers)
    return Response(_resized_jpeg(sd["filename"], w), media_type="image/jpeg", headers=headers)


# ----- depth estimation ---------------------------------------------------


def _require_depth():
    if not depth_model.available:
        raise HTTPException(
            503, f"Depth Anything checkpoint not found at {DEPTH_CHECKPOINT}. "
            "Set DEPTH_ANYTHING_CHECKPOINT to the .pth file.")


@app.get("/api/depth/info")
def depth_info():
    return depth_model.info()


@app.get("/api/samples/{sample_token}/depth")
def sample_depth(sample_token: str):
    """Per-camera fit of the stock model against the lidar sweep."""
    _get("sample", sample_token)
    _require_depth()
    frame = nusc.frame(sample_token)
    cams = depth_model.frame_depth(nusc, frame)
    z = np.concatenate([c.z_lidar for c in cams])
    zp = np.concatenate([c.z_pred for c in cams])
    ratio = np.maximum(zp / z, z / zp)
    return {
        "token": sample_token,
        "model": depth_model.info(),
        "cameras": [
            {
                "channel": c.channel,
                "sd_token": c.sd_token,
                "pred_shape": list(c.pred.shape),
                "scale": c.scale,
                "shift": c.shift,
                "n_lidar": c.n_lidar,
                "abs_rel": c.abs_rel,
                "rmse": c.rmse,
                "delta1": c.delta1,
            }
            for c in cams
        ],
        "overall": {
            "n_lidar": int(len(z)),
            "abs_rel": float(np.mean(np.abs(zp - z) / z)),
            "rmse": float(np.sqrt(np.mean((zp - z) ** 2))),
            "delta1": float(np.mean(ratio < 1.25)),
        },
    }


@app.get("/api/scenes/{scene_token}/depth")
def scene_depth(scene_token: str):
    """Depth error per keyframe across one scene. Slow on first call for a
    scene whose predictions are not cached yet (about 0.2 s per image)."""
    _get("scene", scene_token)
    _require_depth()
    return depth_model.scene_summary(nusc, scene_token)


@app.get("/api/samples/{sample_token}/depthcloud.bin")
def sample_depth_cloud(sample_token: str, stride: int = Query(3, ge=1, le=8)):
    """Float32, 7 per point: x y z r g b camera_index (ref ego frame)."""
    _get("sample", sample_token)
    _require_depth()
    frame = nusc.frame(sample_token)
    cams = depth_model.frame_depth(nusc, frame)
    pts = depth_model.depth_cloud(nusc, frame, cams, stride=stride)
    return Response(pts.tobytes(), media_type="application/octet-stream",
                    headers={"X-Stride": "7", "Cache-Control": "max-age=3600"})


@app.get("/api/samples/{sample_token}/depthlidar.bin")
def sample_depth_lidar(sample_token: str):
    """Float32, 5 per point: camera_index u v z_lidar z_pred. The lidar points
    used to fit each camera, with the model's fitted depth at the same pixel."""
    _get("sample", sample_token)
    _require_depth()
    frame = nusc.frame(sample_token)
    cams = depth_model.frame_depth(nusc, frame)
    parts = [
        np.stack([np.full_like(c.u, i), c.u, c.v, c.z_lidar, c.z_pred], axis=1)
        for i, c in enumerate(cams)
    ]
    pts = np.concatenate(parts).astype(np.float32)
    return Response(pts.tobytes(), media_type="application/octet-stream",
                    headers={"X-Stride": "5", "Cache-Control": "max-age=3600"})


@lru_cache(maxsize=2048)
def _depth_png(sd_token: str, width: int | None) -> bytes:
    sd = nusc.get("sample_data", sd_token)
    pred = depth_model.predict(sd_token, DATAROOT / sd["filename"])
    return depth_model.colorized_png(pred, width)


@app.get("/api/depth/{sd_token}.png")
def depth_image(sd_token: str, w: int | None = Query(None, ge=64, le=1600)):
    sd = _get("sample_data", sd_token)
    _require_depth()
    if sd["fileformat"] != "jpg":
        raise HTTPException(400, "not an image")
    return Response(_depth_png(sd_token, w), media_type="image/png",
                    headers={"Cache-Control": "max-age=86400"})


# ----- volumetric fusion --------------------------------------------------


@app.get("/api/scenes/{scene_token}/fusion")
def scene_fusion(
    scene_token: str,
    source: str = Query("camera"),
    voxel: float = Query(0.2),
    mask: bool = Query(True),
):
    """Status of the fused mesh for one scene. Starts the build in the
    background if it is not cached; poll until state is 'ready', then fetch
    /api/fusion/{key}.ply."""
    _get("scene", scene_token)
    if source not in SOURCES:
        raise HTTPException(400, f"source must be one of {SOURCES}")
    if voxel not in VOXELS:
        raise HTTPException(400, f"voxel must be one of {VOXELS}")
    if source == "camera":
        _require_depth()
    return fusion.status(scene_token, source, voxel, mask)


@app.get("/api/fusion/{key}.ply")
def fusion_mesh(key: str):
    """Binary little-endian PLY with vertex positions, normals and colors, in
    the ego frame of the scene's first keyframe."""
    path = fusion.mesh_path(key)
    if not path.exists() or "/" in key or ".." in key:
        raise HTTPException(404, "no mesh with that key")
    return FileResponse(path, media_type="application/octet-stream",
                        headers={"Cache-Control": "max-age=86400"})


# ----- Gaussian splats (Depth Anything 3) --------------------------------


@app.get("/api/splat/info")
def splat_info():
    return splats.info()


@app.get("/api/samples/{sample_token}/splat")
def sample_splat(sample_token: str, views: int = Query(6), posed: bool = Query(True)):
    """Status of the Gaussian splat for one keyframe. Starts the DA3 run in the
    background if it is not cached; poll until state is 'ready', then fetch
    /api/splat/{key}.ply."""
    _get("sample", sample_token)
    if views not in (6, 18):
        raise HTTPException(400, "views must be 6 or 18")
    if not splats.available:
        raise HTTPException(503, f"Depth Anything 3 checkpoint not found at {DA3_MODEL_DIR}. "
                                 "See README, Gaussian splat view.")
    return splats.status(sample_token, views, posed)


@app.get("/api/splat/{key}.ply")
def splat_ply(key: str):
    """3DGS-format PLY in the ego frame of the keyframe."""
    path = splats.ply_path(key)
    if "/" in key or ".." in key or not path.exists():
        raise HTTPException(404, "no splat with that key")
    return FileResponse(path, media_type="application/octet-stream",
                        headers={"Cache-Control": "max-age=86400"})


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
