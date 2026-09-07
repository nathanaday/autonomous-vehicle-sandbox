"""Print the files of one data bundle for the given scenes, relative to data/.

    uv run --project backend python scripts/list_files.py <bundle> <scene-name>...

Bundles: dataset (tables plus the keyframe files of each scene, no sweeps),
depth, fusion, splat, gs3d (the cache files of each scene). scripts/bundle_data.sh
feeds the list to tar.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.nuscenes import NuScenes  # noqa: E402
from app.splat import splat_key  # noqa: E402

DATA = ROOT / "data"
DATAROOT = Path(os.environ.get("NUSCENES_DATAROOT", DATA / "nuscenes"))


def main() -> None:
    bundle, *names = sys.argv[1:]
    nusc = NuScenes(DATAROOT)
    by_name = {s["name"]: s for s in nusc.table["scene"]}
    missing = [n for n in names if n not in by_name]
    if missing or not names:
        raise SystemExit(f"unknown scenes {missing}; on disk: {', '.join(by_name)}")
    scenes = [by_name[n] for n in names]
    out: list[str] = []

    if bundle == "dataset":
        out += [f"nuscenes/{nusc.version}/{p.name}" for p in sorted((DATAROOT / nusc.version).glob("*.json"))]
        for scene in scenes:
            for sample in nusc.samples_of_scene[scene["token"]]:
                out += [f"nuscenes/{sd['filename']}" for sd in nusc.keyframe_sd[sample["token"]].values()]
    elif bundle == "depth":
        for scene in scenes:
            out.append(f"cache/depth/scene_{scene['token']}.json")
            for sample in nusc.samples_of_scene[scene["token"]]:
                for sd in nusc.keyframe_sd[sample["token"]].values():
                    if sd["fileformat"] == "jpg":
                        out.append(f"cache/depth/{sd['token']}.npy")
    elif bundle == "fusion":
        for scene in scenes:
            out += [f"cache/fusion/{p.name}" for p in sorted((DATA / "cache" / "fusion").glob(f"{scene['token'][:12]}_*"))]
    elif bundle == "splat":
        for scene in scenes:
            for sample in nusc.samples_of_scene[scene["token"]]:
                prefix = splat_key(sample["token"], 6, True).split("_v")[0]
                out += [f"cache/splat/{p.name}" for p in sorted((DATA / "cache" / "splat").glob(f"{prefix}_*"))]
    elif bundle == "gs3d":
        for scene in scenes:
            out += [f"cache/gs3d/{p.name}" for p in sorted((DATA / "cache" / "gs3d").glob(f"{scene['token'][:12]}_*"))]
    else:
        raise SystemExit("bundle must be dataset, depth, fusion, splat or gs3d")

    absent = [f for f in out if not (DATA / f).exists()]
    if absent:
        raise SystemExit(f"{len(absent)} files missing for the {bundle} bundle, first: {absent[0]}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
