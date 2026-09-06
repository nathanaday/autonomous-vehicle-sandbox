<script setup lang="ts">
import { computed } from 'vue'
import { RADAR_STRIDE } from '../api'
import { categoryColor, categoryLabel } from '../geometry'
import { frame, layers, state, type LidarColorMode } from '../state'

const d = computed(() => frame.value?.detail ?? null)

const speed = computed(() => {
  const det = d.value
  if (!det) return null
  const t = det.trajectory
  const i = det.index
  const a = t[Math.max(0, i - 1)], b = t[Math.min(t.length - 1, i + 1)]
  const dt = b.t_s - a.t_s
  if (dt <= 0) return null
  const dist = Math.hypot(b.position[0] - a.position[0], b.position[1] - a.position[1])
  return (dist / dt) * 3.6
})

interface CategoryRow {
  category: string
  label: string
  count: number
  color: string
  lidarPts: number
  radarPts: number
  tokens: string[]
}

const categories = computed<CategoryRow[]>(() => {
  const rows = new Map<string, CategoryRow>()
  for (const a of d.value?.annotations ?? []) {
    let r = rows.get(a.category)
    if (!r) {
      r = { category: a.category, label: categoryLabel(a.category), count: 0, color: categoryColor(a.category), lidarPts: 0, radarPts: 0, tokens: [] }
      rows.set(a.category, r)
    }
    r.count++
    r.lidarPts += a.num_lidar_pts
    r.radarPts += a.num_radar_pts
    r.tokens.push(a.token)
  }
  return [...rows.values()].sort((x, y) => y.count - x.count)
})

const radarTotal = computed(() => (frame.value ? frame.value.radar.length / RADAR_STRIDE : 0))
const radarRaw = computed(() => d.value?.radars.reduce((s, r) => s + r.nbr_points_raw, 0) ?? 0)

const colorModes: { id: LidarColorMode; label: string }[] = [
  { id: 'height', label: 'Height' },
  { id: 'intensity', label: 'Intensity' },
  { id: 'distance', label: 'Distance' },
]

function shortChannel(ch: string) {
  return ch.replace(/^(CAM|RADAR|LIDAR)_/, '').replace(/_/g, ' ').toLowerCase()
}
</script>

