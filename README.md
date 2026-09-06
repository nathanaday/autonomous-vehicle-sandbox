# nuScenes sandbox

A viewer for the nuScenes `v1.0-mini` split. Pick one of the ten scenes, step
through its keyframes, and see every sensor at once: the six cameras, the
lidar sweep, the five radars, the annotated 3D boxes, and the path the car
drove. The point of the tool is to make the shape of the data obvious before
choosing a project direction. See `depth-anything-av-application.md` for the
research context.

> [!NOTE]
> **Quickstart.** Needs Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), Node 20 or newer, and about 11 GB of free disk.
>
> ```sh
> git clone https://github.com/nathanaday/autonomous-vehicle-sandbox.git
> cd autonomous-vehicle-sandbox
> make setup       # uv creates backend/.venv and installs Python deps; npm installs frontend deps
> make data        # downloads the 4.6 GB data bundle from GitHub releases and extracts it into data/
> make backend     # terminal 1: FastAPI on http://localhost:8000
> make frontend    # terminal 2: Vite dev server on http://localhost:5173
> ```
>
> Open <http://localhost:5173>. For a single process instead of two, `make demo` builds the UI and serves it with the API on <http://localhost:8000>.

![Night scene after rain](docs/screenshot.jpg)

## Layout

- **Header.** The current scene's name, tags, location, date, and
  description. The Change scene button (or `s`) opens a picker with all ten
  scenes as thumbnail cards, tagged `night` and `rain` from their
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
keyframe 20 with the front camera enlarged, and `#depth/scene-1094/20` opens the
same keyframe in the depth view.

## Depth Anything view

![Depth view, night scene, top-down by camera](docs/depth-view.jpg)

The second view runs stock Depth Anything V2 (ViT-B, no fine tuning) on all
six cameras and puts the result next to the lidar. It is the baseline for
both project directions in `depth-anything-av-application.md`.

- **Camera tiles.** A wipe between photo and depth map, the depth map alone,
  or the lidar points drawn on the photo and colored by how far the model
  misses them: coral too close, blue too far.
- **3D view.** The six depth maps unprojected into the ego frame as one
  colored point cloud, over the lidar sweep. Color it by source camera and
  look from the top to see where neighbouring cameras disagree about scale.
- **Inspector.** AbsRel, RMSE, and δ1 against lidar for the keyframe and per
  camera, plus the whole-scene average.
- **Timeline and scene cards.** In this view the timeline bars show error per
  keyframe and every scene card shows its average error, so day and night
  scenes can be compared at a glance.

![Lidar error overlay](docs/depth-error-tiles.jpg)

The model outputs relative inverse depth, so before any comparison each image
gets its own scale and shift fitted by least squares to the lidar points that
project into it. Everything reported is measured after that fit. That is the
best case for the stock model, and the spread of fitted scales between cameras
of the same keyframe is one of the things a real system would have to resolve.

On the mini split the stock model lands at 9 to 16 percent AbsRel on the
daytime scenes and 20 to 22 percent on the three night scenes.

The checkpoint and the precomputed predictions ship in the data bundle (see
Data). Predictions for any image missing from the cache are computed on first
request and cached under `data/cache/depth`.

## Fused mesh view

![Fused mesh, camera depth, driving through scene 0061](docs/fusion-view.jpg)

The third view fuses a whole scene into one surface. Every keyframe's six
depth images are cast into a truncated signed distance volume with Open3D,
using the recorded ego poses, and marching cubes extracts the mesh. Colors
come from the photos.

- **Depth source.** Camera depth is the Depth Anything output made metric
  with the per-image fit to lidar: dense, and only as right as that fit.
  Lidar is the sweep projected into each camera and filled between beams by
  nearest neighbour: sparse but measured. Comparing the two meshes of the same
  scene shows what in-filling with camera depth buys and what it costs.
- **Moving objects.** Anything whose annotated position changes by more than
  a metre during the scene is masked out of the depth images before
  integration. Parked cars stay, driving cars and pedestrians leave no smear.
