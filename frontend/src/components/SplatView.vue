<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { SparkRenderer, SplatMesh } from '@sparkjsdev/spark'
import { api, LIDAR_STRIDE, type SplatStatus } from '../api'
import { COLORS } from '../geometry'
import { setPoints, useThreeScene } from '../composables/useThreeScene'
import { frame, splatLayers, splatStatus, state } from '../state'

const host = ref<HTMLDivElement | null>(null)
const { scene, renderer, rings, ego, preset, setView } = useThreeScene(host)

// ----- Spark: one renderer object in the scene, one SplatMesh per key -----

let spark: SparkRenderer | null = null
watch(renderer, (r) => {
  if (r && !spark) {
    spark = new SparkRenderer({ renderer: r })
    scene.add(spark)
  }
})

let splat: SplatMesh | null = null
let splatKey = ''
const loading = ref(false)
const loadError = ref<string | null>(null)

function clearSplat() {
  if (splat) {
    scene.remove(splat)
    splat.dispose()
    splat = null
  }
  splatKey = ''
}

async function showSplat(s: SplatStatus) {
  if (s.key === splatKey) return
  clearSplat()
  splatKey = s.key
  loading.value = true
  loadError.value = null
  const mesh = new SplatMesh({ url: api.splatUrl(s.key) })
  splat = mesh
  scene.add(mesh)
  try {
    await mesh.initialized
  } catch (e) {
    if (splat === mesh) loadError.value = String(e)
  } finally {
    if (splat === mesh) loading.value = false
  }
}

watch(
  splatStatus,
  (s) => {
    if (s?.state === 'ready') showSplat(s)
    else if (!s || s.state !== 'running') clearSplat()
  },
  { immediate: true },
)

// ----- overlays: lidar of the keyframe, camera frustums -----

const lidarGeom = new THREE.BufferGeometry()
const lidar = new THREE.Points(lidarGeom, new THREE.PointsMaterial({ size: 1.4, color: COLORS.lidar, sizeAttenuation: false, transparent: true, opacity: 0.8 }))
lidar.frustumCulled = false
const frustums = new THREE.Group()
scene.add(lidar, frustums)

watch(
  frame,
  (f) => {
    if (!f) return
    const n = f.lidar.length / LIDAR_STRIDE
    const pos = new Float32Array(n * 3)
    for (let i = 0; i < n; i++) {
      const b = i * LIDAR_STRIDE
      pos[i * 3] = f.lidar[b]
      pos[i * 3 + 1] = f.lidar[b + 1]
      pos[i * 3 + 2] = f.lidar[b + 2]
    }
    setPoints(lidarGeom, pos)
  },
  { immediate: true },
)

function buildFrustums(s: SplatStatus | null) {
  frustums.clear()
  const f = frame.value
  if (!s?.views || !f) return
  const byChannel = new Map(f.detail.cameras.map((c) => [c.channel, c]))
  for (const v of s.views) {
    const cam = byChannel.get(v.channel)
    if (!cam || !v.c2w) continue
    const m = v.c2w
    const K = cam.intrinsic
    const depth = 2
    const corners = [[0, 0], [cam.width, 0], [cam.width, cam.height], [0, cam.height]].map(([u, w]) => {
      const x = ((u - K[0][2]) / K[0][0]) * depth
      const y = ((w - K[1][2]) / K[1][1]) * depth
      return new THREE.Vector3(
        m[0][0] * x + m[0][1] * y + m[0][2] * depth + m[0][3],
        m[1][0] * x + m[1][1] * y + m[1][2] * depth + m[1][3],
        m[2][0] * x + m[2][1] * y + m[2][2] * depth + m[2][3],
      )
    })
    const o = new THREE.Vector3(m[0][3], m[1][3], m[2][3])
    const pts: THREE.Vector3[] = []
    for (let i = 0; i < 4; i++) pts.push(o, corners[i], corners[i], corners[(i + 1) % 4])
    const own = v.sample_token === f.detail.token
    frustums.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: COLORS.camera, transparent: true, opacity: own ? 0.6 : 0.25 })))
  }
}
watch([splatStatus, frame], () => buildFrustums(splatStatus.value), { immediate: true })

