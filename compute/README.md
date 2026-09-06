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
`FUSION_CACHE`, `SPLAT_CACHE`, `DEPTH_ANYTHING_CHECKPOINT` and
`DA3_MODEL_DIR` override them.

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
