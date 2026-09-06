# nuScenes sandbox

This is a data viewer for the nuScenes `v1.0-mini` split. My goal was to create a platform to explore the nuScenes data set, and visualze a few post-processing layers one may want to explore: DepthAnything, Scene Fusion, and Gaussian Splatting.

---

# Repository Components

### (1/2) Data Viewer Environment

![Night scene after rain](docs/screenshot.jpg)

> All precomputed data is available in the `releases` section and can be downloaded with the provided `make` files. 

This is all you need to get started!

The viewer stack, `backend/` and `frontend/`, reads the dataset and precomputed results. Therefore, no models or heavy computations on device are required. 

### (2/2) Data Computation Environment

This part is optional. If you want to run new computations (depth, gaussians, etc.), you can download the corresponding models and use the `compute/` environment.

---

## Quick Start

### Requirements

>[!NOTE]
> 
> - Python 3.12
> - [uv Python environment](https://docs.astral.sh/uv/)
> - Node 20 (or newer)
> - ~1GB Disc Space


### From Repository Source

```sh
git clone https://github.com/nathanaday/autonomous-vehicle-sandbox.git
cd autonomous-vehicle-sandbox
```

### Provided `make` instructions

```sh
make setup 
```

> `setup` uses `uv`, creates `backend/.venv` and installs Python deps; `npm` installs frontend deps


```sh
make data
```

> Downloads the `NuScenes` data from the repo's releases page

```sh
make backend
```

> Starts the backend server (`FastAPI`)

```sh
make frontend
```

> Starts the frontend server (`vite` dev server) 
> <http://localhost:5173>. 

```sh
make data-depth    # Depth Anything predictions: Depth Anything view
make data-fusion   # fused meshes: Fused mesh view
make data-splat    # Gaussian splats: Gaussian splat view
```

> Downloads the precomputed results that unlock the other three views (depth, fusion, splat, respectively) - note you can run any or all of these depending on what you want to see

```sh
make demo
```

> For a single process instead of two, `make demo` builds the UI and serves it with the API on <http://localhost:8000>.

---

# Provided Views

## Depth Anything view

![Depth view, night scene, top-down by camera](docs/depth-view.jpg)

The second view shows stock Depth Anything V2 (ViT-B, no fine tuning) run on all six cameras and puts the result next to the lidar. 

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

The predictions come precomputed in the `depth` bundle (see Data) or from
`compute/cli.py depth`, under `data/cache/depth`. The fit to lidar and the
error numbers are computed by the backend per request from the cached
prediction, so they need no model.

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

Each combination of scene, source, voxel size and masking is a separate
mesh, decimated to 700 000 triangles, about 30 MB as PLY under
`data/cache/fusion`. The `fusion` bundle carries all twelve combinations for
each of its scenes; `compute/cli.py fusion` makes them, about 25 seconds
each. A combination missing from the cache shows the command that computes
it.

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

Splats come precomputed in the `splat` bundle, as 40 MB 3DGS PLY files under
`data/cache/splat` that any 3DGS viewer can open, one per keyframe for the
six-view calibrated setting. The viewer never runs the model: a keyframe
without a splat shows the command that computes it, and playback shows each
keyframe's splat from the cache. `compute/cli.py splat` computes a scene in
about three and a half minutes on an Apple GPU, and its `--views 18` and
`--unposed` options fill the other settings the panel offers. The Depth
Anything 3 checkpoint is CC BY-NC 4.0; the vendored Depth Anything V2 code and
the DA3 code installed by pip are Apache 2.0.

---

Details on the data bundles and how the pieces fit together are in [DETAILS.md](DETAILS.md).
