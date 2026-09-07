# compute

Offline compute for the viewer. It runs the models and writes their results
into `data/cache`, where the backend reads them. The viewer never runs a
model, so a team member who only wants to look at results needs the data
bundles and not this directory.

## What it computes

| Task | Model | Writes | Time per scene on an Apple GPU |
|---|---|---|---|
| `depth` | Depth Anything V2 ViT-B | `data/cache/depth/<sd_token>.npy` per keyframe camera image, `scene_<token>.json` with the error against lidar | about 1 minute |
| `fusion` | none (uses the depth cache and the lidar) | `data/cache/fusion/<key>.ply` and `.json` for each source, voxel size and mask setting, 12 combinations | about 4 minutes for all 12 |
| `splat` | Depth Anything 3, nested Giant + metric Large | `data/cache/splat/<key>.ply`, `.json`, `.npz` per keyframe | about 3.5 minutes |
| `gs3d` | official 3D Gaussian Splatting trainer, on a CUDA machine | `data/cache/gs3d/<key>.ply` and `.json` per scene and option set | 30 to 60 minutes per scene on a rented GPU; see below |

## Setup

Requires Python 3.12 with [uv](https://docs.astral.sh/uv/). The environment
is separate from the backend's because Depth Anything 3 pins `numpy<2` and
the models need torch, which the viewer does not.

```sh
cd compute && uv sync          # torch, open3d, Depth Anything 3
../scripts/fetch_models.sh     # both checkpoints into ../data/models, 7.2 GB
```

`fetch_models.sh depth` or `fetch_models.sh splat` fetches one. The Depth
Anything V2 ViT-B checkpoint (372 MB, Apache 2.0) comes from its Hugging Face
release; the Depth Anything 3 checkpoint (6.8 GB, CC BY-NC 4.0) from
`depth-anything/DA3NESTED-GIANT-LARGE-1.1`.

## Run

```sh
uv run python cli.py all --scene scene-0061
uv run python cli.py depth --scene scene-0061 --scene scene-0103
uv run python cli.py fusion --scene scene-0061 --source lidar --voxel 0.2 --mask on
uv run python cli.py splat --scene scene-0061 --views 18
uv run python cli.py all --all-scenes
```

Results already in the cache are skipped, so a run is safe to interrupt and
repeat. `fusion` computes `depth` first when the camera source needs it.
Restart the backend after a run only if it was started before the cache
directory existed; otherwise it picks new files up on the next request.

The paths follow the backend's: `NUSCENES_DATAROOT`, `DEPTH_CACHE`,
`FUSION_CACHE`, `SPLAT_CACHE`, `GS3D_CACHE`, `GS3D_EXPORT`,
`DEPTH_ANYTHING_CHECKPOINT` and `DA3_MODEL_DIR` override them.

## Trained splats (`gs3d/`)

The trained splat view shows one Gaussian splat of a whole scene, optimised
with the [official 3D Gaussian Splatting code](https://github.com/graphdeco-inria/gaussian-splatting)
(Kerbl et al. 2023). The rasteriser is a CUDA extension, so training runs on
an NVIDIA machine, for example a Lambda instance. Everything else runs here.

The scene is exported in the COLMAP layout the trainer reads, with the
dataset's poses and intrinsics in place of a structure-from-motion run:

```sh
make gs3d-export SCENES="scene-0061"                      # data/gs3d/scene-0061_kf_m1, 39 keyframes x 6 cameras, 0.3 GB
make gs3d-export SCENES="scene-0061" GS3D_ARGS=--sweeps   # data/gs3d/scene-0061_sweeps_m1, plus the 12 Hz sweeps, 1.6 GB
```

`compute/gs3d/export.py` needs only the viewer's environment. It writes the
images, with an alpha channel that masks the objects that move during the
scene and the ego car's body in the back camera; the trainer takes alpha as
a loss mask. The initial Gaussians are every keyframe's lidar returns,
static ones only, coloured from the cameras. When the depth cache has a
prediction for every image, it also writes Depth Anything's inverse depth
per image with a scale and shift fitted to the lidar, which the trainer uses
as its depth prior. Sweeps have no prediction, so a sweeps export has no
depth prior unless `depth` is first run on them. `--no-mask` keeps moving
objects. The world frame is the ego frame of the first keyframe, so the
result lands in the same frame as the fused mesh.

On the GPU machine, once:

```sh
export GS3D_HOST=ubuntu@<ip>   # or a host alias from ~/.ssh/config
make gs3d-push      # compute/gs3d and data/gs3d to ~/av-gs3d on the machine
make gs3d-setup     # clones the trainer, builds its CUDA extensions in a uv venv, checks torch sees the GPU
```

Then train, in the background on the machine. Runs go one after the other,
since one run takes the whole GPU; a train call with several exports queues
them:

```sh
make gs3d-train EXPORT=scene-0061_kf_m1                             # keyframes, masked, with the depth prior
make gs3d-train EXPORT=scene-0061_kf_m1 GS3D_TRAIN_ARGS=--no-depth   # the same without the prior
make gs3d-train EXPORT="scene-0061_sweeps_m1 scene-0103_kf_m1"      # a queue
make gs3d-log       # follow the run
make gs3d-pull      # results into data/cache/gs3d; restart the backend if it started before the directory existed
```

`compute/gs3d/train.py` drives the trainer's `train.py` for 30,000
iterations, with `-d depths` when the export has the prior, and `--data_device
cpu` for a sweeps export, whose images do not fit on the GPU next to the
model. Other trainer options pass through, e.g. `GS3D_TRAIN_ARGS="--eval
--antialiasing"`. When training ends it copies the PLY next to a JSON of
stats (Gaussian count, PSNR from the trainer's log, GPU, time) and the
per-keyframe ego poses, named `<scene token[:12]>_<kf|sweeps>_m<0|1>_d<0|1>`
so the backend can list a scene's variants. The PLY is a standard 3DGS file
that any splat viewer opens. `ssh $GS3D_HOST` and run `train.py` by hand
for anything else; `python gs3d/train.py --help` there lists the options.

The trainer's code is licensed for non-commercial research use only.

## Layout

- `cli.py` chooses scenes and tasks, loads each model once, and writes files
  through the cache classes in `backend/app`, so both sides name them the
  same way.
- `depth.py` runs Depth Anything V2. The fit to lidar and the error metrics
  live in `backend/app/depth.py`, since the viewer computes them per request
  from the cached prediction.
- `fusion.py` integrates each keyframe's camera views into an Open3D TSDF
  volume and extracts the mesh.
- `splat_export.py` runs Depth Anything 3 on six or eighteen views and writes
  a 3DGS PLY in the ego frame. Two DA3 behaviours are worked around and
  explained in its comments: the pose-based depth rescale that is
  ill-conditioned for co-located cameras, and Gaussian positions that
  disagree with the depth map.
- `depth_anything_v2/` is the vendored model code (Apache 2.0).
- `gs3d/export.py` writes a scene in the COLMAP layout for the official 3DGS
  trainer; `gs3d/setup_remote.sh` and `gs3d/train.py` run on the CUDA machine
  and need nothing from this environment.
