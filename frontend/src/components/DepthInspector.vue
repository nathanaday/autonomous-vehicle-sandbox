<script setup lang="ts">
import { computed } from 'vue'
import { CAMERA_TINTS } from '../geometry'
import { depth, depthLayers, depthScenes, state, type DepthCloudColor, type DepthTileMode } from '../state'

const d = computed(() => depth.value?.detail ?? null)
const sceneSummary = computed(() => (state.scene ? depthScenes[state.scene.token] : undefined))
const sceneRange = computed(() => {
  const s = sceneSummary.value
  if (!s) return null
  const e = s.frames.map((f) => f.abs_rel)
  return { min: Math.min(...e), max: Math.max(...e) }
})

const tileModes: { id: DepthTileMode; label: string; hint: string }[] = [
  { id: 'wipe', label: 'Wipe', hint: 'Photo on the left, depth on the right. Move the mouse over a tile to slide the split.' },
  { id: 'depth', label: 'Depth', hint: 'The relative depth map alone. Warm is near, cool is far, scaled per image.' },
  { id: 'error', label: 'Lidar error', hint: 'Lidar points on the photo. Coral where the model sees them too close, blue too far, white within a few percent.' },
]
const cloudColors: { id: DepthCloudColor; label: string }[] = [
  { id: 'photo', label: 'Photo' },
  { id: 'camera', label: 'By camera' },
]

function short(ch: string) {
  return ch.replace(/^CAM_/, '').replace(/_/g, ' ').toLowerCase()
}
function pct(x: number) {
  return (x * 100).toFixed(1) + '%'
}
function cameraOn(ch: string) {
  return depthLayers.cameras[ch] !== false
}
function toggleCamera(ch: string) {
  depthLayers.cameras[ch] = !cameraOn(ch)
}
</script>

<template>
  <aside class="inspector">
    <section>
      <h2>Model</h2>
      <p class="lead" v-if="d">{{ d.model.model }}, stock weights, no fine tuning. Runs on {{ d.model.device === 'mps' ? 'the Apple GPU' : d.model.device }} in about {{ d.model.last_inference_s ? Math.round(d.model.last_inference_s * 1000) : '200' }} ms per image.</p>
      <p class="note muted">
        The model predicts relative inverse depth: which pixels are nearer, not how many metres away. To compare with lidar, each image gets its own scale and shift fitted by least squares to the lidar points that project into it. Everything below is measured after that fit, so it is the best case for the stock model.
      </p>
      <p v-if="state.depthError" class="error">{{ state.depthError }}</p>
    </section>

    <section v-if="d">
      <h2>Against lidar, this keyframe</h2>
      <dl class="kv num">
        <dt title="Mean of |predicted - lidar| / lidar">AbsRel</dt>
        <dd>{{ pct(d.overall.abs_rel) }}</dd>
        <dt title="Root mean square depth error in metres">RMSE</dt>
        <dd>{{ d.overall.rmse.toFixed(2) }} m</dd>
        <dt title="Share of lidar points predicted within 25% of their true depth">δ1</dt>
        <dd>{{ pct(d.overall.delta1) }}</dd>
        <dt>Lidar points</dt>
        <dd>{{ d.overall.n_lidar.toLocaleString() }}</dd>
      </dl>
      <p class="note scene" v-if="sceneSummary && sceneRange">
        Whole scene: AbsRel {{ pct(sceneSummary.abs_rel) }} on average, from {{ pct(sceneRange.min) }} to {{ pct(sceneRange.max) }} across its keyframes. The timeline bars below show it per keyframe.
      </p>
      <table class="cams num">
        <thead>
          <tr>
            <th>Camera</th>
            <th>AbsRel</th>
            <th>δ1</th>
            <th title="Fitted scale on the model output. Cameras that agree should have similar values.">Scale</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(c, i) in d.cameras" :key="c.channel" :class="{ off: !cameraOn(c.channel) }" @click="toggleCamera(c.channel)" :title="cameraOn(c.channel) ? 'Hide this camera in 3D' : 'Show this camera in 3D'">
            <td><span class="swatch" :style="{ background: CAMERA_TINTS[i] }"></span>{{ short(c.channel) }}</td>
            <td>{{ pct(c.abs_rel) }}</td>
            <td>{{ (c.delta1 * 100).toFixed(0) }}%</td>
            <td>{{ (c.scale * 1000).toFixed(1) }}</td>
          </tr>
        </tbody>
      </table>
      <p class="note muted">Scale is shown ×1000. The spread between cameras is scale drift the model has no way to know about; a single fit for all six would be worse than any row above.</p>
    </section>

    <section>
      <h2>Camera tiles</h2>
      <div class="seg">
        <button v-for="m in tileModes" :key="m.id" :class="{ on: depthLayers.tile === m.id }" @click="depthLayers.tile = m.id">{{ m.label }}</button>
      </div>
      <p class="note muted">{{ tileModes.find((m) => m.id === depthLayers.tile)?.hint }}</p>
    </section>

    <section>
      <h2>3D layers</h2>
      <button class="toggle" :class="{ on: depthLayers.prediction }" @click="depthLayers.prediction = !depthLayers.prediction"><span>Camera depth, unprojected</span><span class="knob"></span></button>
      <div class="seg" v-if="depthLayers.prediction">
        <button v-for="m in cloudColors" :key="m.id" :class="{ on: depthLayers.cloudColor === m.id }" @click="depthLayers.cloudColor = m.id">{{ m.label }}</button>
      </div>
      <label class="range" v-if="depthLayers.prediction">
        <span class="muted">Point size</span>
        <input type="range" min="1" max="5" step="0.2" v-model.number="depthLayers.pointSize" />
      </label>
      <label class="range" v-if="depthLayers.prediction">
        <span class="muted">Max range {{ depthLayers.maxRange }} m</span>
        <input type="range" min="10" max="80" step="5" v-model.number="depthLayers.maxRange" />
      </label>
      <button class="toggle" :class="{ on: depthLayers.lidar }" @click="depthLayers.lidar = !depthLayers.lidar"><span>Lidar sweep</span><span class="knob"></span></button>
      <p class="note muted">Click a camera row above to hide or show it in 3D. Seams between neighbouring cameras are where the per-image fits disagree.</p>
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
.note.scene {
  margin: 0 0 12px;
}
.error {
  margin: 8px 0 0;
  color: #ffb4b4;
  font-size: 12px;
}
.kv {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 3px 14px;
  margin: 0 0 10px;
}
.kv dt {
  color: var(--muted);
}
.kv dd {
  margin: 0;
}
.cams {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.cams th {
  text-align: right;
  font-weight: 500;
  color: var(--muted);
  padding: 2px 0 4px;
}
.cams th:first-child,
.cams td:first-child {
  text-align: left;
}
.cams td {
  text-align: right;
  padding: 3px 0;
  border-top: 1px solid var(--line);
  text-transform: capitalize;
  cursor: pointer;
}
.cams td .swatch {
  margin-right: 7px;
  vertical-align: 0;
}
.cams tr:hover td {
  background: var(--panel-2);
}
.cams tr.off td {
  color: var(--faint);
}
.cams tr.off .swatch {
  opacity: 0.3;
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
.range {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 0 8px;
  font-size: 12px;
}
.range input {
  flex: 1;
  accent-color: var(--accent);
}
</style>