- **Driving through it.** The keyframe timeline moves the ego car along the
  mesh, with the current lidar sweep drawn over the fused surface so the
  alignment can be judged by eye. Shading can be photo colors, lit, or
  normals, with a wireframe toggle.

Each combination of scene, source, voxel size and masking is built once on
first request, about 25 seconds, decimated to 700 000 triangles, and cached
under `data/cache/fusion` as a 30 MB PLY. The fusion cache is not part of the
data bundle.

## Setup

Requires Python 3.12 or newer with [uv](https://docs.astral.sh/uv/), and Node
20 or newer.

```sh
make setup      # Python deps with uv, npm deps
make data       # 4.6 GB download from the GitHub release, 6 GB extracted into data/
```

## Data

Everything large lives in `data/`, which git ignores:

| Path | Contents | Size |
|---|---|---|
| `data/nuscenes/` | The extracted nuScenes `v1.0-mini` split | 5.1 GB |
| `data/models/depth-anything-v2/` | `depth_anything_v2_vitb.pth` | 372 MB |
| `data/cache/depth/` | Depth Anything output for every keyframe camera image, plus per-scene summaries | 559 MB |

All three are packaged as one bundle on the repository's
[releases page](https://github.com/nathanaday/autonomous-vehicle-sandbox/releases),
split into parts under 2 GB. `data.manifest` at the repository root records the
release URL and a SHA-256 for every part and for the joined archive.

**Option 1, the script.** `make data` runs `scripts/sync_data.sh`, which
downloads the parts listed in `data.manifest`, verifies each checksum, joins
and verifies the archive, extracts it into `data/`, and checks that the
expected folders exist. It resumes interrupted downloads and does nothing if
`data/` is already complete. It needs `curl` and `shasum` or `sha256sum`, and
about 11 GB of free disk while it runs.

**Option 2, by hand.** Download every `av-sandbox-data.tar.gz.part-*` file
from the release, then:

```sh
cat av-sandbox-data.tar.gz.part-* > av-sandbox-data.tar.gz
shasum -a 256 av-sandbox-data.tar.gz     # compare with the archive line in data.manifest
mkdir -p data && tar -xzf av-sandbox-data.tar.gz -C data
```

**Option 3, from the sources.** Download `v1.0-mini.tar` from
<https://www.nuscenes.org/nuscenes#download> and extract it so that
`data/nuscenes/v1.0-mini/scene.json` exists. Download the Depth Anything V2
ViT-B checkpoint from its Hugging Face release into
`data/models/depth-anything-v2/`. Then run `make depth-cache` to compute the
depth cache, about eight minutes on an Apple GPU. Without the checkpoint the
Sensors view still works and the Depth Anything view reports the missing file.

To publish a new bundle after changing `data/`, run `make data-bundle
TAG=data-v2`, upload the files it writes to `data/bundle/` to a release with
that tag, and commit the updated `data.manifest`.

`NUSCENES_DATAROOT`, `DEPTH_ANYTHING_CHECKPOINT` and `DEPTH_CACHE` override
the three locations.

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

`backend/app/depth.py` wraps the vendored Depth Anything V2 model code
(`backend/app/depth_anything_v2`, Apache 2.0), runs it on the Apple GPU when
available, caches predictions, fits each image to the lidar, and unprojects
the fitted depth into the ego frame.

`backend/app/fusion.py` builds the fused meshes in a background thread with
Open3D's scalable TSDF volume, masks moving objects using the annotation
boxes, and writes binary PLY plus a JSON sidecar with stats and per-keyframe
ego poses in the scene frame.

`frontend/src` is Vue 3 with a small reactive store in `state.ts`. The three
views share the Three.js scaffolding in `composables/useThreeScene.ts`, with
the ego frame used directly as world coordinates, z up. The nuScenes ego
origin is on the road surface. Only one view is mounted at a time so its
WebGL context is released before the next one starts. Camera overlays are
drawn on a 2D canvas over each image.

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