<template>
  <aside class="inspector" v-if="d">
    <section>
      <h2>Ego vehicle</h2>
      <dl class="kv num">
        <dt>Speed</dt>
        <dd>{{ speed === null ? '—' : speed.toFixed(0) + ' km/h' }}</dd>
        <dt>Position</dt>
        <dd>{{ d.ego_pose.translation[0].toFixed(1) }}, {{ d.ego_pose.translation[1].toFixed(1) }} m</dd>
        <dt>Heading</dt>
        <dd>{{ ((Math.atan2(2 * (d.ego_pose.rotation[0] * d.ego_pose.rotation[3] + d.ego_pose.rotation[1] * d.ego_pose.rotation[2]), 1 - 2 * (d.ego_pose.rotation[2] ** 2 + d.ego_pose.rotation[3] ** 2)) * 180) / Math.PI).toFixed(0) }}° in map frame</dd>
      </dl>
    </section>

    <section>
      <h2>Sensors</h2>
      <ul class="sensors">
        <li>
          <span class="dot" style="background: var(--lidar)"></span>
          <span class="ch">Lidar top</span>
          <span class="val num">{{ d.lidar.nbr_points.toLocaleString() }} pts</span>
        </li>
        <li v-for="r in d.radars" :key="r.channel">
          <span class="dot" style="background: var(--radar)"></span>
          <span class="ch">Radar {{ shortChannel(r.channel) }}</span>
          <span class="val num" :title="`${r.nbr_points_raw} raw returns, ${r.nbr_points} after the devkit validity filter`">{{ r.nbr_points }} <span class="muted">of {{ r.nbr_points_raw }}</span></span>
        </li>
        <li v-for="c in d.cameras" :key="c.channel">
          <span class="dot" style="background: #c9d3e0"></span>
          <span class="ch">Camera {{ shortChannel(c.channel) }}</span>
          <span class="val num muted">{{ c.dt_ms > 0 ? '+' : '' }}{{ c.dt_ms.toFixed(0) }} ms</span>
        </li>
      </ul>
      <p class="note muted">
        Radar shows {{ radarTotal }} of {{ radarRaw }} raw returns after the standard validity filter. The lidar returns {{ d.lidar.nbr_points.toLocaleString() }} points in the same instant.
      </p>
    </section>

    <section>
      <h2>Annotated objects, {{ d.annotations.length }}</h2>
      <ul class="cats">
        <li
          v-for="c in categories"
          :key="c.category"
          @mouseenter="state.hoveredAnnotation = c.tokens.length === 1 ? c.tokens[0] : null"
          @mouseleave="state.hoveredAnnotation = null"
        >
          <span class="swatch" :style="{ background: c.color }"></span>
          <span class="ch">{{ c.label }}</span>
          <span class="val num">{{ c.count }}</span>
          <span class="pts num muted" :title="'Lidar and radar points inside these boxes'">{{ c.lidarPts.toLocaleString() }} / {{ c.radarPts }}</span>
        </li>
      </ul>
      <p class="note muted" v-if="categories.length">Counts on the right are lidar / radar points inside the boxes.</p>
    </section>

    <section>
      <h2>3D layers</h2>
      <button class="toggle" :class="{ on: layers.lidar }" @click="layers.lidar = !layers.lidar"><span>Lidar points</span><span class="knob"></span></button>
      <div class="seg" v-if="layers.lidar">
        <button v-for="m in colorModes" :key="m.id" :class="{ on: layers.lidarColor === m.id }" @click="layers.lidarColor = m.id">{{ m.label }}</button>
      </div>
      <label class="range" v-if="layers.lidar">
        <span class="muted">Point size</span>
        <input type="range" min="0.8" max="4" step="0.2" v-model.number="layers.pointSize" />
      </label>
      <button class="toggle" :class="{ on: layers.radar }" @click="layers.radar = !layers.radar"><span>Radar returns</span><span class="knob"></span></button>
      <button class="toggle sub" :class="{ on: layers.radarVelocity }" v-if="layers.radar" @click="layers.radarVelocity = !layers.radarVelocity"><span>Radial velocity</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: layers.boxes }" @click="layers.boxes = !layers.boxes"><span>Annotation boxes</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: layers.trajectory }" @click="layers.trajectory = !layers.trajectory"><span>Ego path through the scene</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: layers.sensors }" @click="layers.sensors = !layers.sensors"><span>Sensor mounts and frustums</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: layers.rings }" @click="layers.rings = !layers.rings"><span>Range rings, 10 m</span><span class="knob"></span></button>
    </section>

    <section>
      <h2>Camera overlays</h2>
      <button class="toggle" :class="{ on: layers.overlayLidar }" @click="layers.overlayLidar = !layers.overlayLidar"><span>Lidar depth</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: layers.overlayRadar }" @click="layers.overlayRadar = !layers.overlayRadar"><span>Radar returns</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: layers.overlayBoxes }" @click="layers.overlayBoxes = !layers.overlayBoxes"><span>Annotation boxes</span><span class="knob"></span></button>
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
ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.sensors li,
.cats li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2.5px 0;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
}
.ch {
  flex: 1;
  text-transform: capitalize;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.val {
  white-space: nowrap;
}
.pts {
  width: 84px;
  text-align: right;
  font-size: 12px;
}
.cats li:hover {
  background: var(--panel-2);
  margin: 0 -6px;
  padding-left: 6px;
  padding-right: 6px;
  border-radius: 4px;
}
.note {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.4;
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
.toggle.sub {
  padding-left: 14px;
  color: var(--muted);
}
</style>
