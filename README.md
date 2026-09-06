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

## Gaussian splat view

![Gaussian splat of one keyframe from Depth Anything 3](docs/splat-view.jpg)

The fourth view is a Gaussian splat of one keyframe from
[Depth Anything 3](https://github.com/ByteDance-Seed/Depth-Anything-3), with no
per-scene training. The nested 1.4B-parameter model takes the six photos and
returns, in one forward pass, a metric depth map, a sky mask, and one 3D
Gaussian per pixel. On the Apple GPU the pass takes about 5 seconds for six
views and 10 for twelve. The browser renders the result with
[Spark](https://sparkjs.dev/), a Gaussian splat renderer for Three.js.

- **Views.** The six cameras of the keyframe, or eighteen with the neighbouring
  keyframes. More views give the model more overlap and lower the depth error
  in every camera.
- **Cameras.** Calibrated poses and intrinsics condition the model, or the
  model estimates poses itself. The estimated result is anchored at the front
  left camera so the other five show how far the estimate drifts, and the
  inspector reports the rotation and position error per camera.
- **Depth against lidar, no fitting.** Unlike the Depth Anything view, the
  metric branch's scale is used as is. On scene 0061 that gives 13.5 percent
  AbsRel from six views and 10.1 from twelve, next to 12.4 for Depth Anything
  V2 with a per-image lidar fit.
- **Overlays.** The lidar sweep, the camera frustums, the range rings and ego
  car, all in the keyframe's ego frame.

Two implementation notes. The API's final step rescales metric depth by a
similarity fit between predicted and given camera centres; with six cameras a
metre apart that fit is ill-conditioned and halved the depth, so the exporter
skips it and keeps the metric branch's scale. And the Gaussian head's own
positions disagreed with its depth map by a factor of 1.4 to 2.5, so the
exporter keeps the model's rays, colors, opacities and shapes but places every
Gaussian on the metric depth map along calibrated rays.

The view needs the `splat` bundle, and building new splats needs the Depth
Anything 3 environment, which is separate because DA3 pins `numpy<2`:

```sh
make data-splat     # the checkpoint and cached splats, about 9 GB; enough to view them
make splat-setup    # the bundle plus its own uv environment under tools/da3, to build more
```

Splats are built on request, never by stepping or playing through keyframes.
The view offers to build the current keyframe or every keyframe the scene is
missing; a scene build loads the model once and then takes about 5 seconds per
keyframe on the Apple GPU, with progress in the panel and on the timeline. The
backend runs one build at a time and refuses a second one while it runs.
Results cache under `data/cache/splat` as 40 MB PLY files that any 3DGS viewer
can open, and once a scene is built, playback shows the splat of each keyframe
from the cache. Without the bundle the other views work and this one is
locked. The checkpoint is CC BY-NC 4.0; the vendored Depth Anything V2 code
and the DA3 code installed by pip are Apache 2.0.

## Setup

Requires Python 3.12 or newer with [uv](https://docs.astral.sh/uv/), and Node
20 or newer.

```sh
make setup      # Python deps with uv, npm deps
make data       # the nuScenes v1.0-mini dataset, 5 GB, unlocks the Sensors view
```

The other views need more data. Each is a separate download so a look at the
dataset costs 5 GB, not 20:

```sh
make data-depth   # Depth Anything V2 checkpoint and caches, about 1 GB: Depth Anything and Fused mesh views
make data-splat   # Depth Anything 3 checkpoint and cached splats, about 9 GB: Gaussian splat view
```

## Data

Everything large lives in `data/`, which git ignores, in three bundles. The
backend reports which are installed at `/api/bundles`, and the UI locks the
views whose bundle is missing and shows the command that fetches it.

| Bundle | Path | Contents | Size | Unlocks |
|---|---|---|---|---|
| `dataset` | `data/nuscenes/` | The extracted nuScenes `v1.0-mini` split | 5.1 GB | Sensors |
| `depth` | `data/models/depth-anything-v2/`, `data/cache/depth/`, `data/cache/fusion/` | `depth_anything_v2_vitb.pth`, Depth Anything output for every keyframe camera image with per-scene summaries, fused meshes | 1.0 GB | Depth Anything, Fused mesh |
| `splat` | `data/models/da3/`, `data/cache/splat/` | Depth Anything 3 checkpoint, splats of scenes 0061 and 0103 | 9.4 GB | Gaussian splat |

The `dataset` bundle is required; the backend refuses to start without it.
The fused mesh view can also build from lidar alone, but it lives behind the
`depth` bundle because its camera source and its cache come from Depth
Anything. New fusion meshes and splats build on request and grow the caches.

The bundles are split into parts under 2 GB on the repository's
[releases page](https://github.com/nathanaday/autonomous-vehicle-sandbox/releases).
`data.manifest` at the repository root records, for each bundle, the release
URL and a SHA-256 for every part and for the joined archive.

**Option 1, the script.** `make data`, `make data-depth` and `make data-splat`
run `scripts/sync_data.sh` for one bundle; `make data-all` fetches all three.
The script downloads the parts listed in `data.manifest`, verifies each
checksum, joins and verifies the archive, extracts it into `data/`, and checks
that the bundle's marker file exists. It resumes interrupted downloads and
skips a bundle that is already installed. It needs `curl` and `shasum` or
`sha256sum`, and free disk of about twice the bundle's size while it extracts.

**Option 2, by hand.** Download every `av-sandbox-<bundle>.tar.gz.part-*`
file from the release, then:

```sh
cat av-sandbox-dataset.tar.gz.part-* > av-sandbox-dataset.tar.gz
shasum -a 256 av-sandbox-dataset.tar.gz     # compare with the bundle line in data.manifest
mkdir -p data && tar -xzf av-sandbox-dataset.tar.gz -C data
```

**Option 3, from the sources.** Download `v1.0-mini.tar` from
<https://www.nuscenes.org/nuscenes#download> and extract it so that
`data/nuscenes/v1.0-mini/scene.json` exists. Download the Depth Anything V2
ViT-B checkpoint from its Hugging Face release into
`data/models/depth-anything-v2/`, then run `make depth-cache` to compute the
depth cache, about eight minutes on an Apple GPU. `scripts/fetch_da3.sh`
downloads the Depth Anything 3 checkpoint from Hugging Face; splats then build
from the view.

To publish a bundle after changing its part of `data/`, run `make data-bundle
TAG=data-v3 BUNDLES=splat`, upload the files it writes to `data/bundle/splat/`
to a release with that tag, and commit the updated `data.manifest`. Bundles
not rebuilt keep their lines and their release URL.

`NUSCENES_DATAROOT`, `DEPTH_ANYTHING_CHECKPOINT`, `DEPTH_CACHE`,
`FUSION_CACHE`, `SPLAT_CACHE` and `DA3_MODEL_DIR` override the locations.

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

`tools/da3/splat_export.py` runs Depth Anything 3 in its own environment on a
list of keyframes, loading the model once, and writes a 3DGS PLY per keyframe
in its ego frame; `backend/app/splat.py` launches it as a subprocess for one
build at a time, follows its progress file, and serves the results.

`frontend/src` is Vue 3 with a small reactive store in `state.ts`. The four
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
