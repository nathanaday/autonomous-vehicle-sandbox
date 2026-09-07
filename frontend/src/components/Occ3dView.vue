<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { LIDAR_STRIDE, OCC3D_CAMERA_BIT, OCC3D_CLASS_MASK, OCC3D_FREE, OCC3D_LIDAR_BIT, type Occ3dFrame } from '../api'
import { BOX_EDGES, boxCorners, categoryColor, COLORS } from '../geometry'
import { setPoints, useThreeScene } from '../composables/useThreeScene'
import { frame, occ3d, occ3dLayers, sceneOcc3d, state } from '../state'

const host = ref<HTMLDivElement | null>(null)
const { scene, rings, ego, preset, setView } = useThreeScene(host)
rings.visible = false

scene.add(new THREE.HemisphereLight('#dfe8f5', '#1b2330', 1.15))
const sun = new THREE.DirectionalLight('#ffffff', 1.3)
sun.position.set(30, -20, 60)
scene.add(sun)

/** Grid geometry from the scene status, with the published Occ3D values as
 *  the fallback while it loads. */
const grid = computed(() => sceneOcc3d.value?.grid ?? { shape: [200, 200, 16], voxel: 0.4, origin: [-40, -40, -1] })
const classes = computed(() => sceneOcc3d.value?.classes ?? [])

// ----- voxels: one instanced cube per drawn voxel, rebuilt when anything changes -----

const material = new THREE.MeshLambertMaterial()
const group = new THREE.Group()
scene.add(group)
let cubes: THREE.InstancedMesh | null = null
const shown = ref(0)

function classColors(): THREE.Color[] {
  return classes.value.map((c) => new THREE.Color(c.color))
}

function rebuild() {
  if (cubes) {
    group.remove(cubes)
    cubes.geometry.dispose()
    cubes = null
  }
  const o = occ3d.value
  if (!o || !classes.value.length) {
    shown.value = 0
    return
  }
  const { shape, voxel, origin } = grid.value
  const [, ny, nz] = shape
  const bytes = o.grid
  const want = occ3dLayers.visibility === 'camera' ? OCC3D_CAMERA_BIT : occ3dLayers.visibility === 'lidar' ? OCC3D_LIDAR_BIT : 0
  const hidden = occ3dLayers.hidden
  const zMax = Math.min(nz, occ3dLayers.maxLayer)

  // first pass: count, so the instanced buffer is exact
  const keep = new Uint8Array(bytes.length)
  let n = 0
  for (let i = 0; i < bytes.length; i++) {
    const b = bytes[i]
    const cls = b & OCC3D_CLASS_MASK
    if (cls === OCC3D_FREE || hidden[cls]) continue
    if (want && !(b & want)) continue
    if (i % nz >= zMax) continue
    keep[i] = 1
    n++
  }
  shown.value = n
  if (!n) return

  const size = voxel * occ3dLayers.cubeScale
  const geom = new THREE.BoxGeometry(size, size, size)
  const mesh = new THREE.InstancedMesh(geom, material, n)
  const colors = classColors()
  const m = new THREE.Matrix4()
  const half = voxel / 2
  let k = 0
  for (let i = 0; i < bytes.length; i++) {
    if (!keep[i]) continue
    const iz = i % nz
    const iy = ((i - iz) / nz) % ny
    const ix = (i - iz - iy * nz) / (ny * nz)
    m.makeTranslation(origin[0] + ix * voxel + half, origin[1] + iy * voxel + half, origin[2] + iz * voxel + half)
    mesh.setMatrixAt(k, m)
    mesh.setColorAt(k, colors[bytes[i] & OCC3D_CLASS_MASK])
    k++
  }
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  mesh.frustumCulled = false
  cubes = mesh
  group.add(mesh)
}

watch(
  () => [occ3d.value, sceneOcc3d.value, occ3dLayers.visibility, occ3dLayers.maxLayer, occ3dLayers.cubeScale, { ...occ3dLayers.hidden }] as const,
  rebuild,
  { immediate: true },
)
watch(() => occ3dLayers.lift, (z) => (group.position.z = z), { immediate: true })

// ----- grid bounds, lidar and boxes, all in the ego frame -----

