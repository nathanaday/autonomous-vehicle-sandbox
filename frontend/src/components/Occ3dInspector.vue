<script setup lang="ts">
import { computed } from 'vue'
import { OCC3D_FREE } from '../api'
import { occ3d, occ3dLayers, sceneOcc3d } from '../state'

const stats = computed(() => occ3d.value?.stats ?? null)
const grid = computed(() => sceneOcc3d.value?.grid ?? null)

/** Classes with at least one voxel in this keyframe, most common first,
 *  with the count under the current visibility choice. */
const rows = computed(() => {
  const s = stats.value, sc = sceneOcc3d.value
  if (!s || !sc) return []
  const counts = occ3dLayers.visibility === 'camera' ? s.class_counts_camera : occ3dLayers.visibility === 'lidar' ? s.class_counts_lidar : s.class_counts
  return sc.classes
    .filter((c) => c.id !== OCC3D_FREE && s.class_counts[c.id] > 0)
    .map((c) => ({ ...c, n: counts[c.id] }))
    .sort((a, b) => b.n - a.n)
})
const total = computed(() => rows.value.reduce((a, r) => a + r.n, 0))

function toggle(id: number) {
  if (occ3dLayers.hidden[id]) delete occ3dLayers.hidden[id]
  else occ3dLayers.hidden[id] = true
}
function only(id: number) {
  const alone = rows.value.every((r) => (r.id === id) !== !!occ3dLayers.hidden[r.id])
  for (const r of rows.value) {
    if (alone || r.id === id) delete occ3dLayers.hidden[r.id]
    else occ3dLayers.hidden[r.id] = true
  }
}
const anyHidden = computed(() => Object.keys(occ3dLayers.hidden).length > 0)
function showAll() {
  for (const k of Object.keys(occ3dLayers.hidden)) delete occ3dLayers.hidden[Number(k)]
}

const pct = (a: number, b: number) => (b ? `${((100 * a) / b).toFixed(0)}%` : '')
const heightCut = computed(() => (grid.value ? grid.value.origin[2] + occ3dLayers.maxLayer * grid.value.voxel : 0))
</script>

