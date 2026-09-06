# Wishlist

Ideas we have discussed and not built. Ordered roughly by how cheap they are.

## Gaussian splat view, done

Built as the fourth view with Depth Anything 3 (nested Giant + metric Large)
and the Spark renderer. Left over from that work:

- Per-scene splat fitting on a CUDA machine (Street Gaussians, OmniRe) using the
  12 Hz sweeps and the annotation boxes, then load those splats in the same
  view next to the feed-forward one.
- A Gaussian size slider in the viewer. Today the size multiplier is a build
  option (`--scale-mult`, default 0.7).
- Write splats as SuperSplat's compressed PLY, which Spark reads, to cut the
  splat bundle about fourfold.
- Splats of several keyframes stitched along the trajectory, with moving
  objects masked, as a splat counterpart to the fused mesh.
- Try DA3's sky mask and confidence to prune more aggressively, and try the
  higher processing resolution the model supports.

## Smaller items

- Expose the 12 Hz sweeps between keyframes, at least for lidar, so playback
  can run at sensor rate.
- Crop the map raster around each scene and draw the ego path on it.
- Hover a 3D annotation box to see its category, attributes and point counts.
- Automated tests for the geometry: projection of a known lidar point into a
  camera, box corner ordering, radar velocity rotation.
- Per-category depth error in the depth view, using the lidar points inside
  each annotation box.
