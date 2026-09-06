import { reactive, shallowRef, watch } from 'vue'
import { api, type DepthFrame, type Frame, type SceneDepthSummary, type SceneDetail, type SceneSummary } from './api'

export type LidarColorMode = 'height' | 'intensity' | 'distance'
export type ViewMode = 'explore' | 'depth'
export type DepthTileMode = 'wipe' | 'depth' | 'error'
export type DepthCloudColor = 'photo' | 'camera' | 'error'

export const depthLayers = reactive({
  tile: 'wipe' as DepthTileMode,
  wipe: 0.5,
  prediction: true,
  lidar: true,
  cloudColor: 'photo' as DepthCloudColor,
  pointSize: 2.2,
  maxRange: 60,
  cameras: {} as Record<string, boolean>,
})

export const layers = reactive({
  lidar: true,
  radar: true,
  radarVelocity: true,
  boxes: true,
  trajectory: true,
  sensors: true,
  rings: true,
  lidarColor: 'height' as LidarColorMode,
  pointSize: 1.6,
  overlayLidar: false,
  overlayRadar: true,
  overlayBoxes: true,
})

export const state = reactive({
  scenes: [] as SceneSummary[],
  scene: null as SceneDetail | null,
  loadingScene: false,
  loadingFrame: false,
  error: null as string | null,
  playing: false,
  fps: 2,
  lightboxCamera: null as string | null,
  scenePickerOpen: false,
  hoveredAnnotation: null as string | null,
  view: 'explore' as ViewMode,
  loadingDepth: false,
  depthError: null as string | null,
})

/** Current frame. shallowRef because the typed arrays are large and never mutate. */
export const frame = shallowRef<Frame | null>(null)

/** Depth Anything output for the current frame, loaded only in the depth view. */
export const depth = shallowRef<DepthFrame | null>(null)

const depthCache = new Map<string, Promise<DepthFrame>>()

function fetchDepth(token: string): Promise<DepthFrame> {
  let p = depthCache.get(token)
  if (!p) {
    p = api.depth(token)
    depthCache.set(token, p)
    p.catch(() => depthCache.delete(token))
  }
  return p
}

let depthRequest = 0

async function loadDepth(token: string, next: string | null) {
  const id = ++depthRequest
  state.loadingDepth = true
  try {
    const d = await fetchDepth(token)
    if (id !== depthRequest) return
    depth.value = d
    state.depthError = null
    if (next) fetchDepth(next)
  } catch (e) {
    if (id === depthRequest) state.depthError = String(e)
  } finally {
    if (id === depthRequest) state.loadingDepth = false
  }
}

watch(
  () => [state.view, frame.value] as const,
  ([view, f]) => {
    if (view !== 'depth' || !f) return
    if (depth.value?.detail.token !== f.detail.token) loadDepth(f.detail.token, f.detail.next)
  },
  { immediate: true },
)

/** Per-scene depth error, keyed by scene token. Filled lazily in the depth
 *  view: the current scene first, then the others one at a time so the
 *  backend is never asked to run inference for several scenes at once. */
export const depthScenes = reactive<Record<string, SceneDepthSummary>>({})
const depthScenesPending = new Set<string>()

async function loadDepthScenes() {
  const current = state.scene?.token
  const order = [...state.scenes].sort((a, b) => (a.token === current ? -1 : b.token === current ? 1 : 0))
  for (const s of order) {
    if (state.view !== 'depth') return
    if (depthScenes[s.token] || depthScenesPending.has(s.token)) continue
    depthScenesPending.add(s.token)
    try {
      depthScenes[s.token] = await api.sceneDepth(s.token)
    } catch {
      // leave it missing; the UI simply shows no badge for this scene
    } finally {
      depthScenesPending.delete(s.token)
    }
  }
}

watch(
  () => [state.view, state.scene?.token, state.scenes.length] as const,
  ([view]) => {
    if (view === 'depth') loadDepthScenes()
  },
  { immediate: true },
)

const frameCache = new Map<string, Promise<Frame>>()

function fetchFrame(token: string): Promise<Frame> {
  let p = frameCache.get(token)
  if (!p) {
    p = api.frame(token)
    frameCache.set(token, p)
    p.catch(() => frameCache.delete(token))
  }
  return p
}

let frameRequest = 0

export async function loadFrame(token: string) {
  const id = ++frameRequest
  state.loadingFrame = true
  try {
    const f = await fetchFrame(token)
    if (id !== frameRequest) return
    frame.value = f
    state.error = null
    if (f.detail.next) fetchFrame(f.detail.next)
  } catch (e) {
    if (id === frameRequest) state.error = String(e)
  } finally {
    if (id === frameRequest) state.loadingFrame = false
  }
}

export async function loadScene(token: string, index = 0) {
  if (state.scene?.token === token) return
  state.playing = false
  state.loadingScene = true
  try {
    const detail = await api.scene(token)
    state.scene = detail
    const start = detail.samples[Math.min(detail.samples.length - 1, Math.max(0, index || 0))]
    await loadFrame(start.token)
  } catch (e) {
    state.error = String(e)
  } finally {
    state.loadingScene = false
  }
}

/** URL hash mirrors the view: #scene-0061/12/CAM_FRONT (scene, keyframe, open
 *  camera), or #depth/scene-0061/12 for the depth view. */
function readHash() {
  const parts = location.hash.replace(/^#\/?/, '').split('/')
  const view: ViewMode = parts[0] === 'depth' ? 'depth' : 'explore'
  if (view === 'depth') parts.shift()
  const [name, index, cam] = parts
  return { view, name: name || null, index: index ? Number(index) - 1 : 0, cam: cam || null }
}

function writeHash() {
  const f = frame.value
  if (!f) return
  const parts = [f.detail.scene_name, String(f.detail.index + 1)]
  if (state.view === 'depth') parts.unshift('depth')
  else if (state.lightboxCamera) parts.push(state.lightboxCamera)
  const next = '#' + parts.join('/')
  if (location.hash !== next) history.replaceState(null, '', next)
}

watch([frame, () => state.lightboxCamera, () => state.view], writeHash)

export async function loadScenes() {
  state.scenes = await api.scenes()
  if (!state.scenes.length || state.scene) return
  const h = readHash()
  const scene = state.scenes.find((s) => s.name === h.name) ?? state.scenes[0]
  state.view = h.view
  state.lightboxCamera = h.view === 'explore' ? h.cam : null
  await loadScene(scene.token, h.index)
}

export function stepFrame(delta: number) {
  const f = frame.value
  if (!f || !state.scene) return
  const i = Math.min(state.scene.samples.length - 1, Math.max(0, f.detail.index + delta))
  const target = state.scene.samples[i]
  if (target.token !== f.detail.token) loadFrame(target.token)
}

export function goToIndex(i: number) {
  if (!state.scene) return
  const target = state.scene.samples[Math.min(state.scene.samples.length - 1, Math.max(0, i))]
  if (target && target.token !== frame.value?.detail.token) loadFrame(target.token)
}

let timer: number | null = null
watch(
  () => [state.playing, state.fps] as const,
  ([playing, fps]) => {
    if (timer) window.clearInterval(timer)
    timer = null
    if (!playing) return
    timer = window.setInterval(() => {
      const f = frame.value
      if (!f) return
      if (!f.detail.next) {
        goToIndex(0)
        return
      }
      if (!state.loadingFrame) loadFrame(f.detail.next)
    }, 1000 / fps)
  },
)
