"""Train a Gaussian splat of one exported scene with the official 3D Gaussian
Splatting code, then file the result where the viewer reads it. Runs on the
GPU machine; needs only the Python standard library besides the trainer's
own environment.

    python gs3d/train.py export/scene-0061_kf_m1 [export/...] [--no-depth] [--iterations 30000] [--eval] [trainer args...]

Several exports train one after the other, so one call can fill a queue.

Layout on the machine, relative to --root (default: the parent of this file's
directory, i.e. ~/av-gs3d when setup_remote.sh put it there):
  gaussian-splatting/   the official repository, built by setup_remote.sh
  .venv/                its environment
  export/<name>/        scenes from compute/gs3d/export.py
  runs/<key>/           the trainer's output and log
  cache/gs3d/<key>.ply  the result, plus <key>.json; make gs3d-pull fetches these
                        into data/cache/gs3d

The key names the scene and the options, as backend/app/gs3d.py expects:
<scene token[:12]>_<kf|sweeps>_m<0|1>_d<0|1>.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ply_vertex_count(path: Path) -> int:
    with open(path, "rb") as f:
        for _ in range(64):
            line = f.readline()
            if line.startswith(b"element vertex"):
                return int(line.split()[-1])
            if line.strip() == b"end_header":
                break
    raise SystemExit(f"{path}: no vertex count in the PLY header")


def gpu_name() -> str | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exports", type=Path, nargs="+", help="exported scene folders, e.g. export/scene-0061_kf_m1, trained in turn")
    ap.add_argument("--root", type=Path, default=HERE.parent, help="where gaussian-splatting/, .venv/, runs/ and cache/ live")
    ap.add_argument("--iterations", type=int, default=30_000)
    ap.add_argument("--no-depth", action="store_true", help="train without the Depth Anything prior even when the export has it")
    ap.add_argument("--eval", action="store_true", help="hold out every 8th image and report its PSNR (the trainer's --eval)")
    ap.add_argument("--force", action="store_true", help="retrain even if the result exists")
    args, extra = ap.parse_known_args()  # anything else goes to the trainer, e.g. --antialiasing --train_test_exp
    args.extra = [a for a in extra if a != "--"]

    root = args.root.resolve()
    repo = root / "gaussian-splatting"
    python = root / ".venv" / "bin" / "python"
    exports = [(e if e.is_absolute() else root / e).resolve() for e in args.exports]
    for p, what in [(repo / "train.py", "the official repository"), (python, "its environment")] + [(e / "scene.json", "an export") for e in exports]:
        if not p.exists():
            raise SystemExit(f"{what} not found at {p}. Run setup_remote.sh, and make gs3d-push from the repository.")
    for export in exports:
        train(export, args, root, repo, python)


def train(export: Path, args: argparse.Namespace, root: Path, repo: Path, python: Path) -> None:
    scene = json.loads((export / "scene.json").read_text())

    use_depth = scene["depth_prior_available"] and not args.no_depth
    key = f"{scene['scene_token'][:12]}_{scene['images']}_m{int(scene['mask_moving'])}_d{int(use_depth)}"
    run = root / "runs" / key
    cache = root / "cache" / "gs3d"
    cache.mkdir(parents=True, exist_ok=True)
    if (cache / f"{key}.json").exists() and not args.force:
        print(f"{key}: done already, {cache / f'{key}.ply'}")
        return
    if args.no_depth and not scene["depth_prior_available"]:
        print(f"{key}: the export has no depth prior; --no-depth changes nothing")

    cmd = [str(python), "train.py", "-s", str(export), "-m", str(run), "--disable_viewer",
           "--iterations", str(args.iterations), "--save_iterations", str(args.iterations),
           "--test_iterations", "7000", str(args.iterations)]
    if use_depth:
        cmd += ["-d", "depths"]
    if args.eval:
        cmd += ["--eval"]
    if scene["images"] == "sweeps":
        cmd += ["--data_device", "cpu"]  # 1,300 images at 1600x900 do not fit next to the model on a 24 GB card
    cmd += args.extra

    run.mkdir(parents=True, exist_ok=True)
    log_path = run / "train.log"
    print(f"{key}: training {scene['n_images']} images"
          + (" with the depth prior" if use_depth else "") + f", log at {log_path}", flush=True)
    print("  " + " ".join(cmd), flush=True)
    t0 = time.time()
    psnr: dict[str, float] = {}
    last_stamp = -1
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    with open(log_path, "w") as log, subprocess.Popen(cmd, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                       text=True, env=env, errors="replace") as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            m = re.search(r"\[ITER (\d+)\] Evaluating (\w+): L1 ([\d.e+-]+) PSNR ([\d.e+-]+)", line)
            if m and int(m.group(1)) == args.iterations:
                psnr[m.group(2)] = round(float(m.group(4)), 2)
            # the progress bar rewrites its line; print it at intervals only
            if "Training progress" in line:
                stamp = re.findall(r"(\d+)/(\d+)", line)
                if stamp and int(stamp[-1][0]) % 1000 == 0 and int(stamp[-1][0]) != last_stamp:
                    last_stamp = int(stamp[-1][0])
                    print(f"  {last_stamp}/{stamp[-1][1]} iterations, {(time.time() - t0) / 60:.1f} min", flush=True)
            elif line.strip() and not re.match(r"\s*Reading camera (\d+)/(?!\1\b)", line):
                print("  " + line.rstrip(), flush=True)
    seconds = time.time() - t0
    if proc.returncode != 0:
        raise SystemExit(f"{key}: the trainer failed with exit code {proc.returncode}; see {log_path}")

    ply = run / "point_cloud" / f"iteration_{args.iterations}" / "point_cloud.ply"
    if not ply.exists():
        raise SystemExit(f"{key}: no result at {ply}; see {log_path}")
    shutil.copyfile(ply, cache / f"{key}.ply")
    meta = {
        "scene_token": scene["scene_token"],
        "scene_name": scene["scene_name"],
        "images": scene["images"],
        "mask_moving": scene["mask_moving"],
        "depth_prior": use_depth,
        "method": "3D Gaussian Splatting (Kerbl et al. 2023), official trainer",
        "iterations": args.iterations,
        "eval_holdout": args.eval,
        "trainer_args": args.extra,
        "n_images": scene["n_images"],
        "n_keyframe_images": scene["n_keyframe_images"],
        "n_masked_images": scene["n_masked_images"],
        "moving_instances": scene["moving_instances"],
        "n_points_init": scene["n_points"],
        "n_gaussians": ply_vertex_count(ply),
        "psnr": psnr,
        "gpu": gpu_name(),
        "seconds": round(seconds, 1),
        "ply_bytes": ply.stat().st_size,
        "poses": scene["poses"],
    }
    # written last: its presence is what marks the result as done
    (cache / f"{key}.json").write_text(json.dumps(meta))
    print(f"{key}: {meta['n_gaussians']:,} Gaussians, PSNR {psnr}, {seconds / 60:.1f} min, {meta['ply_bytes'] / 1e6:.0f} MB -> {cache / f'{key}.ply'}")


if __name__ == "__main__":
    main()
