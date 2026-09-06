<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js'
import { api, LIDAR_STRIDE, type FusionStatus } from '../api'
import { COLORS } from '../geometry'
import { egoOutline, setPoints, useThreeScene } from '../composables/useThreeScene'
import { frame, fusionLayers, fusionStatus } from '../state'

const host = ref<HTMLDivElement | null>(null)
const { scene, camera, controls, rings, ego, preset, setView } = useThreeScene(host)
rings.visible = false
ego.visible = false // the fusion view moves its own ego outline along the path

// ----- mesh -----

const photoMat = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide })
const litMat = new THREE.MeshStandardMaterial({ vertexColors: true, side: THREE.DoubleSide, roughness: 0.9, metalness: 0 })
const normalMat = new THREE.MeshNormalMaterial({ side: THREE.DoubleSide })
const mesh: THREE.Mesh<THREE.BufferGeometry, THREE.Material> = new THREE.Mesh(new THREE.BufferGeometry(), photoMat)
mesh.frustumCulled = false
scene.add(mesh)
scene.add(new THREE.HemisphereLight('#dfe8f5', '#1b2330', 1.1))
const sun = new THREE.DirectionalLight('#ffffff', 1.4)
sun.position.set(40, -30, 80)
scene.add(sun)

const loader = new PLYLoader()
const geometryCache = new Map<string, THREE.BufferGeometry>()
const loading = ref(false)
const loadError = ref<string | null>(null)
let loadRequest = 0

async function loadMesh(s: FusionStatus) {
  const id = ++loadRequest
  loadError.value = null
  let geom = geometryCache.get(s.key)
  if (!geom) {
    loading.value = true
    try {
      geom = await loader.loadAsync(api.fusionMeshUrl(s.key))
      geometryCache.set(s.key, geom)
    } catch (e) {
      if (id === loadRequest) loadError.value = String(e)
      return
    } finally {
      if (id === loadRequest) loading.value = false
    }
  }
  if (id !== loadRequest) return
  mesh.geometry = geom
}

watch(
  fusionStatus,
  (s) => {
    if (s?.state === 'ready') loadMesh(s)
    else mesh.geometry = new THREE.BufferGeometry()
  },
  { immediate: true },
)

function applyShading() {
  const m = fusionLayers.shading === 'lit' ? litMat : fusionLayers.shading === 'normals' ? normalMat : photoMat
  m.wireframe = fusionLayers.wireframe
  mesh.material = m
}
watch(() => [fusionLayers.shading, fusionLayers.wireframe], applyShading, { immediate: true })

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
  const s = fusionStatus.value
  const tok = frame.value?.detail.token
  const p = s?.poses?.find((p) => p.token === tok)?.ego_to_scene
  return p ? new THREE.Matrix4().set(...(p.flat() as [number, number, number, number, number, number, number, number, number, number, number, number, number, number, number, number])) : null
})

function updatePath() {
  const poses = fusionStatus.value?.poses ?? []
  pathGeom.setFromPoints(poses.map((p) => new THREE.Vector3(p.ego_to_scene[0][3], p.ego_to_scene[1][3], p.ego_to_scene[2][3] + 0.05)))
}

function updateEgo() {
  const m = currentPose.value
  const f = frame.value
  if (!m || !f) {
    egoMarker.visible = false
    lidar.visible = false
    return
  }
  egoMarker.visible = true
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
  lidar.visible = fusionLayers.lidarOverlay

  if (fusionLayers.followEgo && controls.value) {
    const target = new THREE.Vector3(m.elements[12], m.elements[13], m.elements[14])
    const delta = target.clone().sub(controls.value.target)
    controls.value.target.copy(target)
    camera.position.add(delta)
    controls.value.update()
  }
}

watch([currentPose, frame], updateEgo, { immediate: true })
watch(() => fusionStatus.value?.poses, updatePath, { immediate: true })
watch(
  () => [fusionLayers.lidarOverlay, fusionLayers.path],
  () => {
    lidar.visible = fusionLayers.lidarOverlay && egoMarker.visible
    pathGroup.visible = fusionLayers.path
  },
  { immediate: true },
)

onUnmounted(() => {
  for (const g of geometryCache.values()) g.dispose()
  geometryCache.clear()
})

</script>

<template>
  <section class="cloud">
    <div class="host" ref="host"></div>
    <div class="banner" v-if="fusionStatus?.state === 'missing'">
      <div class="title">No fused mesh computed for these settings</div>
      <div class="muted">Meshes are computed offline and read from the cache.</div>
      <pre class="cmd">{{ fusionStatus.message?.replace(/^.*offline: /, '') }}</pre>
    </div>
    <div class="banner error" v-else-if="fusionStatus?.state === 'error' || loadError">{{ fusionStatus?.message || loadError }}</div>
    <div class="banner" v-else-if="loading"><div class="title">Loading mesh</div></div>
    <div class="hud">
      <div class="views">
        <button :class="{ on: preset === 'chase' }" @click="setView('chase')">Chase</button>
        <button :class="{ on: preset === 'top' }" @click="setView('top')">Top</button>
        <button :class="{ on: preset === 'side' }" @click="setView('side')">Side</button>
      </div>
      <div class="legend num" v-if="fusionStatus?.state === 'ready'">
        <span>{{ (fusionStatus.triangles ?? 0).toLocaleString() }} triangles from {{ fusionStatus.views }} camera views over {{ fusionStatus.keyframes }} keyframes</span>
        <span v-if="fusionLayers.lidarOverlay"><i class="swatch" :style="{ background: COLORS.lidar }"></i>Lidar, this keyframe</span>
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
  min-width: 320px;
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
