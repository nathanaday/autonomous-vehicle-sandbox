<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { LIDAR_STRIDE, RADAR_STRIDE, type Frame } from '../api'
import { BOX_EDGES, boxCorners, categoryColor, COLORS, heightColor, intensityColor, depthColor, srgbToLinear } from '../geometry'
import { frame, layers, state } from '../state'

const host = ref<HTMLDivElement | null>(null)

const scene = new THREE.Scene()
scene.background = new THREE.Color('#0f1620')
const camera = new THREE.PerspectiveCamera(50, 1, 0.5, 600)
camera.up.set(0, 0, 1)
let renderer: THREE.WebGLRenderer | null = null
let controls: OrbitControls | null = null
let raf = 0

// ----- persistent objects, updated in place per frame -----

const lidarGeom = new THREE.BufferGeometry()
const lidarMat = new THREE.PointsMaterial({ size: layers.pointSize, vertexColors: true, sizeAttenuation: false })
const lidar = new THREE.Points(lidarGeom, lidarMat)
lidar.frustumCulled = false

const radarGeom = new THREE.BufferGeometry()
const radarMat = new THREE.PointsMaterial({ size: 7, color: COLORS.radar, sizeAttenuation: false })
const radar = new THREE.Points(radarGeom, radarMat)
radar.frustumCulled = false

const radarVelGeom = new THREE.BufferGeometry()
const radarVel = new THREE.LineSegments(radarVelGeom, new THREE.LineBasicMaterial({ color: COLORS.radar, transparent: true, opacity: 0.8 }))
radarVel.frustumCulled = false

const boxGeom = new THREE.BufferGeometry()
const boxes = new THREE.LineSegments(boxGeom, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9 }))
boxes.frustumCulled = false

const pathGeom = new THREE.BufferGeometry()
const path = new THREE.Line(pathGeom, new THREE.LineBasicMaterial({ color: COLORS.path }))
const pathDotsGeom = new THREE.BufferGeometry()
const pathDots = new THREE.Points(pathDotsGeom, new THREE.PointsMaterial({ size: 4, color: '#8fa3ba', sizeAttenuation: false }))
const pathGroup = new THREE.Group()
pathGroup.add(path, pathDots)

const sensorsGroup = new THREE.Group()
const ringsGroup = new THREE.Group()
const egoGroup = new THREE.Group()

scene.add(lidar, radar, radarVel, boxes, pathGroup, sensorsGroup, ringsGroup, egoGroup)

function buildStatic() {
  // range rings every 10 m, brighter at 50 m
  for (let r = 10; r <= 100; r += 10) {
    const pts: THREE.Vector3[] = []
    for (let i = 0; i <= 128; i++) {
      const a = (i / 128) * Math.PI * 2
      pts.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, -1.75))
    }
    const g = new THREE.BufferGeometry().setFromPoints(pts)
    const strong = r % 50 === 0
    ringsGroup.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: strong ? '#34435a' : '#1f2a38' })))
  }
  // heading line down the x axis
  const axis = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, -1.75), new THREE.Vector3(100, 0, -1.75)])
  ringsGroup.add(new THREE.Line(axis, new THREE.LineBasicMaterial({ color: '#1f2a38' })))

  // ego car outline: nuScenes ego frame sits at the rear axle center at ground level
  const ego = new THREE.BoxGeometry(4.1, 1.85, 1.55)
  ego.translate(1.25, 0, 0.775 - 1.75 + 0.3)
  const edges = new THREE.EdgesGeometry(ego)
  egoGroup.add(new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: COLORS.ego, transparent: true, opacity: 0.7 })))
}

