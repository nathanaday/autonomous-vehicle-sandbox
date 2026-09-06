<script setup lang="ts">
import { computed } from 'vue'
import type { FusionSource } from '../api'
import { fusionLayers, fusionStatus, type FusionShading } from '../state'

const s = computed(() => (fusionStatus.value?.state === 'ready' ? fusionStatus.value : null))

const sources: { id: FusionSource; label: string; hint: string }[] = [
  { id: 'camera', label: 'Camera depth', hint: 'Depth Anything output, made metric with the per-image fit to lidar. Dense, and only as right as that fit.' },
  { id: 'lidar', label: 'Lidar', hint: 'The lidar sweep projected into each camera and filled in between beams by nearest neighbour. Sparse but measured.' },
]
const voxels = [0.15, 0.2, 0.3]
const shadings: { id: FusionShading; label: string }[] = [
  { id: 'photo', label: 'Photo' },
  { id: 'lit', label: 'Lit' },
  { id: 'normals', label: 'Normals' },
]

function extent(): string {
  if (!s.value?.bounds_min || !s.value?.bounds_max) return ''
  const d = s.value.bounds_max.map((v, i) => v - s.value!.bounds_min![i])
  return `${d[0].toFixed(0)} × ${d[1].toFixed(0)} × ${d[2].toFixed(0)} m`
}
</script>

<template>
  <aside class="inspector">
    <section>
      <h2>Method</h2>
      <p class="lead">Every keyframe's six depth images are cast into a signed distance volume using the recorded ego poses, then marching cubes extracts the surface.</p>
      <p class="note muted">Objects that move more than a metre during the scene are masked out before integration, so driving cars and walking people leave no smear, while parked cars stay. Colors come from the photos. The result is one mesh for the whole scene, in the frame of its first keyframe.</p>
    </section>

    <section>
      <h2>Depth source</h2>
      <div class="seg">
        <button v-for="o in sources" :key="o.id" :class="{ on: fusionLayers.source === o.id }" @click="fusionLayers.source = o.id">{{ o.label }}</button>
      </div>
      <p class="note muted">{{ sources.find((o) => o.id === fusionLayers.source)?.hint }}</p>
      <div class="row">
        <span class="muted">Voxel size</span>
        <div class="seg">
          <button v-for="v in voxels" :key="v" :class="{ on: fusionLayers.voxel === v }" @click="fusionLayers.voxel = v">{{ v }} m</button>
        </div>
      </div>
      <button class="toggle" :class="{ on: fusionLayers.maskMoving }" @click="fusionLayers.maskMoving = !fusionLayers.maskMoving"><span>Mask moving objects</span><span class="knob"></span></button>
      <p class="note muted">Each combination is a separate mesh, computed offline by the compute CLI and read from data/cache/fusion.</p>
    </section>

    <section v-if="s">
      <h2>This mesh</h2>
      <dl class="kv num">
        <dt>Triangles</dt>
        <dd>{{ (s.triangles ?? 0).toLocaleString() }} <span class="muted">of {{ (s.raw_triangles ?? 0).toLocaleString() }} before decimation</span></dd>
        <dt>Vertices</dt>
        <dd>{{ (s.vertices ?? 0).toLocaleString() }}</dd>
        <dt>Views fused</dt>
        <dd>{{ s.views }} <span class="muted">over {{ s.keyframes }} keyframes</span></dd>
        <dt>Masked</dt>
        <dd>{{ s.moving_instances }} <span class="muted">moving objects</span></dd>
        <dt>Extent</dt>
        <dd>{{ extent() }}</dd>
        <dt>Build time</dt>
        <dd>{{ s.seconds }} s</dd>
      </dl>
    </section>

    <section>
      <h2>Display</h2>
      <div class="row">
        <span class="muted">Shading</span>
        <div class="seg">
          <button v-for="o in shadings" :key="o.id" :class="{ on: fusionLayers.shading === o.id }" @click="fusionLayers.shading = o.id">{{ o.label }}</button>
        </div>
      </div>
      <button class="toggle" :class="{ on: fusionLayers.wireframe }" @click="fusionLayers.wireframe = !fusionLayers.wireframe"><span>Wireframe</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: fusionLayers.lidarOverlay }" @click="fusionLayers.lidarOverlay = !fusionLayers.lidarOverlay"><span>Lidar sweep of the current keyframe</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: fusionLayers.path }" @click="fusionLayers.path = !fusionLayers.path"><span>Ego path</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: fusionLayers.followEgo }" @click="fusionLayers.followEgo = !fusionLayers.followEgo"><span>Camera follows the ego car</span><span class="knob"></span></button>
      <p class="note muted">Step keyframes with the arrow keys to drive the car through the mesh. The lidar overlay shows how the fused surface lines up with a single live sweep.</p>
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
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 0 2px;
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
.seg {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  margin: 2px 0 6px;
  background: var(--ground);
  border-radius: var(--radius);
}
.seg button {
  padding: 3px 9px;
  border-radius: 4px;
  color: var(--muted);
  font-size: 12px;
}
.seg button.on {
  color: var(--text);
  background: var(--line-strong);
}
</style>