const boundsGeom = new THREE.BufferGeometry()
const bounds = new THREE.LineSegments(boundsGeom, new THREE.LineBasicMaterial({ color: '#34435a' }))
group.add(bounds)
watch(
  grid,
  (g) => {
    const [nx, ny, nz] = g.shape
    const box = new THREE.BoxGeometry(nx * g.voxel, ny * g.voxel, nz * g.voxel)
    box.translate(g.origin[0] + (nx * g.voxel) / 2, g.origin[1] + (ny * g.voxel) / 2, g.origin[2] + (nz * g.voxel) / 2)
    bounds.geometry.dispose()
    bounds.geometry = new THREE.EdgesGeometry(box)
  },
  { immediate: true },
)

const lidarGeom = new THREE.BufferGeometry()
const lidar = new THREE.Points(lidarGeom, new THREE.PointsMaterial({ size: 1.8, color: COLORS.lidar, sizeAttenuation: false, transparent: true, opacity: 0.85 }))
lidar.frustumCulled = false
const boxGeom = new THREE.BufferGeometry()
const boxes = new THREE.LineSegments(boxGeom, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9 }))
boxes.frustumCulled = false
scene.add(lidar, boxes)

function updateFrame() {
  const f = frame.value
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

  const anns = f.detail.annotations
  const bpos = new Float32Array(anns.length * BOX_EDGES.length * 6)
  const bcol = new Float32Array(anns.length * BOX_EDGES.length * 6)
  const color = new THREE.Color()
  let k = 0
  for (const a of anns) {
    const c = boxCorners(a)
    color.set(categoryColor(a.category))
    for (const [i, j] of BOX_EDGES) {
      for (const p of [c[i], c[j]]) {
        bpos[k] = p[0]
        bpos[k + 1] = p[1]
        bpos[k + 2] = p[2]
        bcol[k] = color.r
        bcol[k + 1] = color.g
        bcol[k + 2] = color.b
        k += 3
      }
    }
  }
  setPoints(boxGeom, bpos, bcol)
}
watch(frame, updateFrame, { immediate: true })
watch(
  () => [occ3dLayers.lidar, occ3dLayers.boxes, occ3dLayers.bounds],
  () => {
    lidar.visible = occ3dLayers.lidar
    boxes.visible = occ3dLayers.boxes
    bounds.visible = occ3dLayers.bounds
  },
  { immediate: true },
)
ego.visible = true

onUnmounted(() => {
  cubes?.geometry.dispose()
  material.dispose()
})

const stats = computed(() => occ3d.value?.stats ?? null)
const missing = computed(() => sceneOcc3d.value && sceneOcc3d.value.n_ready === 0)

function fmt(o: Occ3dFrame | null): string {
  if (!o) return ''
  return `${shown.value.toLocaleString()} of ${o.stats.n_occupied.toLocaleString()} occupied voxels`
}
</script>

<template>
  <section class="cloud">
    <div class="host" ref="host"></div>

    <div class="banner" v-if="missing">
      <div class="title">No Occ3D labels for this scene</div>
      <div class="muted">The labels are a download, not a computation.</div>
      <pre class="cmd" v-if="sceneOcc3d?.message">{{ sceneOcc3d.message }}</pre>
    </div>
    <div class="banner error" v-else-if="state.occ3dError">{{ state.occ3dError }}</div>
    <div class="banner" v-else-if="state.loadingOcc3d && !occ3d"><div class="title">Loading occupancy grid</div></div>

    <div class="hud">
      <div class="views">
        <button :class="{ on: preset === 'chase' }" @click="setView('chase')">Chase</button>
        <button :class="{ on: preset === 'top' }" @click="setView('top')">Top</button>
        <button :class="{ on: preset === 'side' }" @click="setView('side')">Side</button>
      </div>
      <div class="legend num" v-if="stats">
        <span>{{ fmt(occ3d) }}<template v-if="occ3dLayers.visibility !== 'all'">, {{ occ3dLayers.visibility === 'camera' ? 'camera' : 'lidar' }}-visible only</template><template v-if="occ3dLayers.maxLayer < grid.shape[2]">, below {{ (grid.origin[2] + occ3dLayers.maxLayer * grid.voxel).toFixed(1) }} m</template></span>
        <span v-if="occ3dLayers.lift">grid lifted {{ occ3dLayers.lift > 0 ? '+' : '' }}{{ occ3dLayers.lift.toFixed(1) }} m</span>
        <span v-if="occ3dLayers.lidar"><i class="swatch" :style="{ background: COLORS.lidar }"></i>Lidar sweep</span>
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
