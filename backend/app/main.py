"""HTTP API for the nuScenes viewer.

Run from `backend/` with `uv run uvicorn app.main:app --reload`.
Serves the dataset and the caches that compute/cli.py fills; it computes
nothing itself. Everything large lives under `../data/` (see DETAILS.md, "Data").
Override the locations with NUSCENES_DATAROOT, DEPTH_CACHE, FUSION_CACHE,
SPLAT_CACHE, GS3D_CACHE and OCC3D_ROOT. If `../frontend/dist` exists it is served at `/`.
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

from .depth import MODEL_INFO, DepthCache, NotComputed
from .fusion import SOURCES, VOXELS, FusionCache
from .gs3d import Gs3dCache
from .nuscenes import NuScenes
from .occ3d import Occ3dLabels
from .splat import SplatCache

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DATAROOT = Path(os.environ.get("NUSCENES_DATAROOT", DATA / "nuscenes"))
FRONTEND_DIST = ROOT / "frontend" / "dist"
DEPTH_CACHE = Path(os.environ.get("DEPTH_CACHE", DATA / "cache" / "depth"))
FUSION_CACHE = Path(os.environ.get("FUSION_CACHE", DATA / "cache" / "fusion"))
SPLAT_CACHE = Path(os.environ.get("SPLAT_CACHE", DATA / "cache" / "splat"))
GS3D_CACHE = Path(os.environ.get("GS3D_CACHE", DATA / "cache" / "gs3d"))
OCC3D_ROOT = Path(os.environ.get("OCC3D_ROOT", DATA / "occ3d"))

if not (DATAROOT / "v1.0-mini" / "scene.json").exists():
    raise SystemExit(f"nuScenes v1.0-mini not found at {DATAROOT}. Run 'make data' first; see DETAILS.md, Data.")

nusc = NuScenes(DATAROOT)
depth = DepthCache(DEPTH_CACHE)
fusion = FusionCache(FUSION_CACHE)
splats = SplatCache(SPLAT_CACHE)
gs3d = Gs3dCache(GS3D_CACHE)
occ3d = Occ3dLabels(OCC3D_ROOT)
app = FastAPI(title="nuScenes sandbox")


def _get(table: str, token: str) -> dict:
    try:
        return nusc.get(table, token)
    except KeyError:
        raise HTTPException(404, f"no {table} with token {token}")


def _features(scene: dict) -> dict:
    """Which caches hold results for the scene."""
    tokens = [s["token"] for s in nusc.samples_of_scene[scene["token"]]]
    return {
        "depth": depth.has_scene(scene["token"]),
        "fusion": fusion.has_scene(scene["token"]),
        "splat": splats.has_scene(tokens),
        "gs3d": gs3d.has_scene(scene["token"]),
        "occ3d": occ3d.has_scene(scene["name"], tokens),
    }


def _not_computed(task: str, scene_token: str, options: str = "") -> HTTPException:
    """404 whose detail tells the reader how to fill the cache."""
    name = nusc.get("scene", scene_token)["name"]
    return HTTPException(404, f"{name} has no {task} results yet. Compute them offline: "
                              f"cd compute && uv run python cli.py {task} --scene {name}{options}")


# ----- dataset ------------------------------------------------------------


@app.get("/api/features")
def features():
    """Which features have results for at least one scene, and the views each
    one unlocks. The UI locks the views whose feature has nothing to show."""
    scenes = nusc.table["scene"]
    per_scene = [_features(s) for s in scenes]
    return {
        "dataset": {"present": True, "views": ["explore"], "make": "make data"},
        "depth": {"present": any(f["depth"] for f in per_scene), "views": ["depth"], "make": "make data-depth"},
        "fusion": {"present": any(f["fusion"] for f in per_scene), "views": ["fusion"], "make": "make data-fusion"},
        "splat": {"present": any(f["splat"] for f in per_scene), "views": ["splat"], "make": "make data-splat"},
        "gs3d": {"present": any(f["gs3d"] for f in per_scene), "views": ["gs3d"], "make": "make data-gs3d"},
        "occ3d": {"present": any(f["occ3d"] for f in per_scene), "views": ["occ3d"], "make": "make data-occ3d"},
    }


@app.get("/api/scenes")
def scenes():
    return [{**nusc.scene_summary(s), "features": _features(s)} for s in nusc.table["scene"]]


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


def _frame_depth(sample_token: str):
    frame = nusc.frame(sample_token)
    try:
        return frame, depth.frame_depth(nusc, frame)
    except NotComputed:
        raise _not_computed("depth", frame.sample["scene_token"])


@app.get("/api/samples/{sample_token}/depth")
def sample_depth(sample_token: str):
    """Per-camera fit of the stock model against the lidar sweep."""
    _get("sample", sample_token)
    _, cams = _frame_depth(sample_token)
    z = np.concatenate([c.z_lidar for c in cams])
    zp = np.concatenate([c.z_pred for c in cams])
    ratio = np.maximum(zp / z, z / zp)
    return {
        "token": sample_token,
        "model": MODEL_INFO,
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
    """Depth error per keyframe across one scene."""
    _get("scene", scene_token)
    try:
        return depth.scene_summary(scene_token)
    except NotComputed:
        raise _not_computed("depth", scene_token)


@app.get("/api/samples/{sample_token}/depthcloud.bin")
def sample_depth_cloud(sample_token: str, stride: int = Query(3, ge=1, le=8)):
    """Float32, 7 per point: x y z r g b camera_index (ref ego frame)."""
    _get("sample", sample_token)
    frame, cams = _frame_depth(sample_token)
    pts = depth.depth_cloud(nusc, frame, cams, stride=stride)
    return Response(pts.tobytes(), media_type="application/octet-stream",
                    headers={"X-Stride": "7", "Cache-Control": "max-age=3600"})


@app.get("/api/samples/{sample_token}/depthlidar.bin")
def sample_depth_lidar(sample_token: str):
    """Float32, 5 per point: camera_index u v z_lidar z_pred. The lidar points
    used to fit each camera, with the model's fitted depth at the same pixel."""
    _get("sample", sample_token)
    _, cams = _frame_depth(sample_token)
    parts = [
        np.stack([np.full_like(c.u, i), c.u, c.v, c.z_lidar, c.z_pred], axis=1)
        for i, c in enumerate(cams)
    ]
    pts = np.concatenate(parts).astype(np.float32)
    return Response(pts.tobytes(), media_type="application/octet-stream",
                    headers={"X-Stride": "5", "Cache-Control": "max-age=3600"})


