<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { SparkRenderer, SplatMesh } from '@sparkjsdev/spark'
import { api, LIDAR_STRIDE } from '../api'
import { COLORS } from '../geometry'
import { egoOutline, setPoints, useThreeScene, type ViewPreset } from '../composables/useThreeScene'
import { frame, gs3dLayers, gs3dVariant, sceneGs3d, state } from '../state'

const host = ref<HTMLDivElement | null>(null)
const { scene, camera, controls, renderer, rings, ego, setView: setPreset } = useThreeScene(host)
ego.visible = false // this view moves its own ego outline along the path

// ----- Spark: one renderer object in the scene, one SplatMesh for the scene -----

let spark: SparkRenderer | null = null
watch(renderer, (r) => {
  if (r && !spark) {
    spark = new SparkRenderer({ renderer: r })
    scene.add(spark)
  }
})

let shown: SplatMesh | null = null
let shownKey = ''
const loadError = ref<string | null>(null)

function hideSplat() {
  if (shown) {
    scene.remove(shown)
    shown.dispose()
  }
  shown = null
  shownKey = ''
  state.loadingGs3d = false
}

async function showSplat(key: string) {
  if (key === shownKey) return
  hideSplat()
  const m = new SplatMesh({ url: api.gs3dUrl(key) })
  shown = m
  shownKey = key
  scene.add(m)
  state.loadingGs3d = true
  loadError.value = null
  try {
    await m.initialized
  } catch (e) {
    if (shown === m) loadError.value = String(e)
  } finally {
    if (shown === m) state.loadingGs3d = false
  }
}

watch(
  gs3dVariant,
  (v) => {
    if (v) showSplat(v.key)
    else hideSplat()
  },
  { immediate: true },
)

// ----- ego, path, and the current keyframe's lidar in the scene frame -----

const egoMarker = egoOutline(0.9)
const pathGeom = new THREE.BufferGeometry()
const pathGroup = new THREE.Group()
pathGroup.add(
  new THREE.Line(pathGeom, new THREE.LineBasicMaterial({ color: COLORS.path })),
  new THREE.Points(pathGeom, new THREE.PointsMaterial({ size: 4, color: '#8fa3ba', sizeAttenuation: false })),
)
const lidarGeom = new THREE.BufferGeometry()
const lidar = new THREE.Points(lidarGeom, new THREE.PointsMaterial({ size: 1.6, color: COLORS.lidar, sizeAttenuation: false, transparent: true, opacity: 0.9 }))
lidar.frustumCulled = false
scene.add(egoMarker, pathGroup, lidar)

const currentPose = computed(() => {
  const tok = frame.value?.detail.token
  const p = gs3dVariant.value?.poses.find((p) => p.token === tok)?.ego_to_scene
  return p ? new THREE.Matrix4().set(...(p.flat() as [number, number, number, number, number, number, number, number, number, number, number, number, number, number, number, number])) : null
})

function updatePath() {
  const poses = gs3dVariant.value?.poses ?? []
  pathGeom.setFromPoints(poses.map((p) => new THREE.Vector3(p.ego_to_scene[0][3], p.ego_to_scene[1][3], p.ego_to_scene[2][3] + 0.05)))
}

/** 'driver' is this view's own preset: the camera sits at the windshield and
 *  looks down the road, close to where the training images were taken. The
 *  shared presets look down from above, where a splat shows its worst side. */
type Gs3dPreset = ViewPreset | 'driver'
const mode = ref<Gs3dPreset>('driver')

function placeDriver(m: THREE.Matrix4) {
  if (!controls.value) return
  camera.position.set(1.5, 0, 1.6).applyMatrix4(m)
  controls.value.target.set(30, 0, 1.2).applyMatrix4(m)
  controls.value.update()
}

function followEgo() {
  const m = currentPose.value
  if (!m || !controls.value) return
  if (mode.value === 'driver') return placeDriver(m)
  const target = new THREE.Vector3(m.elements[12], m.elements[13], m.elements[14])
  const delta = target.clone().sub(controls.value.target)
  controls.value.target.copy(target)
  camera.position.add(delta)
  controls.value.update()
}

