# Details

The data bundles and how the pieces fit together. The README covers setup and the views.

## Data

Everything large lives in `data/`, which git ignores. The dataset and the
results of each feature are separate bundles, and each holds three scenes:
0061 (Singapore, day), 0103 (Boston, day) and 1094 (Singapore, night). The
backend reports which features have results at `/api/features`, and the UI
locks the views whose feature has none and shows the command that fetches
them.

| Bundle | Path | Contents | Size | Unlocks |
|---|---|---|---|---|
| `dataset` | `data/nuscenes/` | The `v1.0-mini` tables and the keyframe files of the three scenes; no sweeps | 0.2 GB | Sensors |
| `depth` | `data/cache/depth/` | Depth Anything output for every keyframe camera image, with per-scene summaries | 0.1 GB | Depth Anything |
| `fusion` | `data/cache/fusion/` | Fused meshes, twelve per scene | 0.7 GB | Fused mesh |
| `splat` | `data/cache/splat/` | Gaussian splats, one per keyframe | 4.0 GB | Gaussian splat |

The `dataset` bundle is required; the backend refuses to start without it.
The tables list all ten scenes of the split, and the backend shows the ones
whose files are on disk, so a full `v1.0-mini` extracted into
`data/nuscenes/` works too and shows all ten. Model checkpoints are not in
any bundle; `scripts/fetch_models.sh` fetches them for the compute side.

The bundles are split into parts under 2 GB on the repository's
[releases page](https://github.com/nathanaday/autonomous-vehicle-sandbox/releases).
`data.manifest` at the repository root records, for each bundle, the release
URL and a SHA-256 for every part and for the joined archive.

**Option 1, the script.** `make data`, `make data-depth`, `make data-fusion`
and `make data-splat` run `scripts/sync_data.sh` for one bundle; `make
data-all` fetches all four. The script downloads the parts listed in
`data.manifest`, verifies each checksum, joins and verifies the archive,
extracts it into `data/`, and checks that the bundle's marker path exists. It
resumes interrupted downloads and skips a bundle that is already installed.
It needs `curl` and `shasum` or `sha256sum`, and free disk of about twice the
bundle's size while it extracts.

**Option 2, by hand.** Download every `av-sandbox-<bundle>.tar.gz.part-*`
file from the release, then:

```sh
cat av-sandbox-dataset.tar.gz.part-* > av-sandbox-dataset.tar.gz
shasum -a 256 av-sandbox-dataset.tar.gz     # compare with the bundle line in data.manifest
mkdir -p data && tar -xzf av-sandbox-dataset.tar.gz -C data
```

**Option 3, from the sources.** Download `v1.0-mini.tar` from
<https://www.nuscenes.org/nuscenes#download> and extract it so that
`data/nuscenes/v1.0-mini/scene.json` exists. Then compute the results with
the compute side, `compute/README.md`.

To publish a bundle after changing its part of `data/`, run `make data-bundle
TAG=data-v3 BUNDLES=splat`, upload the files it writes to `data/bundle/splat/`
to a release with that tag, and commit the updated `data.manifest`. Bundles
not rebuilt keep their lines and their release URL. `SCENES` chooses the
scenes.

`NUSCENES_DATAROOT`, `DEPTH_CACHE`, `FUSION_CACHE` and `SPLAT_CACHE` override
the locations for the backend and the compute CLI alike.



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

`compute/` holds everything that runs a model: `depth.py` for Depth Anything
V2, `fusion.py` for the TSDF mesh, `splat_export.py` for Depth Anything 3,
and `cli.py`, which fills the cache for named scenes and loads each model
once. It imports the loader and the cache classes from `backend/app`, so both
sides name files the same way. `backend/app/depth.py`, `fusion.py` and
`splat.py` only read the cache; the backend's environment has no torch.

`frontend/src` is Vue 3 with a small reactive store in `state.ts`. The four
views share the Three.js scaffolding in `composables/useThreeScene.ts`, with
the ego frame used directly as world coordinates, z up. The nuScenes ego
origin is on the road surface. Only one view is mounted at a time so its
WebGL context is released before the next one starts. Camera overlays are
drawn on a 2D canvas over each image.