@lru_cache(maxsize=2048)
def _depth_png(sd_token: str, width: int | None) -> bytes:
    return depth.colorized_png(depth.pred(sd_token), width)


@app.get("/api/depth/{sd_token}.png")
def depth_image(sd_token: str, w: int | None = Query(None, ge=64, le=1600)):
    sd = _get("sample_data", sd_token)
    if sd["fileformat"] != "jpg":
        raise HTTPException(400, "not an image")
    try:
        png = _depth_png(sd_token, w)
    except NotComputed:
        raise _not_computed("depth", nusc.get("sample", sd["sample_token"])["scene_token"])
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


# ----- volumetric fusion --------------------------------------------------


@app.get("/api/scenes/{scene_token}/fusion")
def scene_fusion(
    scene_token: str,
    source: str = Query("camera"),
    voxel: float = Query(0.2),
    mask: bool = Query(True),
):
    """The fused mesh's stats for one scene and option set, state 'ready',
    then fetch /api/fusion/{key}.ply; or state 'missing' with the command
    that computes it."""
    _get("scene", scene_token)
    if source not in SOURCES:
        raise HTTPException(400, f"source must be one of {SOURCES}")
    if voxel not in VOXELS:
        raise HTTPException(400, f"voxel must be one of {VOXELS}")
    status = fusion.status(scene_token, source, voxel, mask)
    if status["state"] == "missing":
        options = f" --source {source} --voxel {voxel:g} --mask {'on' if mask else 'off'}"
        status["message"] = _not_computed("fusion", scene_token, options).detail
    return status


@app.get("/api/fusion/{key}.ply")
def fusion_mesh(key: str):
    """Binary PLY with vertex colors and normals, in the scene frame, which is
    the ego frame of the scene's first keyframe."""
    path = fusion.mesh_path(key)
    if not path.exists() or "/" in key or ".." in key:
        raise HTTPException(404, "no mesh with that key")
    return FileResponse(path, media_type="application/octet-stream",
                        headers={"Cache-Control": "max-age=86400"})


# ----- Gaussian splats (Depth Anything 3) --------------------------------


def _splat_options(views: int, posed: bool) -> str:
    if views not in (6, 18):
        raise HTTPException(400, "views must be 6 or 18")
    return f" --views {views}" + ("" if posed else " --unposed")


