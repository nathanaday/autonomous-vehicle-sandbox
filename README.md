# nuScenes sandbox

A viewer for the nuScenes `v1.0-mini` split. Pick one of the ten scenes, step
through its keyframes, and see every sensor at once: the six cameras, the
lidar sweep, the five radars, the annotated 3D boxes, and the path the car
drove. The point of the tool is to make the shape of the data obvious before
choosing a project direction. See `depth-anything-av-application.md` for the
research context.

![Night scene after rain](docs/screenshot.jpg)

## Layout

- **Scene rail.** The ten scenes, tagged `night` and `rain` from their
  descriptions, with keyframe count, duration, and number of annotated
  objects.
- **Camera grid.** The six cameras in their physical arrangement, front row
  and back row. Radar returns and annotation boxes project into each image.
  Click any camera to open it full size with a lidar depth overlay.
- **3D view.** Lidar points colored by height, intensity, or distance. Radar
  returns as amber points with velocity streaks. Annotation boxes colored by
  category. Sensor mounts, camera frustums, range rings, and the ego path
  through the scene. Drag to orbit, right-drag to pan, scroll to zoom.
- **Inspector.** Ego speed and pose, per-sensor counts, object counts by
  category, and layer toggles.
- **Timeline.** One bar per keyframe, taller when more objects are annotated.
  Space plays at 2 keyframes per second, the rate they were recorded. Arrow
  keys step.

The URL hash tracks the view, so `#scene-1094/20/CAM_FRONT` opens scene 1094 at
keyframe 20 with the front camera enlarged.

## Setup

Requires Python 3.12 or newer with [uv](https://docs.astral.sh/uv/), and Node
20 or newer.

1. Download `v1.0-mini.tar` from <https://www.nuscenes.org/nuscenes#download>
   and put it at `nuscenes/v1.0-mini.tar`.
2. Extract it:

   ```sh
   mkdir -p nuscenes/data && tar xf nuscenes/v1.0-mini.tar -C nuscenes/data
   ```

3. Install dependencies:

   ```sh
   make setup
   ```

Set `NUSCENES_DATAROOT` if the extracted split lives somewhere other than
`nuscenes/data`.

## Run

Development, with hot reload on both sides. Two terminals:

```sh
make backend    # FastAPI on http://localhost:8000
make frontend   # Vite on http://localhost:5173, proxies /api to the backend
```

Demo, one process:

```sh
make demo       # builds the UI, then serves it and the API on http://localhost:8000
```

## How it fits together

`backend/app/nuscenes.py` reads the JSON tables directly and does the
geometry. It does not depend on the nuScenes devkit. For each keyframe it
puts every sensor into one frame, the ego vehicle frame at the lidar
timestamp, so the frontend never has to compose transforms:

- Lidar and radar points come back as flat `Float32Array` binaries already in
  that frame. Radar is filtered the way the devkit filters it by default
  (`invalid_state == 0`, `ambig_state == 3`); the inspector shows raw and
  filtered counts side by side.
- Each camera comes with its intrinsics and a `ref_to_cam` matrix that
  accounts for the ego motion between the lidar sweep and the camera exposure.
  The browser projects points into images with those.
- Annotation boxes and the scene trajectory are expressed in the same frame.

`backend/app/main.py` exposes this as JSON and binary endpoints under `/api`,
resizes camera images on request, and serves `frontend/dist` when it exists.

`frontend/src` is Vue 3 with a small reactive store in `state.ts`. The 3D
view is Three.js with the ego frame used directly as world coordinates, z up.
Camera overlays are drawn on a 2D canvas over each image.

## What the mini split contains

| | |
|---|---|
| Scenes | 10, about 20 s each, 39 to 41 keyframes at 2 Hz |
| Locations | Boston Seaport, Singapore One North, Queenstown, Holland Village |
| Conditions | 3 night scenes, 1 tagged after rain, the rest clear daytime |
| Cameras | 6 at 1600×900, 12 Hz, about 65° horizontal fov each, 89° for the back camera |
| Lidar | 1 at 20 Hz, 32 beams, about 35 000 points per sweep |
| Radar | 5 at 13 Hz, about 125 raw returns each, 20 to 80 after filtering |
| Annotations | 3D boxes at every keyframe, 23 categories, with per-box lidar and radar point counts |

Only keyframes are shown. The `sweeps/` folder holds the intermediate
frames at full sensor rate; the API does not expose them yet.
