"""Run Depth Anything over every keyframe camera image and fill the cache.

    uv run python -m app.precompute_depth

Safe to interrupt and rerun; cached images are skipped.
"""

from __future__ import annotations

import time

from .main import DATAROOT, depth_model, nusc
from .nuscenes import CAMERA_CHANNELS


def main() -> None:
    todo = [
        sd for sds in nusc.keyframe_sd.values()
        for ch, sd in sds.items() if ch in CAMERA_CHANNELS
    ]
    print(f"{len(todo)} camera keyframes, device {depth_model.device}")
    t0 = time.time()
    for i, sd in enumerate(todo, 1):
        depth_model.predict(sd["token"], DATAROOT / sd["filename"])
        if i % 50 == 0 or i == len(todo):
            rate = i / (time.time() - t0)
            print(f"{i}/{len(todo)}  {rate:.1f} img/s  ~{(len(todo) - i) / rate / 60:.1f} min left", flush=True)
    for scene in nusc.table["scene"]:
        s = depth_model.scene_summary(nusc, scene["token"])
        print(f"{scene['name']}  AbsRel {s['abs_rel'] * 100:.1f}%  d1 {s['delta1'] * 100:.1f}%", flush=True)


if __name__ == "__main__":
    main()
