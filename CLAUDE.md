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

A full-stack visual application, split so the data work stays in Python and the
viewing stays in the browser.

- **Backend — Python.** Owns everything that touches the dataset: nuScenes
  loading, sensor calibration, radar-to-image projection, and later any model
  inference. Serves the scene data over HTTP.
- **Frontend — Vue 3 + Vite + TypeScript.** Owns the viewer. Runs against the
  backend with the Vite dev server during development, and builds to static
  files the backend can serve for a single-process demo.

Keep both serving modes working. Losing the dev server costs fast iteration on
the UI; losing the built mode costs the ability to hand someone one command.

## Current state

The viewer works end to end on `v1.0-mini`. See `README.md` for the layout and
the data summary.

- `backend/app/nuscenes.py` reads the JSON tables and does all geometry. Every
  keyframe is expressed in the ego frame at the lidar timestamp. No devkit.
- `backend/app/main.py` is the FastAPI app. JSON for scenes and frames, binary
  `Float32Array` for lidar and radar, resized JPEGs for cameras. Serves
  `frontend/dist` at `/` when it exists.
- `backend/app/depth.py` runs stock Depth Anything V2 (vendored model code in
  `backend/app/depth_anything_v2`, checkpoint in `data/models/`),
  caches predictions under `data/cache/depth`, fits each image to the
  lidar with a scale and shift, and reports AbsRel, RMSE, δ1.
- `backend/app/fusion.py` fuses a scene into one mesh with Open3D's TSDF
  volume from either camera depth or lidar, masks moving objects, and caches
  PLY files under `data/cache/fusion` (not in the data bundle).
- `tools/da3/` is a separate uv environment running Depth Anything 3 (pins
  numpy<2, so it cannot share the backend env). `splat_export.py` takes a list
  of keyframes, loads the model once, and writes a 3DGS PLY per keyframe;
  `backend/app/splat.py` runs it as a subprocess, one build at a time, and only
  when a build route is called. Reading a splat's status never starts a build:
  playback once started one exporter per keyframe, each loading the 6.8 GB
  model, and took the machine down. Checkpoint in `data/models/da3/`, outputs
  in `data/cache/splat/`. Two DA3 quirks are worked around in the exporter and
  explained in its comments: the API's pose-based depth rescale, and the
  Gaussian head's positions.
- `frontend/src` is Vue 3 + Three.js. `state.ts` holds the store and the URL
  hash sync. `overlay.ts` draws projected points and boxes onto camera images.
  Four views, `explore`, `depth`, `fusion` and `splat`, share
  `composables/useThreeScene.ts`; only one is mounted at a time. Splats render
  through `@sparkjsdev/spark`, which needs three >= 0.180.
- The nuScenes ego frame origin is at road level, not at axle height. Ground
  is z = 0; the lidar sweeps put it between -0.4 and 0 m.

Only keyframes are exposed. Sweeps and map rasters are not wired up. No
training code exists yet; the depth view is the stock baseline both stubs
compare against. `todo.md` holds the wishlist, including the Gaussian splat view.

## Commands

Everything large lives in `data/` (gitignored): `data/nuscenes` is the extracted
split, `data/models` the Depth Anything checkpoint, `data/cache` the computed
depth predictions. `make data` fetches all of it from the GitHub release listed
in `data.manifest`. `make data-bundle` rebuilds that bundle from a local `data/`.

- `make setup` installs Python deps with uv and npm deps.
- `make backend` and `make frontend` run the two dev servers. Open
  http://localhost:5173.
- `make demo` builds the UI and serves everything from http://localhost:8000.
- `make depth-cache` runs Depth Anything over every keyframe camera image and
  the per-scene summaries, about eight minutes on an Apple GPU.
- `make splat-setup` installs the Depth Anything 3 environment and downloads
  its 6.8 GB checkpoint. Only needed for the Gaussian splat view.
- `make check` type-checks the frontend. There are no automated tests yet.

Take screenshots with puppeteer-core driving the installed Chrome when the
browser extension is not connected. Chrome's own `--screenshot` flag hangs on
this app. A helper that loads a URL, clicks buttons by their text, waits, and
saves a PNG while reporting console errors is about 30 lines; keep it in the
scratchpad, not the repo.
