# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A sandbox for a master's-level deep learning course project. It is not the final
project. Its purpose is to load real driving scenes from nuScenes, look at them,
and build enough hands-on familiarity with the data to choose a direction.

Treat it as a workbench. Prefer code that is easy to throw away and rewrite over
code that is general.

## Research context

`depth-anything-av-application.md` holds the motivation. Read it before making
design decisions. The short version:

Camera-only depth estimation degrades in rain, fog, and snow. Radar keeps
working in weather but returns only a few hundred sparse points per frame. Two
project directions follow from that, and both are still open:

- **Stub 1 — fine tuning.** Add synthetic weather to clear-weather frames, then
  train Depth Anything so its output on the corrupted frame matches its output
  on the clean one. The clean frame is the label, so no hand annotation.
- **Stub 2 — sensor fusion.** Train a small model that takes a dense camera
  depth map plus sparse radar points and outputs a corrected depth map.

Do not write code that assumes one stub over the other. The choice comes after
seeing the data.

## Immediate goal

Load nuScenes scenes and visualize them. Camera frames, radar returns projected
into the image, ego pose over time, and the scene-level weather and time-of-day
tags. Seeing how sparse the radar really is, and how the weather-tagged scenes
actually look, is the point of the exercise.

Start from the `v1.0-mini` split (~4 GB) so the whole loop runs locally.

## Architecture

Two halves. The compute side runs the models offline and writes results into
`data/cache`; the viewer reads the dataset and those results and runs no
model. A team member who only wants to look at results needs the viewer and
the data bundles, not torch or the checkpoints.

- **Compute — Python, `compute/`.** Its own uv environment (torch, Open3D,
  Depth Anything 3, which pins numpy<2). `cli.py <depth|fusion|splat|all>
  --scene NAME` fills the cache for a scene, skipping what exists. It imports
  the loader and the cache classes from `backend/app`, so both sides name
  files the same way. See `compute/README.md`.
  The trained-splat task is the exception: `compute/gs3d/export.py` writes a
  scene in COLMAP layout using the viewer's environment, and
  `compute/gs3d/train.py` runs the official 3DGS trainer on a CUDA machine
  (`make gs3d-push`, `gs3d-setup`, `gs3d-train`, `gs3d-pull` with
  `GS3D_HOST`); nothing here has a CUDA build.
- **Backend — Python, `backend/`.** FastAPI, numpy and Pillow only. Owns the
  nuScenes loading, calibration and geometry, and serves the caches. A scene
  without results answers 404 with the compute command in the detail.
- **Frontend — Vue 3 + Vite + TypeScript.** Owns the viewer. Runs against the
  backend with the Vite dev server during development, and builds to static
  files the backend can serve for a single-process demo.

Keep both serving modes working. Losing the dev server costs fast iteration on
the UI; losing the built mode costs the ability to hand someone one command.
Keep the viewer free of model dependencies: anything that runs a model goes
in `compute/`.

## Current state

The viewer works end to end. See `README.md` for the layout and the data
summary.

- `backend/app/nuscenes.py` reads the JSON tables and does all geometry. Every
  keyframe is expressed in the ego frame at the lidar timestamp. No devkit.
  It shows only the scenes whose keyframe files are on disk, since the data
  bundles carry three of the ten.
- `backend/app/main.py` is the FastAPI app. JSON for scenes and frames, binary
  `Float32Array` for lidar and radar, resized JPEGs for cameras. `/api/features`
  says which caches have results. Serves `frontend/dist` at `/` when it exists.
- `backend/app/depth.py` reads Depth Anything V2 predictions from
  `data/cache/depth`, fits each image to the lidar with a scale and shift, and
  reports AbsRel, RMSE, δ1. `compute/depth.py` writes the predictions.
- `backend/app/fusion.py` and `backend/app/splat.py` name and read the fused
  meshes (`data/cache/fusion`) and the Gaussian splats (`data/cache/splat`).
  `compute/fusion.py` builds the meshes with Open3D's TSDF volume from camera
  depth or lidar, masking moving objects. `compute/splat_export.py` runs Depth
  Anything 3; two DA3 quirks are worked around there and explained in its
  comments: the API's pose-based depth rescale, and the Gaussian head's
  positions.