@app.get("/api/scenes/{scene_token}/splat")
def scene_splat(scene_token: str, views: int = Query(6), posed: bool = Query(True)):
    """Which keyframes of the scene have a splat for these options."""
    _get("scene", scene_token)
    options = _splat_options(views, posed)
    tokens = [s["token"] for s in nusc.samples_of_scene[scene_token]]
    status = splats.scene_status(scene_token, tokens, views, posed)
    if status["n_ready"] < status["n_total"]:
        status["message"] = _not_computed("splat", scene_token, options).detail
    return status


@app.get("/api/samples/{sample_token}/splat")
def sample_splat(sample_token: str, views: int = Query(6), posed: bool = Query(True)):
    """Stats of the keyframe's splat when computed, else state 'missing'.
    Fetch /api/splat/{key}.ply when ready."""
    sample = _get("sample", sample_token)
    options = _splat_options(views, posed)
    status = splats.sample_status(sample_token, views, posed)
    if status["state"] == "missing":
        status["message"] = _not_computed("splat", sample["scene_token"], options).detail
    return status


@app.get("/api/splat/{key}.ply")
def splat_ply(key: str):
    """3DGS-format PLY in the ego frame of the keyframe."""
    path = splats.ply_path(key)
    if "/" in key or ".." in key or not path.exists():
        raise HTTPException(404, "no splat with that key")
    return FileResponse(path, media_type="application/octet-stream",
                        headers={"Cache-Control": "max-age=86400"})


# ----- trained Gaussian splats (official 3DGS) ----------------------------


@app.get("/api/scenes/{scene_token}/gs3d")
def scene_gs3d(scene_token: str):
    """Every trained splat of the scene with its stats and the per-keyframe
    ego poses in the scene frame; fetch /api/gs3d/{key}.ply for one. With
    none, a message saying how they are made."""
    scene = _get("scene", scene_token)
    variants = gs3d.variants(scene_token)
    out = {"scene_token": scene_token, "variants": variants}
    if not variants:
        out["message"] = (f"{scene['name']} has no trained splat yet. Export it, train on a CUDA machine, "
                          f"and pull the result: make gs3d-export SCENES={scene['name']}; see compute/README.md.")
    return out


@app.get("/api/gs3d/{key}.ply")
def gs3d_ply(key: str):
    """3DGS-format PLY in the scene frame, which is the ego frame of the
    scene's first keyframe."""
    path = gs3d.ply_path(key)
    if "/" in key or ".." in key or not path.exists():
        raise HTTPException(404, "no trained splat with that key")
    return FileResponse(path, media_type="application/octet-stream",
                        headers={"Cache-Control": "max-age=86400"})


# ----- Occ3D semantic occupancy labels -----------------------------------


def _occ3d_missing(scene: dict) -> HTTPException:
    return HTTPException(404, f"{scene['name']} has no Occ3D labels. They are a download, not a computation: "
                              f"make data-occ3d fetches the labels of the bundled scenes; see DETAILS.md, Data.")


@app.get("/api/scenes/{scene_token}/occ3d")
def scene_occ3d(scene_token: str):
    """Which keyframes of the scene have an occupancy label, the grid
    geometry and the class list."""
    scene = _get("scene", scene_token)
    tokens = [s["token"] for s in nusc.samples_of_scene[scene_token]]
    status = occ3d.scene_status(scene["name"], tokens)
    if status["n_ready"] == 0:
        status["message"] = _occ3d_missing(scene).detail
    return status


@app.get("/api/samples/{sample_token}/occ3d")
def sample_occ3d(sample_token: str):
    """Class counts and visibility totals of the keyframe's label, and how
    the lidar sweep lands in the grid."""
    sample = _get("sample", sample_token)
    scene = nusc.get("scene", sample["scene_token"])
    if not occ3d.path(scene["name"], sample_token).exists():
        raise _occ3d_missing(scene)
    lidar = nusc.read_lidar(nusc.frame(sample_token))
    return occ3d.stats(scene["name"], sample_token, lidar)


@app.get("/api/samples/{sample_token}/occ3d.bin")
def sample_occ3d_grid(sample_token: str):
    """200 x 200 x 16 bytes in x, y, z order (z fastest), ego frame. Bits
    0-4 hold the class id, 17 for free; bit 5 is set when the lidar saw the
    voxel, bit 6 when a camera did."""
    sample = _get("sample", sample_token)
    scene = nusc.get("scene", sample["scene_token"])
    if not occ3d.path(scene["name"], sample_token).exists():
        raise _occ3d_missing(scene)
    return Response(occ3d.packed(scene["name"], sample_token), media_type="application/octet-stream",
                    headers={"Cache-Control": "max-age=3600"})


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