function setSensors(f: Frame) {
  sensorsGroup.clear()
  const d = f.detail
  const mk = (t: number[], color: string, size: number) => {
    const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(t[0], t[1], t[2])])
    sensorsGroup.add(new THREE.Points(g, new THREE.PointsMaterial({ size, color, sizeAttenuation: false })))
  }
  mk(d.lidar.translation, COLORS.lidar, 9)
  for (const r of d.radars) {
    mk(r.translation, COLORS.radar, 7)
    // radar boresight: a short line in the sensor's facing direction
    const yaw = (r.yaw_deg * Math.PI) / 180
    const g = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(r.translation[0], r.translation[1], r.translation[2]),
      new THREE.Vector3(r.translation[0] + Math.cos(yaw) * 1.2, r.translation[1] + Math.sin(yaw) * 1.2, r.translation[2]),
    ])
    sensorsGroup.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: COLORS.radar, transparent: true, opacity: 0.7 })))
  }
  for (const c of d.cameras) {
    mk(c.translation, COLORS.camera, 6)
    // frustum: four rays from the optical center to the image corners at 1.5 m
    const m = c.cam_to_ref
    const K = c.intrinsic
    const depth = 1.5
    const corners = [
      [0, 0], [c.width, 0], [c.width, c.height], [0, c.height],
    ].map(([u, v]) => {
      const x = ((u - K[0][2]) / K[0][0]) * depth
      const y = ((v - K[1][2]) / K[1][1]) * depth
      return new THREE.Vector3(
        m[0][0] * x + m[0][1] * y + m[0][2] * depth + m[0][3],
        m[1][0] * x + m[1][1] * y + m[1][2] * depth + m[1][3],
        m[2][0] * x + m[2][1] * y + m[2][2] * depth + m[2][3],
      )
    })
    const o = new THREE.Vector3(m[0][3], m[1][3], m[2][3])
    const pts: THREE.Vector3[] = []
    for (let i = 0; i < 4; i++) {
      pts.push(o, corners[i], corners[i], corners[(i + 1) % 4])
    }
    const g = new THREE.BufferGeometry().setFromPoints(pts)
    sensorsGroup.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: COLORS.camera, transparent: true, opacity: 0.35 })))
  }
}

function setLidar(f: Frame) {
  const n = f.lidar.length / LIDAR_STRIDE
  const pos = new Float32Array(n * 3)
  const col = new Float32Array(n * 3)
  for (let i = 0; i < n; i++) {
    const x = f.lidar[i * LIDAR_STRIDE], y = f.lidar[i * LIDAR_STRIDE + 1], z = f.lidar[i * LIDAR_STRIDE + 2]
    pos[i * 3] = x
    pos[i * 3 + 1] = y
    pos[i * 3 + 2] = z
    let c: [number, number, number]
    if (layers.lidarColor === 'intensity') c = intensityColor(f.lidar[i * LIDAR_STRIDE + 3])
    else if (layers.lidarColor === 'distance') c = depthColor(Math.hypot(x, y))
    else c = heightColor(z)
    col[i * 3] = srgbToLinear(c[0] / 255)
    col[i * 3 + 1] = srgbToLinear(c[1] / 255)
    col[i * 3 + 2] = srgbToLinear(c[2] / 255)
  }
  lidarGeom.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  lidarGeom.setAttribute('color', new THREE.BufferAttribute(col, 3))
}

function setRadar(f: Frame) {
  const n = f.radar.length / RADAR_STRIDE
  const pos = new Float32Array(n * 3)
  const vel = new Float32Array(n * 6)
  for (let i = 0; i < n; i++) {
    const b = i * RADAR_STRIDE
    const x = f.radar[b], y = f.radar[b + 1], z = f.radar[b + 2]
    pos.set([x, y, z], i * 3)
    // 0.5 s of compensated velocity, so 10 m/s reads as a 5 m streak
    vel.set([x, y, z, x + f.radar[b + 3] * 0.5, y + f.radar[b + 4] * 0.5, z], i * 6)
  }
  radarGeom.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  radarVelGeom.setAttribute('position', new THREE.BufferAttribute(vel, 3))
}

