"""HTTP API for the nuScenes viewer.

Run from `backend/` with `uv run uvicorn app.main:app --reload`.
Set NUSCENES_DATAROOT to point at the extracted split (defaults to
`../nuscenes/data`). If `../frontend/dist` exists it is served at `/`.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .nuscenes import NuScenes

ROOT = Path(__file__).resolve().parents[2]
DATAROOT = Path(os.environ.get("NUSCENES_DATAROOT", ROOT / "nuscenes" / "data"))
FRONTEND_DIST = ROOT / "frontend" / "dist"

nusc = NuScenes(DATAROOT)
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


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
