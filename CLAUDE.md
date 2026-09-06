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
- `frontend/src` is Vue 3 + Three.js. `state.ts` holds the store and the URL
  hash sync. `overlay.ts` draws projected points and boxes onto camera images.

Only keyframes are exposed. Sweeps, map rasters, and any model inference are
not wired up yet.

## Commands

Dataset: extract `nuscenes/v1.0-mini.tar` into `nuscenes/data/` (gitignored).

- `make setup` installs Python deps with uv and npm deps.
- `make backend` and `make frontend` run the two dev servers. Open
  http://localhost:5173.
- `make demo` builds the UI and serves everything from http://localhost:8000.
- `make check` type-checks the frontend. There are no automated tests yet.

Take screenshots with headless Chrome when the browser extension is not
connected:

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --disable-gpu --use-angle=swiftshader --enable-unsafe-swiftshader \
  --hide-scrollbars --window-size=1600,1000 --virtual-time-budget=8000 \
  --screenshot=out.png "http://localhost:5173/#scene-1094/20"
```
