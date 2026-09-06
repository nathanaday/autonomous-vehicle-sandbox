<script setup lang="ts">
import { computed } from 'vue'
import { channelLabel } from '../geometry'
import { frame, splatLayers, splatStatus } from '../state'

const s = computed(() => (splatStatus.value?.state === 'ready' ? splatStatus.value : null))

/** Views of the current keyframe only; with 18 views the neighbours are folded
 *  into the same six rows by channel. */
const rows = computed(() => {
  const st = s.value
  const tok = frame.value?.detail.token
  if (!st?.views) return []
  return st.views
    .map((v, i) => ({ ...v, i }))
    .filter((v) => v.sample_token === tok)
    .map((v) => ({
      channel: v.channel,
      label: channelLabel(v.channel),
      lidar: v.lidar,
      rot: st.pose?.rotation_error_deg?.[v.i],
      pos: st.pose?.position_error_m?.[v.i],
    }))
})

const overall = computed(() => {
  const st = s.value
  if (!st?.views) return null
  const withLidar = st.views.filter((v) => v.lidar)
  if (!withLidar.length) return null
  const n = withLidar.reduce((a, v) => a + v.lidar!.n, 0)
  const absRel = withLidar.reduce((a, v) => a + v.lidar!.abs_rel * v.lidar!.n, 0) / n
  const delta1 = withLidar.reduce((a, v) => a + v.lidar!.delta1 * v.lidar!.n, 0) / n
  const scaled = withLidar.reduce((a, v) => a + v.lidar!.abs_rel_after_scale * v.lidar!.n, 0) / n
  const perCam = withLidar.map((v) => v.lidar!.abs_rel).sort((a, b) => a - b)
  const median = perCam[Math.floor(perCam.length / 2)]
  return { n, absRel, delta1, scaled, median }
})

function pct(x: number) {
  return (x * 100).toFixed(1) + '%'
}
</script>

<template>
  <aside class="inspector">
    <section>
      <h2>Method</h2>
      <p class="lead">Depth Anything 3 takes the six photos of this keyframe and returns, in one forward pass, a metric depth map, a sky mask and a 3D Gaussian for every pixel. No per-scene training.</p>
      <p class="note muted">The Gaussians are re-expressed in the ego frame using the calibrated camera poses, so the splat sits on the same ground as the lidar sweep. The model is the nested 1.4B-parameter release: an any-view transformer for geometry and Gaussians plus a monocular branch for metric scale.</p>
    </section>

    <section>
      <h2>Run</h2>
      <div class="row">
        <span class="muted">Views</span>
        <div class="seg">
          <button :class="{ on: splatLayers.views === 6 }" @click="splatLayers.views = 6">This keyframe</button>
          <button :class="{ on: splatLayers.views === 18 }" @click="splatLayers.views = 18">With neighbours</button>
        </div>
      </div>
      <div class="row">
        <span class="muted">Cameras</span>
        <div class="seg">
          <button :class="{ on: splatLayers.posed }" @click="splatLayers.posed = true">Calibrated</button>
          <button :class="{ on: !splatLayers.posed }" @click="splatLayers.posed = false">Estimated</button>
        </div>
      </div>
      <p class="note muted">
        <template v-if="splatLayers.posed">Camera poses and intrinsics come from the nuScenes calibration and condition the model.</template>
        <template v-else>The model estimates camera poses itself. The result is aligned to the calibration afterwards, and the pose error is reported below.</template>
        Each combination is built once and cached.
      </p>
    </section>

    <section v-if="s">
      <h2>This splat</h2>
      <dl class="kv num">
        <dt>Gaussians</dt>
        <dd>{{ (s.n_gaussians ?? 0).toLocaleString() }} <span class="muted">of {{ (s.n_gaussians_raw ?? 0).toLocaleString() }} predicted</span></dd>
        <dt>Per view</dt>
        <dd>{{ s.process_res?.[0] }}×{{ s.process_res?.[1] }} <span class="muted">pixels, one Gaussian each</span></dd>
        <dt>Sky</dt>
        <dd>{{ s.sky_fraction != null ? pct(s.sky_fraction) : '—' }} <span class="muted">of pixels, removed</span></dd>
        <dt>Inference</dt>
        <dd>{{ s.seconds?.inference }} s <span class="muted">on {{ s.device === 'mps' ? 'the Apple GPU' : s.device }}, {{ s.seconds?.load }} s to load</span></dd>
        <dt>File</dt>
        <dd>{{ ((s.ply_bytes ?? 0) / 1e6).toFixed(0) }} MB</dd>
      </dl>
    </section>

    <section v-if="s && overall">
      <h2>Metric depth against lidar, no fitting</h2>
      <dl class="kv num">
        <dt>AbsRel</dt>
        <dd>{{ pct(overall.absRel) }} <span class="muted" v-if="overall.absRel > 2 * overall.median">pooled; median camera {{ pct(overall.median) }}</span></dd>
        <dt>δ1</dt>
        <dd>{{ pct(overall.delta1) }}</dd>
        <dt>After one scale</dt>
        <dd>{{ pct(overall.scaled) }} <span class="muted">AbsRel</span></dd>
      </dl>
      <table class="cams num">
        <thead>
          <tr>
            <th>Camera</th>
            <th title="Mean absolute relative error against lidar, using the model's own metric scale">AbsRel</th>
            <th title="Median ratio lidar / predicted depth. 1.00 means the metric scale is right.">Scale</th>
            <th v-if="!s.posed" title="Rotation error of the estimated camera after alignment">Rot</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.channel">
            <td>{{ r.label }}</td>
            <td>{{ r.lidar ? pct(r.lidar.abs_rel) : '—' }}</td>
            <td>{{ r.lidar ? r.lidar.median_scale_to_lidar.toFixed(2) : '—' }}</td>
            <td v-if="!s.posed">{{ r.rot != null ? r.rot.toFixed(1) + '°' : '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p class="note muted">Unlike the Depth Anything view, nothing here is fitted to the lidar first. These are the numbers a camera-only system would actually have.</p>
    </section>

    <section>
      <h2>Display</h2>
      <button class="toggle" :class="{ on: splatLayers.lidar }" @click="splatLayers.lidar = !splatLayers.lidar"><span>Lidar sweep</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: splatLayers.frustums }" @click="splatLayers.frustums = !splatLayers.frustums"><span>Camera frustums</span><span class="knob"></span></button>
      <button class="toggle" :class="{ on: splatLayers.rings }" @click="splatLayers.rings = !splatLayers.rings"><span>Range rings and ego car</span><span class="knob"></span></button>
      <p class="note muted">Orbit away from the car to see how the splat holds up from viewpoints no camera saw. Step keyframes with the arrow keys to build the next one.</p>
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
  padding: 4px 0 2px;
}
.kv {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 3px 14px;
  margin: 0 0 8px;
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
}
.seg {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  margin: 2px 0 4px;
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
