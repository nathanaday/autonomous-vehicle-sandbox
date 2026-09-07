# NuScenes + 3D Perception Project Stubs

## Lessons from NuScenes data - 3D world construction

Since I have been messing around with the NuScenes data for a couple days, I am starting to learn the task of building a reliable 3D scene from the available data is quite difficult. I have tried 4 approaches to create a usable world geometry from the Lidar and vision data, and none of them are exceptional yet.

Approach 1 - Using only the Lidar points alone gives a sparse representation of the scene - while it may be sufficient to avoid collisions and navigate, it is not enough for real spatial awareness and context.

Approach 2 - Adding the depth anything results improves the scene construction by a substantial margin, but only for each camera perspective. Once you start to explore the scene from new perspectives, you run into sparse and missing areas, distortions, etc. Which all makes sense given the pipeline, where depth can only be inferred with respect to the camera origin.

Appraoch 3 - Fusing the depth anything map geometrically (Fused mesh view) does not produce usable results.

Approach 4 - Finally, I expected that using Gaussian spalting, both a basic single-shot from DA3 and a trained splat based on [the original implementation](https://github.com/graphdeco-inria/gaussian-splatting), would produce drastically better results. But since the vehicle only samples each part of a scene in passing, there are not really enough samples to construct a complete world and the results are almost worse than Approach 2. 

## Open Questions

- NuScenes visual data frame rate? 


## Potential Interest Areas

- Sensor fusion: multiple modalities on vehicle + satelitte
- Single shot, realtime occupancy grid
- Detecting anomalies in the occupancy grid from frame to frame



---

## Stub 1 — (Fine Tuning) Teach the depth model to ignore weather

**Idea.** Take driving footage recorded in clear weather. Add rain and fog to
the images ourselves, using a physical model so the added weather behaves the
way real weather does. We now have matched pairs: the same scene, clean and
corrupted, with the clean version acting as the answer key.

Fine-tune Depth Anything so its output on the corrupted image matches its
output on the clean one. The model learns to look past the weather instead of
reacting to it.

**Why it works as a project.** The answer key is free. We never have to label
anything by hand, and we can generate as much training data as we want by
turning the weather up and down.

**Baseline.** Stock Depth Anything, unmodified.

**Result to show.** Depth error against real weather footage, ours versus
stock, plotted as the weather gets worse.

**Main risk.** Weather we add by hand may not resemble the real thing closely
enough for the training to transfer. Test on real rainy sequences, not only on
our own synthetic ones.

---

## Stub 2 — (Sensor Fusion) Let sat + radar correct the depth model

**Idea.** Radar sees through rain, fog, and snow, but it only returns a few
hundred scattered points per frame with no sense of height. It cannot replace
the camera. It can, however, tell us where the camera's depth estimate has
drifted.

Train a small model that takes the camera's dense depth map plus the sparse
radar points and outputs a corrected depth map. The camera supplies detail and
structure; the radar anchors the distances.

Bonus: use the satellite extension to better correct the 3D occupancy scene
> https://huggingface.co/datasets/chenchen235/Occ3D_nuScenes_SatExt

**Why it works as a project.** Other groups have published on this, so we have
real numbers to measure ourselves against rather than only our own baseline.
The radar points come with the public driving datasets already.

**Baseline.** Depth Anything alone, with no radar.

**Result to show.** Depth error split by weather condition — clear, rain,
night — so we can point at where the radar helps most.

**Main risk.** The radar points are sparse and noisy, and many of them come off
moving vehicles rather than fixed structures. Cleaning them up may turn into
more work than the model itself.

---

## Stub 3 - Filling in 3D Semantic Occupancy From Sparse Data

> Based on:
> https://arxiv.org/html/2403.08748v3



---


## The original project (@KQ)

**Very brief summary.** Throw away the frames of a rainy drive that the rain
ruined. Use the frames that survive to build a 3D model of that street, then
treat that model like a video game level — drive a virtual car through it, add
fake fog and glare, and find out at what point a standard object detector stops
seeing pedestrians.

**Step by step.**

1. Load a recorded drive — camera video, radar, and the car's position over
   time — from a public dataset. Work out where each radar point falls inside
   the camera picture.
2. Run the video through Depth Anything frame by frame. A parked car should
   stay the same distance away from one frame to the next; in rain it won't.
   Measure how much the estimate jumps.
3. Wherever it jumps, check the radar for that spot, since radar sees through
   rain. If the camera and the radar disagree, call the frame ruined and delete
   it. Keep roughly the best one frame in seven.
4. Hand the surviving frames to an existing 3D reconstruction tool. With the
   ruined frames gone, the result should be a solid model of the street rather
   than one with rain baked into it as permanent fake geometry.
5. Use that 3D street as a test track. Point a virtual camera anywhere in it,
   including places the real car never drove. Paint fog, snow, or low sun into
   the rendered picture, feed the result to an object detector, and record how
   thick the fog has to get before it misses a person.

**What is borrowed and what is ours.** The depth model, the 3D reconstruction
tool, and the object detector are all released software used as-is. What the
team would write is the discard rule in step 3 and the fog-painting in step 5.

**The motivation is sound.** Self-driving companies want to test software
against situations that are rare or dangerous to record, so building simulators
out of recorded drives is an active area. Rain does wreck those
reconstructions, and filtering the bad frames first is a reasonable thing to
try.

**Two caveats.** First, steps 1–3 and steps 4–5 barely need each other. The
simulator could be built from any clear-weather drive with no filter at all,
and the filter could be evaluated by reconstruction quality with no simulator
at all. Two project ideas are sitting side by side, joined by one sentence.
Second, nothing here gets trained. Written plainly, the machine learning
content is one threshold picked by hand, while the scope runs to two semesters.

**What the stubs above keep.** The useful part of this idea is using radar to
check the camera, because radar is the one sensor that still works in weather.
Stubs 1 and 2 keep that and turn it into something a model learns, instead of a
rule the team tunes by hand.
