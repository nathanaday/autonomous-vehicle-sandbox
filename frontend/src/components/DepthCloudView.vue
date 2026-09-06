<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import * as THREE from 'three'
import { DEPTH_CLOUD_STRIDE, LIDAR_STRIDE, type DepthFrame, type Frame } from '../api'
import { CAMERA_TINTS, COLORS, srgbToLinear } from '../geometry'
import { setPoints, useThreeScene } from '../composables/useThreeScene'
import { depth, depthLayers, frame, state } from '../state'

const host = ref<HTMLDivElement | null>(null)
const { scene, preset, setView } = useThreeScene(host)


const predGeom = new THREE.BufferGeometry()
const predMat = new THREE.PointsMaterial({ size: depthLayers.pointSize, vertexColors: true, sizeAttenuation: false })
const pred = new THREE.Points(predGeom, predMat)

const lidarGeom = new THREE.BufferGeometry()
const lidar = new THREE.Points(lidarGeom, new THREE.PointsMaterial({ size: 1.4, color: COLORS.lidar, sizeAttenuation: false, transparent: true, opacity: 0.85 }))

pred.frustumCulled = false
lidar.frustumCulled = false
scene.add(pred, lidar)

const tintLinear = CAMERA_TINTS.map((hex) => {
  const c = new THREE.Color(hex)
  return [c.r, c.g, c.b]
})

const shownPoints = ref(0)

function setPrediction(d: DepthFrame) {
  const n = d.cloud.length / DEPTH_CLOUD_STRIDE
  const pos = new Float32Array(n * 3)
  const col = new Float32Array(n * 3)
  const cams = d.detail.cameras
  const maxR = depthLayers.maxRange
  let k = 0
  for (let i = 0; i < n; i++) {
    const b = i * DEPTH_CLOUD_STRIDE
    const x = d.cloud[b], y = d.cloud[b + 1], z = d.cloud[b + 2]
    const camIdx = d.cloud[b + 6]
    const ch = cams[camIdx]?.channel
    if (ch && depthLayers.cameras[ch] === false) continue
    if (Math.hypot(x, y) > maxR) continue
    pos[k] = x
    pos[k + 1] = y
    pos[k + 2] = z
    if (depthLayers.cloudColor === 'camera') {
      const t = tintLinear[camIdx % tintLinear.length]
      col[k] = t[0]
      col[k + 1] = t[1]
      col[k + 2] = t[2]
    } else {
      // lift the photo colors so night scenes still read against the dark ground
      col[k] = srgbToLinear(Math.min(1, 0.08 + d.cloud[b + 3] * 1.25))
      col[k + 1] = srgbToLinear(Math.min(1, 0.08 + d.cloud[b + 4] * 1.25))
      col[k + 2] = srgbToLinear(Math.min(1, 0.08 + d.cloud[b + 5] * 1.25))
    }
    k += 3
  }
  shownPoints.value = k / 3
  setPoints(predGeom, pos.subarray(0, k), col.subarray(0, k))
}

function setLidar(f: Frame) {
  const n = f.lidar.length / LIDAR_STRIDE
  const pos = new Float32Array(n * 3)
  for (let i = 0; i < n; i++) {
    const b = i * LIDAR_STRIDE
    pos[i * 3] = f.lidar[b]
    pos[i * 3 + 1] = f.lidar[b + 1]
    pos[i * 3 + 2] = f.lidar[b + 2]
  }
  setPoints(lidarGeom, pos)
}

function applyLayers() {
  pred.visible = depthLayers.prediction
  lidar.visible = depthLayers.lidar
  predMat.size = depthLayers.pointSize
}

watch(depth, (d) => d && setPrediction(d), { immediate: true })
watch(frame, (f) => f && setLidar(f), { immediate: true })
watch(() => [depthLayers.cloudColor, depthLayers.maxRange, { ...depthLayers.cameras }], () => depth.value && setPrediction(depth.value), { deep: true })
watch(depthLayers, applyLayers, { immediate: true })

const lidarCount = computed(() => frame.value?.detail.lidar.nbr_points ?? 0)
</script>

<template>
  <section class="cloud">
    <div class="host" ref="host"></div>
    <div class="hud">
      <div class="views">
        <button :class="{ on: preset === 'chase' }" @click="setView('chase')">Chase</button>
        <button :class="{ on: preset === 'top' }" @click="setView('top')">Top</button>
        <button :class="{ on: preset === 'side' }" @click="setView('side')">Side</button>
      </div>
      <div class="legend num">
        <span v-if="depthLayers.prediction"><i class="swatch photo"></i>Camera depth, {{ shownPoints.toLocaleString() }} points from {{ depth?.detail.cameras.length ?? 6 }} cameras</span>
        <span v-if="depthLayers.lidar"><i class="swatch" :style="{ background: COLORS.lidar }"></i>Lidar, {{ lidarCount.toLocaleString() }} points</span>
        <span v-if="state.loadingDepth" class="muted">Running Depth Anything</span>
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
.swatch.photo {
  background: linear-gradient(135deg, #ffb347, #5fd3c4);
}
</style>