function applyLayers() {
  lidar.visible = splatLayers.lidar
  frustums.visible = splatLayers.frustums
  rings.visible = splatLayers.rings
  ego.visible = splatLayers.rings
}
watch(splatLayers, applyLayers, { immediate: true })

onUnmounted(() => {
  clearSplat()
  if (spark) {
    scene.remove(spark)
    spark = null
  }
})

const progressPct = computed(() => Math.round((splatStatus.value?.progress ?? 0) * 100))
const sizeMb = computed(() => ((splatStatus.value?.ply_bytes ?? 0) / 1e6).toFixed(0))
</script>

<template>
  <section class="cloud">
    <div class="host" ref="host"></div>

    <div class="banner" v-if="splatStatus?.state === 'running'">
      <div class="title">Depth Anything 3 on {{ splatLayers.views }} views</div>
      <div class="muted">{{ splatStatus.message }}</div>
      <div class="bar"><i :style="{ width: progressPct + '%' }"></i></div>
      <div class="hint muted">First run loads a 6.8 GB model. Later keyframes take about a minute each.</div>
    </div>
    <div class="banner error" v-else-if="splatStatus?.state === 'error' || loadError">
      <div class="title">The splat could not be built</div>
      <div>{{ splatStatus?.message || loadError }}</div>
      <pre v-if="splatStatus?.tail?.length" class="tail">{{ splatStatus.tail.join('\n') }}</pre>
    </div>
    <div class="banner" v-else-if="loading"><div class="title">Loading {{ sizeMb }} MB of Gaussians</div></div>

    <div class="hud">
      <div class="views">
        <button :class="{ on: preset === 'chase' }" @click="setView('chase')">Chase</button>
        <button :class="{ on: preset === 'top' }" @click="setView('top')">Top</button>
        <button :class="{ on: preset === 'side' }" @click="setView('side')">Side</button>
      </div>
      <div class="legend num" v-if="splatStatus?.state === 'ready'">
        <span>{{ (splatStatus.n_gaussians ?? 0).toLocaleString() }} Gaussians from {{ splatStatus.n_views }} views, {{ state.scene?.name }} keyframe {{ (frame?.detail.index ?? 0) + 1 }}</span>
        <span v-if="splatLayers.lidar"><i class="swatch" :style="{ background: COLORS.lidar }"></i>Lidar sweep</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.cloud {
  position: relative;
  min-height: 0;
}
.host,
.host :deep(canvas) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}
.banner {
  position: absolute;
  left: 50%;
  top: 18px;
  transform: translateX(-50%);
  min-width: 360px;
  max-width: 640px;
  padding: 12px 16px;
  background: rgba(22, 31, 43, 0.92);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
}
.banner .title {
  font-weight: 600;
}
.banner.error {
  color: #ffd2d2;
  border-color: #8a3a44;
}
.hint {
  margin-top: 8px;
  font-size: 12px;
}
.tail {
  margin: 8px 0 0;
  font-size: 11px;
  white-space: pre-wrap;
  color: var(--muted);
  max-height: 120px;
  overflow: auto;
}
.bar {
  margin-top: 8px;
  height: 4px;
  border-radius: 2px;
  background: var(--line);
  overflow: hidden;
}
.bar i {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width 300ms;
}
.hud {
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 12px;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  pointer-events: none;
  gap: 12px;
}
.views {
  display: inline-flex;
  pointer-events: auto;
  background: rgba(22, 31, 43, 0.85);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  padding: 2px;
  gap: 2px;
}
.views button {
  padding: 4px 10px;
  border-radius: 4px;
  color: var(--muted);
}
.views button:hover {
  color: var(--text);
}
.views button.on {
  color: var(--text);
  background: var(--line-strong);
}
.legend {
  display: flex;
  gap: 16px;
  font-size: 11.5px;
  color: var(--text);
}
.legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
</style>
