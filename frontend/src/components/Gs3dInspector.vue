<script setup lang="ts">
import { computed } from 'vue'
import { gs3dLayers, gs3dVariant, sceneGs3d } from '../state'

const v = computed(() => gs3dVariant.value)
const variants = computed(() => sceneGs3d.value?.variants ?? [])

function minutes(s: number): string {
  return s >= 60 ? `${(s / 60).toFixed(0)} min` : `${s.toFixed(0)} s`
}
function psnr(p: Record<string, number>): string {
  const parts = Object.entries(p).map(([k, x]) => `${x.toFixed(1)} dB ${k}`)
  return parts.length ? parts.join(', ') : 'not recorded'
}
</script>

<template>
  <aside class="inspector">
    <section>
      <h2>Method</h2>
      <p class="lead">3D Gaussian Splatting as published: the scene starts as the coloured lidar points of every keyframe and is optimised for 30,000 iterations until its renders match the camera images.</p>
      <p class="note muted">Poses and intrinsics come from the dataset, so there is no structure-from-motion step. Objects that move during the scene are masked out of the images, and the Depth Anything prediction of each image can steer the geometry. The result is one splat for the whole scene, in the frame of its first keyframe; compare it with the Gaussian splat view, which is one Depth Anything 3 pass per keyframe with no training.</p>
    </section>

    <section v-if="variants.length > 1">
      <h2>Variant</h2>
      <div class="list">
        <button v-for="o in variants" :key="o.key" :class="{ on: v?.key === o.key }" @click="gs3dLayers.variant = o.key">{{ o.label }}</button>
      </div>
      <p class="note muted">Each variant is a separate training run, read from data/cache/gs3d.</p>
    </section>

    <section v-if="v">
      <h2>This splat</h2>
      <dl class="kv num">
        <dt>Gaussians</dt>
        <dd>{{ v.n_gaussians.toLocaleString() }} <span class="muted">from {{ v.n_points_init.toLocaleString() }} lidar points</span></dd>
        <dt>Images</dt>
        <dd>{{ v.n_images }} <span class="muted">{{ v.images === 'kf' ? 'keyframes' : `${v.n_keyframe_images} keyframes and ${v.n_images - v.n_keyframe_images} sweeps` }}</span></dd>
        <dt>Masked</dt>
        <dd>{{ v.moving_instances }} <span class="muted">moving objects in {{ v.n_masked_images }} images</span></dd>
        <dt>Depth prior</dt>
        <dd>{{ v.depth_prior ? 'Depth Anything V2, fitted to lidar' : 'none' }}</dd>
        <dt>Iterations</dt>
        <dd>{{ v.iterations.toLocaleString() }}<span v-if="v.eval_holdout" class="muted">, every 8th image held out</span></dd>
        <dt>PSNR</dt>
        <dd>{{ psnr(v.psnr) }}</dd>
        <dt>Training</dt>
        <dd>{{ minutes(v.seconds) }} <span class="muted" v-if="v.gpu">on {{ v.gpu }}</span></dd>
        <dt>File</dt>
        <dd>{{ (v.ply_bytes / 1e6).toFixed(0) }} MB</dd>
      </dl>
      <p class="note muted" v-if="v.trainer_args.length">Trainer options: {{ v.trainer_args.join(' ') }}</p>
    </section>

    <section>
      <h2>Display</h2>
      <button class="toggle" :class="{ on: gs3dLayers.lidar }" @click="gs3dLayers.lidar = !gs3dLayers.lidar"><span>Lidar sweep of the current keyframe</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: gs3dLayers.path }" @click="gs3dLayers.path = !gs3dLayers.path"><span>Ego path</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: gs3dLayers.followEgo }" @click="gs3dLayers.followEgo = !gs3dLayers.followEgo"><span>Camera follows the ego car</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: gs3dLayers.rings }" @click="gs3dLayers.rings = !gs3dLayers.rings"><span>Range rings at the scene origin</span><span class="knob"></span></button>
      <p class="note muted">Step keyframes with the arrow keys to drive the car through the splat. The Driver view looks down the road from the windshield, close to the training viewpoints, where a splat is at its best. From the Chase, Top and Side views, far from any training image, it shows streaks and floaters instead of surfaces. The lidar overlay shows how the trained surfaces line up with a live sweep.</p>
    </section>
  </aside>
</template>

<style scoped>
.inspector {
  overflow-y: auto;
  background: var(--panel);
  padding: 6px 16px 20px;
}
section {
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
}
section:last-child {
  border-bottom: 0;
}
h2 {
  margin: 0 0 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--muted);
}
.lead {
  margin: 0 0 6px;
}
.note {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.45;
}
.kv {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 3px 14px;
  margin: 0;
}
.kv dt {
  color: var(--muted);
}
.kv dd {
  margin: 0;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px;
  margin: 2px 0 6px;
  background: var(--ground);
  border-radius: var(--radius);
}
.list button {
  text-align: left;
  padding: 5px 9px;
  border-radius: 4px;
  color: var(--muted);
  font-size: 12px;
}
.list button.on {
  color: var(--text);
  background: var(--line-strong);
}
</style>
