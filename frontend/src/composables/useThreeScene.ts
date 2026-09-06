import { onMounted, onUnmounted, ref, shallowRef, type Ref } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { COLORS } from '../geometry'

export type ViewPreset = 'chase' | 'top' | 'side'

/** Ground level in the ego frame. The nuScenes ego origin is the rear axle
 *  centre projected onto the road, so the road is at z = 0; the lidar sweeps
 *  put it between -0.4 and 0 m. Rings sit a little lower to avoid z-fighting. */
export const GROUND_Z = -0.08

/** Shared Three.js scaffolding for views drawn in the nuScenes ego frame:
 *  x forward, y left, z up. Owns the renderer, orbit controls, resize, the
 *  render loop, and the static ego car and range rings. Disposes everything
 *  on unmount so switching views frees the GPU resources. */
export function useThreeScene(host: Ref<HTMLElement | null>) {
  const scene = new THREE.Scene()
  scene.background = new THREE.Color('#0f1620')
  const camera = new THREE.PerspectiveCamera(50, 1, 0.5, 600)
  camera.up.set(0, 0, 1)

  const rings = new THREE.Group()
  const ego = new THREE.Group()
  scene.add(rings, ego)
  buildRings(rings)
  buildEgo(ego)

  let renderer: THREE.WebGLRenderer | null = null
  let controls: OrbitControls | null = null
  const controlsRef = shallowRef<OrbitControls | null>(null)
  let raf = 0
  let ro: ResizeObserver | null = null

  const preset = ref<ViewPreset>('chase')

  function setView(p: ViewPreset) {
    preset.value = p
    if (!controls) return
    controls.target.set(8, 0, 0)
    if (p === 'chase') camera.position.set(-18, -13, 11)
    else if (p === 'top') {
      controls.target.set(0, 0, 0)
      camera.position.set(-0.01, 0, 90) // tiny -x offset so forward points up the screen
    } else camera.position.set(6, -45, 6)
    controls.update()
  }

  function resize() {
    const el = host.value
    if (!el || !renderer) return
    renderer.setSize(el.clientWidth, el.clientHeight, false)
    camera.aspect = el.clientWidth / Math.max(1, el.clientHeight)
    camera.updateProjectionMatrix()
  }

  onMounted(() => {
    const el = host.value!
    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio))
    el.appendChild(renderer.domElement)
    controls = new OrbitControls(camera, renderer.domElement)
    controlsRef.value = controls
    controls.enableDamping = true
    controls.dampingFactor = 0.12
    controls.maxDistance = 300
    controls.minDistance = 2
    controls.maxPolarAngle = Math.PI / 2 - 0.02
    setView(preset.value)
    resize()
    ro = new ResizeObserver(resize)
    ro.observe(el)
    const loop = () => {
      controls!.update()
      renderer!.render(scene, camera)
      raf = requestAnimationFrame(loop)
    }
    loop()
  })

  onUnmounted(() => {
    cancelAnimationFrame(raf)
    ro?.disconnect()
    controls?.dispose()
    scene.traverse((o) => {
      const m = o as THREE.Mesh
      m.geometry?.dispose?.()
      const mat = m.material as THREE.Material | THREE.Material[] | undefined
      if (Array.isArray(mat)) mat.forEach((x) => x.dispose())
      else mat?.dispose?.()
    })
    scene.clear()
    renderer?.dispose()
    renderer?.forceContextLoss()
    renderer?.domElement.remove()
    renderer = null
  })

  return { scene, camera, controls: controlsRef, rings, ego, preset, setView }
}

function buildRings(group: THREE.Group) {
  for (let r = 10; r <= 100; r += 10) {
    const pts: THREE.Vector3[] = []
    for (let i = 0; i <= 128; i++) {
      const a = (i / 128) * Math.PI * 2
      pts.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, GROUND_Z))
    }
    const g = new THREE.BufferGeometry().setFromPoints(pts)
    group.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: r % 50 === 0 ? '#34435a' : '#1f2a38' })))
  }
  const axis = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, GROUND_Z), new THREE.Vector3(100, 0, GROUND_Z)])
  group.add(new THREE.Line(axis, new THREE.LineBasicMaterial({ color: '#1f2a38' })))
}

/** Outline of the ego car in its own frame. Renault Zoe footprint: 4.1 m
 *  long, 1.85 m wide, body from 0.25 m to 1.55 m above the road, rear axle
 *  1.25 m behind the car's centre. */
export function egoOutline(opacity = 0.7): THREE.LineSegments {
  const box = new THREE.BoxGeometry(4.1, 1.85, 1.3)
  box.translate(1.25, 0, 0.9)
  return new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({ color: COLORS.ego, transparent: true, opacity }))
}

function buildEgo(group: THREE.Group) {
  group.add(egoOutline())
}

/** Replace a BufferGeometry's position (and optional color) attributes. */
export function setPoints(geom: THREE.BufferGeometry, pos: Float32Array, col?: Float32Array) {
  geom.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  if (col) geom.setAttribute('color', new THREE.BufferAttribute(col, 3))
  geom.computeBoundingSphere()
}
