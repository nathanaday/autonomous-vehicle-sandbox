# Wishlist

Ideas we have discussed and not built. Ordered roughly by how cheap they are.

## Gaussian splat view from a feed-forward model

Add a fourth view that renders a Gaussian splat of one keyframe, produced
without per-scene training.

- Run a feed-forward reconstruction model on the six camera images of one
  keyframe, or on a short run of sweeps from one camera. Candidates: Depth
  Anything 3 (same family as our depth model, has a splat output in some
  variants), VGGT, AnySplat, MASt3R. Check what each currently supports and
  whether it accepts known intrinsics and poses, since nuScenes provides both.
- Export the result as a splat `.ply` and serve it from the backend like the
  fusion meshes.
- Render it in the browser with an existing Three.js Gaussian splat renderer,
  reusing the orbit controls and ego frame conventions from
  `composables/useThreeScene.ts`.
- Compare against the volumetric fusion mesh of the same keyframe.
- If the results justify a GPU, fit one day scene and one night scene with a
  driving-specific splatting codebase (Street Gaussians, OmniRe) on a rented
  CUDA machine, using the 12 Hz sweeps and the annotation boxes for moving
  objects, and load those splats in the same view.

## Smaller items

- Expose the 12 Hz sweeps between keyframes, at least for lidar, so playback
  can run at sensor rate.
- Crop the map raster around each scene and draw the ego path on it.
- Hover a 3D annotation box to see its category, attributes and point counts.
- Automated tests for the geometry: projection of a known lidar point into a
  camera, box corner ordering, radar velocity rotation.
- Per-category depth error in the depth view, using the lidar points inside
  each annotation box.