function setBoxes(f: Frame) {
  const anns = f.detail.annotations
  const pos = new Float32Array(anns.length * BOX_EDGES.length * 6)
  const col = new Float32Array(anns.length * BOX_EDGES.length * 6)
  const color = new THREE.Color()
  let k = 0
  for (const a of anns) {
    const corners = boxCorners(a)
    color.set(categoryColor(a.category))
    const dim = state.hoveredAnnotation && state.hoveredAnnotation !== a.token ? 0.35 : 1
    for (const [i, j] of BOX_EDGES) {
      pos.set(corners[i], k)
      pos.set(corners[j], k + 3)
      for (let q = 0; q < 2; q++) col.set([color.r * dim, color.g * dim, color.b * dim], k + q * 3)
      k += 6
    }
  }
  boxGeom.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  boxGeom.setAttribute('color', new THREE.BufferAttribute(col, 3))
}

function setPath(f: Frame) {
  const pts = f.detail.trajectory.map((t) => new THREE.Vector3(t.position[0], t.position[1], t.position[2] - 1.75 + 0.05))
  pathGeom.setFromPoints(pts)
  pathDotsGeom.setFromPoints(pts)
}

function applyLayers() {
  lidar.visible = layers.lidar
  radar.visible = layers.radar
  radarVel.visible = layers.radar && layers.radarVelocity
  boxes.visible = layers.boxes
  pathGroup.visible = layers.trajectory
  sensorsGroup.visible = layers.sensors
  ringsGroup.visible = layers.rings
  egoGroup.visible = layers.sensors || layers.rings
  lidarMat.size = layers.pointSize
}

// ----- view presets -----

type Preset = 'chase' | 'top' | 'side'
const preset = ref<Preset>('chase')
function setView(p: Preset) {
  preset.value = p
  if (!controls) return
  controls.target.set(8, 0, 0)
  if (p === 'chase') camera.position.set(-18, -13, 11)
  else if (p === 'top') {
    controls.target.set(0, 0, 0)
    camera.position.set(0.01, 0, 90)
  } else camera.position.set(6, -45, 6)
  controls.update()
}

// ----- lifecycle -----

function resize() {
  const el = host.value
  if (!el || !renderer) return
  const w = el.clientWidth, h = el.clientHeight
  renderer.setSize(w, h, false)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
}

let ro: ResizeObserver | null = null
onMounted(() => {
  const el = host.value!
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio))
  el.appendChild(renderer.domElement)
  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.12
  controls.maxDistance = 300
  controls.minDistance = 2
  controls.maxPolarAngle = Math.PI / 2 - 0.02
  buildStatic()
  setView('chase')
  resize()
  ro = new ResizeObserver(resize)
  ro.observe(el)
  const loop = () => {
    controls!.update()
    renderer!.render(scene, camera)
    raf = requestAnimationFrame(loop)
  }
  loop()
  if (frame.value) update(frame.value)
})
onUnmounted(() => {
  cancelAnimationFrame(raf)
  ro?.disconnect()
  controls?.dispose()
  renderer?.dispose()
})

function update(f: Frame) {
  setLidar(f)
  setRadar(f)
  setBoxes(f)
  setPath(f)
  setSensors(f)
  applyLayers()
}

watch(frame, (f) => f && update(f))
watch(() => layers.lidarColor, () => frame.value && setLidar(frame.value))
watch(() => state.hoveredAnnotation, () => frame.value && setBoxes(frame.value))
watch(layers, applyLayers)
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
      <div class="legend" v-if="frame">
        <span><i class="swatch" :style="{ background: COLORS.lidar }"></i>Lidar, {{ frame.detail.lidar.nbr_points.toLocaleString() }} points</span>
        <span><i class="swatch" :style="{ background: COLORS.radar, borderRadius: '50%' }"></i>Radar, {{ frame.radar.length / RADAR_STRIDE }} returns from {{ frame.detail.radars.length }} sensors</span>
        <span class="muted">Drag to orbit, right-drag to pan, scroll to zoom</span>
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
  font-variant-numeric: tabular-nums;
}
.legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
@media (max-width: 1300px) {
  .legend .muted {
    display: none;
  }
}
</style>