function updateEgo() {
  const m = currentPose.value
  const f = frame.value
  if (!m || !f) {
    egoMarker.visible = false
    lidar.visible = false
    return
  }
  egoMarker.visible = mode.value !== 'driver'
  egoMarker.matrixAutoUpdate = false
  egoMarker.matrix.copy(m)

  const n = f.lidar.length / LIDAR_STRIDE
  const pos = new Float32Array(n * 3)
  const v = new THREE.Vector3()
  for (let i = 0; i < n; i++) {
    const b = i * LIDAR_STRIDE
    v.set(f.lidar[b], f.lidar[b + 1], f.lidar[b + 2]).applyMatrix4(m)
    pos[i * 3] = v.x
    pos[i * 3 + 1] = v.y
    pos[i * 3 + 2] = v.z
  }
  setPoints(lidarGeom, pos)
  lidar.visible = gs3dLayers.lidar
  if (gs3dLayers.followEgo) followEgo()
}

/** The shared presets frame the origin; keep them on the ego car instead. */
function setView(p: Gs3dPreset) {
  mode.value = p
  if (p !== 'driver') setPreset(p)
  egoMarker.visible = p !== 'driver' && !!currentPose.value
  if (p === 'driver' && currentPose.value) placeDriver(currentPose.value)
  else if (gs3dLayers.followEgo) followEgo()
}

watch([currentPose, frame], updateEgo, { immediate: true })
watch(controls, (c) => c && currentPose.value && mode.value === 'driver' && placeDriver(currentPose.value))
watch(() => gs3dVariant.value?.poses, updatePath, { immediate: true })
watch(
  () => [gs3dLayers.lidar, gs3dLayers.path, gs3dLayers.rings],
  () => {
    lidar.visible = gs3dLayers.lidar && egoMarker.visible
    pathGroup.visible = gs3dLayers.path
    rings.visible = gs3dLayers.rings
  },
  { immediate: true },
)

onUnmounted(() => {
  hideSplat()
  if (spark) {
    scene.remove(spark)
    spark = null
  }
})

const sizeMb = computed(() => ((gs3dVariant.value?.ply_bytes ?? 0) / 1e6).toFixed(0))
</script>

<template>
  <section class="cloud">
    <div class="host" ref="host"></div>

    <div class="banner" v-if="sceneGs3d && !gs3dVariant">
      <div class="title">No trained splat for this scene</div>
      <div class="muted">Splats are trained offline on a CUDA machine and read from the cache.</div>
      <pre class="cmd" v-if="sceneGs3d.message">{{ sceneGs3d.message }}</pre>
    </div>
    <div class="banner error" v-else-if="loadError">
      <div class="title">The splat could not be loaded</div>
      <div>{{ loadError }}</div>
    </div>
    <div class="banner" v-else-if="state.loadingGs3d"><div class="title">Loading {{ sizeMb }} MB of Gaussians</div></div>

    <div class="hud">
      <div class="views">
        <button :class="{ on: mode === 'driver' }" @click="setView('driver')">Driver</button>
        <button :class="{ on: mode === 'chase' }" @click="setView('chase')">Chase</button>
        <button :class="{ on: mode === 'top' }" @click="setView('top')">Top</button>
        <button :class="{ on: mode === 'side' }" @click="setView('side')">Side</button>
      </div>
      <div class="legend num" v-if="gs3dVariant">
        <span>{{ gs3dVariant.n_gaussians.toLocaleString() }} Gaussians from {{ gs3dVariant.n_images }} images, {{ gs3dVariant.scene_name }} keyframe {{ (frame?.detail.index ?? 0) + 1 }}</span>
        <span v-if="gs3dLayers.lidar"><i class="swatch" :style="{ background: COLORS.lidar }"></i>Lidar, this keyframe</span>
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
.cmd {
  margin: 10px 0 0;
  padding: 6px 10px;
  font-size: 12px;
  white-space: pre-wrap;
  background: var(--ground);
  border-radius: var(--radius);
  user-select: all;
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
