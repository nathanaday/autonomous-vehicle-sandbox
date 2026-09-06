"""Fill data/cache for the viewer, one scene at a time.

    uv run python cli.py depth  --scene scene-0061
    uv run python cli.py fusion --scene scene-0061 [--source camera|lidar] [--voxel 0.2] [--mask on|off]
    uv run python cli.py splat  --scene scene-0061 [--views 6|18] [--unposed]
    uv run python cli.py all    --scene scene-0061 --scene scene-0103
    uv run python cli.py all    --all-scenes

Results already in the cache are skipped, so a run is safe to interrupt and
repeat. The viewer (backend/) only reads what this writes. Models come from
scripts/fetch_models.sh; see README.md here for what each task needs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Open3D's TSDF integration runs four times slower with a thread per core on
# Apple silicon than with four, as the threads spin on locks. Set before
# numpy and open3d load; an explicit OMP_NUM_THREADS still wins.
os.environ.setdefault("OMP_NUM_THREADS", "4")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))  # the loader, geometry and cache readers are shared with the viewer

from app.depth import DepthCache  # noqa: E402
from app.fusion import SOURCES, VOXELS, FusionCache, fusion_key  # noqa: E402
from app.nuscenes import CAMERA_CHANNELS, NuScenes  # noqa: E402
from app.splat import SplatCache, splat_key  # noqa: E402

DATA = ROOT / "data"
DATAROOT = Path(os.environ.get("NUSCENES_DATAROOT", DATA / "nuscenes"))
DEPTH_CACHE = Path(os.environ.get("DEPTH_CACHE", DATA / "cache" / "depth"))
FUSION_CACHE = Path(os.environ.get("FUSION_CACHE", DATA / "cache" / "fusion"))
SPLAT_CACHE = Path(os.environ.get("SPLAT_CACHE", DATA / "cache" / "splat"))
DEPTH_CHECKPOINT = Path(os.environ.get(
    "DEPTH_ANYTHING_CHECKPOINT", DATA / "models" / "depth-anything-v2" / "depth_anything_v2_vitb.pth"))
DA3_MODEL_DIR = Path(os.environ.get("DA3_MODEL_DIR", DATA / "models" / "da3" / "DA3NESTED-GIANT-LARGE-1.1"))


def need(path: Path, what: str) -> None:
    if not path.exists():
        raise SystemExit(f"{what} not found at {path}. Run scripts/fetch_models.sh; see compute/README.md.")


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


# ----- tasks ----------------------------------------------------------------


def run_depth(nusc: NuScenes, scenes: list[dict]) -> None:
    cache = DepthCache(DEPTH_CACHE)
    cache.cache_dir.mkdir(parents=True, exist_ok=True)
    predictor = None
    for scene in scenes:
        todo = [
            sd for sample in nusc.samples_of_scene[scene["token"]]
            for ch, sd in nusc.keyframe_sd[sample["token"]].items()
            if ch in CAMERA_CHANNELS and not cache.pred_path(sd["token"]).exists()
        ]
        if not todo and cache.has_scene(scene["token"]):
            print(f"depth  {scene['name']}: done already")
            continue
        if todo:
            if predictor is None:
                need(DEPTH_CHECKPOINT, "Depth Anything V2 checkpoint")
                from depth import DepthPredictor, save_prediction
                predictor = DepthPredictor(DEPTH_CHECKPOINT)
                print(f"depth  model loaded on {predictor.device}")
            t0 = time.time()
            for i, sd in enumerate(todo, 1):
                save_prediction(cache.pred_path(sd["token"]), predictor.predict(DATAROOT / sd["filename"]))
                if i % 30 == 0 or i == len(todo):
                    print(f"depth  {scene['name']}: {i}/{len(todo)} images, {i / (time.time() - t0):.1f} img/s", flush=True)
        summary = cache.summarize_scene(nusc, scene["token"])
        write_json(cache.summary_path(scene["token"]), summary)
        print(f"depth  {scene['name']}: AbsRel {summary['abs_rel'] * 100:.1f}%  δ1 {summary['delta1'] * 100:.1f}%")


def run_fusion(nusc: NuScenes, scenes: list[dict], sources: list[str], voxels: list[float], masks: list[bool]) -> None:
    depth = DepthCache(DEPTH_CACHE)
    cache = FusionCache(FUSION_CACHE)
    cache.cache_dir.mkdir(parents=True, exist_ok=True)
    if "camera" in sources:
        run_depth(nusc, [s for s in scenes if not depth.has_scene(s["token"])])
    from fusion import fuse
    for scene in scenes:
        for source in sources:
            for voxel in voxels:
                for mask in masks:
                    key = fusion_key(scene["token"], source, voxel, mask)
                    label = f"fusion {scene['name']} {source} {voxel:g} m {'masked' if mask else 'unmasked'}"
                    if cache.meta_path(key).exists():
                        print(f"{label}: done already")
                        continue
                    print(f"{label} ...", flush=True)
                    meta = fuse(nusc, depth, scene["token"], source, voxel, mask, cache.mesh_path(key),
                                lambda p, m: None)
                    write_json(cache.meta_path(key), meta)
                    print(f"{label}: {meta['triangles']:,} triangles in {meta['seconds']} s")


def run_splat(nusc: NuScenes, scenes: list[dict], views: int, posed: bool) -> None:
    cache = SplatCache(SPLAT_CACHE)
    cache.cache_dir.mkdir(parents=True, exist_ok=True)
    todo = [
        (scene, sample["token"], splat_key(sample["token"], views, posed))
        for scene in scenes for sample in nusc.samples_of_scene[scene["token"]]
        if not cache.meta_path(splat_key(sample["token"], views, posed)).exists()
    ]
    for scene in scenes:
        n = sum(1 for s, _, _ in todo if s is scene)
        if n == 0:
            print(f"splat  {scene['name']}: done already")
    if not todo:
        return
    need(DA3_MODEL_DIR / "model.safetensors", "Depth Anything 3 checkpoint")
    import splat_export as se

    device = se.pick_device()
    print(f"splat  loading Depth Anything 3 (1.4B parameters) on {device.type} ...", flush=True)
    t0 = time.perf_counter()
    model, adapter_inputs = se.load_model(str(DA3_MODEL_DIR), device)
    t_load = time.perf_counter() - t0
    progress = se.Progress(len(todo))
    for i, (scene, token, key) in enumerate(todo):
        print(f"splat  {scene['name']} keyframe {key}", flush=True)
        progress.keyframe(i)
        se.export_sample(nusc, model, adapter_inputs, device, progress, token, key, cache.cache_dir,
                         views, not posed, 504, 0.7, t_load)
        se.free_memory(device)


# ----- main -----------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task", choices=("depth", "fusion", "splat", "all"))
    ap.add_argument("--scene", action="append", default=[], help="scene name, e.g. scene-0061; repeatable")
    ap.add_argument("--all-scenes", action="store_true", help="every scene on disk")
    ap.add_argument("--source", action="append", choices=SOURCES, help="fusion depth source; default both")
    ap.add_argument("--voxel", action="append", type=float, choices=VOXELS, help="fusion voxel size; default all")
    ap.add_argument("--mask", choices=("on", "off", "both"), default="both", help="fusion: mask moving objects")
    ap.add_argument("--views", type=int, choices=(6, 18), default=6, help="splat: this keyframe, or with neighbours")
    ap.add_argument("--unposed", action="store_true", help="splat: let DA3 estimate the camera poses")
    args = ap.parse_args()

    need(DATAROOT / "v1.0-mini" / "scene.json", "nuScenes v1.0-mini")
    nusc = NuScenes(DATAROOT)
    by_name = {s["name"]: s for s in nusc.table["scene"]}
    if args.all_scenes:
        scenes = list(by_name.values())
    else:
        missing = [n for n in args.scene if n not in by_name]
        if missing or not args.scene:
            raise SystemExit(f"choose --scene from {', '.join(by_name)}, or --all-scenes")
        scenes = [by_name[n] for n in args.scene]

    masks = {"on": [True], "off": [False], "both": [True, False]}[args.mask]
    t0 = time.time()
    if args.task in ("depth", "all"):
        run_depth(nusc, scenes)
    if args.task in ("fusion", "all"):
        run_fusion(nusc, scenes, args.source or list(SOURCES), args.voxel or list(VOXELS), masks)
    if args.task in ("splat", "all"):
        run_splat(nusc, scenes, args.views, not args.unposed)
    print(f"done in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