- `backend/app/gs3d.py` names and reads the trained splats (`data/cache/gs3d`),
  one per scene and option set, in the scene frame like the fused meshes.
  The key is `<scene token[:12]>_<kf|sweeps>_m<0|1>_d<0|1>`; the backend
  lists whatever variants exist rather than a fixed option grid, since each
  is a training run on a rented GPU.
- `backend/app/occ3d.py` reads the Occ3D-nuScenes occupancy labels from
  `data/occ3d/gts/<scene>/<sample token>/labels.npz`, a download rather
  than a computation (the `occ3d` bundle, or the CVPR 2023 challenge's mini
  release). Grid 200x200x16 at 0.4 m in the ego frame, 18 classes with 17
  free, two visibility masks. The x and y axes match the ego frame; the
  labelled road is about 0.8 m below the lidar's road returns, which the
  view reports and lets the user lift by hand rather than correcting.
- `frontend/src` is Vue 3 + Three.js. `state.ts` holds the store and the URL
  hash sync. `overlay.ts` draws projected points and boxes onto camera images.
  Six views, `explore`, `depth`, `fusion`, `splat`, `gs3d` and `occ3d`, share
  `composables/useThreeScene.ts`; only one is mounted at a time. Splats render
  through `@sparkjsdev/spark`, which needs three >= 0.180. Views whose feature
  has no results are locked with the fetch command; a scene or setting
  without results shows the compute command.
- The nuScenes ego frame origin is at road level, not at axle height. Ground
  is z = 0; the lidar sweeps put it between -0.4 and 0 m.

Only keyframes are exposed in the viewer. Sweeps are read only by the `gs3d`
export; map rasters are not wired up. No training code for either stub
exists yet; the 3DGS trainer reconstructs scenes, it does not train a depth
model. The depth view is the stock baseline both stubs compare against.
`todo.md` holds the wishlist.

## Commands

Everything large lives in `data/` (gitignored). `data.manifest` lists the
bundles that `scripts/sync_data.sh` fetches from GitHub releases, each with
three scenes (0061, 0103, 1094): `dataset` (`data/nuscenes`, keyframes only,
required), `depth`, `fusion`, `splat` and `gs3d` (`data/cache/<feature>`),
and `occ3d` (`data/occ3d`, the Occ3D labels).
The local copy also has the 12 Hz sweeps, which only the `gs3d` export uses.
Checkpoints go to `data/models` and are fetched by `scripts/fetch_models.sh`
for the compute side only. `make data-bundle TAG=… BUNDLES=… SCENES=…`
rebuilds bundles from a local `data/` through `scripts/list_files.py`.

- `make setup` installs the viewer's Python deps with uv and npm deps.
- `make data`, `make data-depth`, `make data-fusion`, `make data-splat`,
  `make data-gs3d`, `make data-occ3d`, `make data-all` fetch the bundles.
- `make backend` and `make frontend` run the two dev servers. Open
  http://localhost:5173.
- `make demo` builds the UI and serves everything from http://localhost:8000.
- `make compute-setup` installs the compute environment and both checkpoints.
  `make compute SCENES="scene-0061" TASK=all` fills the cache for a scene:
  about a minute for depth, four for the twelve fusion meshes, three and a
  half for the splats on an Apple GPU.
- `make gs3d-export SCENES=…` exports a scene for the 3DGS trainer in about
  half a minute (two and a half with `GS3D_ARGS=--sweeps`); the `gs3d-*`
  targets with `GS3D_HOST=user@host` run it on a CUDA machine. See
  `compute/README.md`.
- `make check` type-checks the frontend. There are no automated tests yet.

Take screenshots with puppeteer-core driving the installed Chrome when the
browser extension is not connected. Chrome's own `--screenshot` flag hangs on
this app. A helper that loads a URL, clicks buttons by their text, waits, and
saves a PNG while reporting console errors is about 30 lines; keep it in the
scratchpad, not the repo.
