import { reactive, shallowRef, watch } from 'vue'
import { api, type Frame, type SceneDetail, type SceneSummary } from './api'

export type LidarColorMode = 'height' | 'intensity' | 'distance'

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
  hoveredAnnotation: null as string | null,
})

/** Current frame. shallowRef because the typed arrays are large and never mutate. */
export const frame = shallowRef<Frame | null>(null)

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

/** URL hash mirrors the view: #scene-0061/12/CAM_FRONT (scene, keyframe, open camera). */
function readHash() {
  const [name, index, cam] = location.hash.replace(/^#\/?/, '').split('/')
  return { name: name || null, index: index ? Number(index) - 1 : 0, cam: cam || null }
}

function writeHash() {
  const f = frame.value
  if (!f) return
  const parts = [f.detail.scene_name, String(f.detail.index + 1)]
  if (state.lightboxCamera) parts.push(state.lightboxCamera)
  const next = '#' + parts.join('/')
  if (location.hash !== next) history.replaceState(null, '', next)
}

watch([frame, () => state.lightboxCamera], writeHash)

export async function loadScenes() {
  state.scenes = await api.scenes()
  if (!state.scenes.length || state.scene) return
  const h = readHash()
  const scene = state.scenes.find((s) => s.name === h.name) ?? state.scenes[0]
  state.lightboxCamera = h.cam
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