<template>
  <aside class="inspector">
    <section>
      <h2>Occ3D-nuScenes</h2>
      <p class="lead">The published semantic occupancy label of this keyframe: which 0.4 m voxels around the car are filled, and with what.</p>
      <p class="note muted" v-if="grid">{{ grid.shape[0] }} x {{ grid.shape[1] }} x {{ grid.shape[2] }} voxels in the ego frame, {{ grid.origin[0] }} to {{ grid.origin[0] + grid.shape[0] * grid.voxel }} m across and {{ grid.origin[2] }} to {{ (grid.origin[2] + grid.shape[2] * grid.voxel).toFixed(1) }} m up. Built by accumulating the lidar-seg point labels over the scene, so it holds more than one sweep sees. Voxels no beam ever reached are unobserved and do not count in the benchmark.</p>
    </section>

    <section v-if="stats">
      <h2>This keyframe</h2>
      <dl class="kv num">
        <dt>Occupied</dt>
        <dd>{{ stats.n_occupied.toLocaleString() }} <span class="muted">voxels, {{ pct(stats.n_occupied, stats.n_occupied + stats.n_free) }} of the grid</span></dd>
        <dt>Seen by lidar</dt>
        <dd>{{ stats.n_occupied_lidar_visible.toLocaleString() }} <span class="muted">{{ pct(stats.n_occupied_lidar_visible, stats.n_occupied) }} of occupied</span></dd>
        <dt>Seen by cameras</dt>
        <dd>{{ stats.n_occupied_camera_visible.toLocaleString() }} <span class="muted">{{ pct(stats.n_occupied_camera_visible, stats.n_occupied) }} of occupied</span></dd>
        <dt>Lidar sweep</dt>
        <dd>{{ pct(stats.lidar.hit_occupied, 1) }} <span class="muted">of {{ stats.lidar.n_in_grid.toLocaleString() }} points land in an occupied voxel</span></dd>
        <dt>Road offset</dt>
        <dd v-if="stats.lidar.ground_offset_m !== null">{{ stats.lidar.ground_offset_m.toFixed(2) }} m <span class="muted">labelled road below the lidar's road returns</span></dd>
        <dd v-else class="muted">no drivable voxels</dd>
      </dl>
      <p class="note muted">The road offset is why the lidar hit rate is low: the sweep's ground returns fall in the free voxel above the labelled road. Lift the grid to line them up by eye.</p>
    </section>

    <section v-if="rows.length">
      <h2>Classes <button class="link" v-if="anyHidden" @click="showAll">show all</button></h2>
      <div class="classes">
        <div v-for="r in rows" :key="r.id" class="cls" :class="{ off: occ3dLayers.hidden[r.id] }">
          <button class="row" @click="toggle(r.id)" :title="occ3dLayers.hidden[r.id] ? 'Show' : 'Hide'">
            <i class="swatch" :style="{ background: r.color }"></i>
            <span class="name">{{ r.name }}</span>
            <span class="n num muted">{{ r.n.toLocaleString() }}</span>
          </button>
          <span class="bar"><span class="fill" :style="{ width: (100 * r.n) / Math.max(1, rows[0].n) + '%', background: r.color }"></span></span>
          <button class="only" @click="only(r.id)" title="Show only this class">only</button>
        </div>
      </div>
      <p class="note muted num">{{ total.toLocaleString() }} voxels{{ occ3dLayers.visibility === 'all' ? '' : occ3dLayers.visibility === 'camera' ? ' seen by a camera' : ' seen by the lidar' }}. Click a class to hide it.</p>
    </section>

    <section>
      <h2>Voxels</h2>
      <div class="seg">
        <button :class="{ on: occ3dLayers.visibility === 'all' }" @click="occ3dLayers.visibility = 'all'" title="Every occupied voxel">All</button>
        <button :class="{ on: occ3dLayers.visibility === 'camera' }" @click="occ3dLayers.visibility = 'camera'" title="Only voxels a camera can see">Camera</button>
        <button :class="{ on: occ3dLayers.visibility === 'lidar' }" @click="occ3dLayers.visibility = 'lidar'" title="Only voxels the lidar can see">Lidar</button>
      </div>
      <p class="note muted">Every occupied voxel, or only the ones a camera or the lidar can see from here. The benchmark scores the camera-visible ones; All shows what the accumulated labels hold behind walls and around corners.</p>
      <label class="slider">
        <span>Height cut <b class="num">{{ heightCut.toFixed(1) }} m</b></span>
        <input type="range" min="1" :max="grid?.shape[2] ?? 16" step="1" v-model.number="occ3dLayers.maxLayer" />
      </label>
      <label class="slider">
        <span>Lift grid <b class="num">{{ occ3dLayers.lift > 0 ? '+' : '' }}{{ occ3dLayers.lift.toFixed(1) }} m</b></span>
        <input type="range" min="-1" max="1" step="0.1" v-model.number="occ3dLayers.lift" />
      </label>
      <label class="slider">
        <span>Cube size <b class="num">{{ (occ3dLayers.cubeScale * 100).toFixed(0) }}%</b></span>
        <input type="range" min="0.3" max="1" step="0.05" v-model.number="occ3dLayers.cubeScale" />
      </label>
    </section>

    <section>
      <h2>Overlays</h2>
      <button class="toggle" :class="{ on: occ3dLayers.lidar }" @click="occ3dLayers.lidar = !occ3dLayers.lidar"><span>Lidar sweep in the 3D view</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: occ3dLayers.boxes }" @click="occ3dLayers.boxes = !occ3dLayers.boxes"><span>Annotation boxes</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: occ3dLayers.bounds }" @click="occ3dLayers.bounds = !occ3dLayers.bounds"><span>Grid bounds</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: occ3dLayers.overlay }" @click="occ3dLayers.overlay = !occ3dLayers.overlay"><span>Voxels on the camera images</span><span class="knob"></span></button>
      <label class="slider" v-if="occ3dLayers.overlay">
        <span>Image overlay opacity <b class="num">{{ (occ3dLayers.overlayAlpha * 100).toFixed(0) }}%</b></span>
        <input type="range" min="0.1" max="1" step="0.05" v-model.number="occ3dLayers.overlayAlpha" />
      </label>
      <p class="note muted">The image overlay draws the camera-visible voxels only, each as a square the size of a voxel at its distance, so the class colours can be checked against the photo.</p>
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
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin: 0 0 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--muted);
}
.link {
  font-size: 11.5px;
  font-weight: 400;
  color: var(--accent);
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
.classes {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.cls {
  display: grid;
  grid-template-columns: 1fr 56px auto;
  align-items: center;
  gap: 8px;
  border-radius: 4px;
}
.cls:hover {
  background: var(--panel-2);
}
.cls.off {
  opacity: 0.45;
}
.cls.off .name {
  text-decoration: line-through;
}
.row {
  display: grid;
  grid-template-columns: 12px 1fr auto;
  align-items: center;
  gap: 8px;
  padding: 3px 4px;
  text-align: left;
  font-size: 12px;
}
.swatch {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  display: inline-block;
}
.bar {
  height: 4px;
  background: var(--ground);
  border-radius: 2px;
  overflow: hidden;
}
.fill {
  display: block;
  height: 100%;
}
.only {
  font-size: 11px;
  color: var(--muted);
  padding: 2px 6px;
  visibility: hidden;
}
.cls:hover .only {
  visibility: visible;
}
.only:hover {
  color: var(--text);
}
.seg {
  display: flex;
  padding: 2px;
  gap: 2px;
  background: var(--ground);
  border-radius: var(--radius);
}
.seg button {
  flex: 1;
  padding: 4px 6px;
  border-radius: 4px;
  color: var(--muted);
  font-size: 12px;
}
.seg button.on {
  color: var(--text);
  background: var(--line-strong);
}
.slider {
  display: block;
  margin-top: 10px;
  font-size: 12px;
}
.slider span {
  display: flex;
  justify-content: space-between;
  color: var(--muted);
  margin-bottom: 2px;
}
.slider b {
  color: var(--text);
  font-weight: 500;
}
.slider input {
  width: 100%;
}
</style>
