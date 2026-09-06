import { reactive, shallowRef, watch } from 'vue'
import { api, type DepthFrame, type Frame, type FusionSource, type FusionStatus, type SceneDepthSummary, type SceneDetail, type SceneSplatStatus, type SceneSummary, type SplatStatus } from './api'

export type LidarColorMode = 'height' | 'intensity' | 'distance'
export type ViewMode = 'explore' | 'depth' | 'fusion' | 'splat'
export const VIEW_MODES: ViewMode[] = ['explore', 'depth', 'fusion', 'splat']
export type FusionShading = 'photo' | 'lit' | 'normals'
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

export const fusionLayers = reactive({
  source: 'camera' as FusionSource,
  voxel: 0.2,
  maskMoving: true,
  shading: 'photo' as FusionShading,
  wireframe: false,
  lidarOverlay: true,
  path: true,
  followEgo: true,
})

export const splatLayers = reactive({
  views: 6 as 6 | 18,
  posed: true,
  lidar: true,
  frustums: true,
  rings: true,
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
  loadingSplat: false,
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

/** Build status of the fused mesh for the current scene and settings. The
 *  backend builds on first request; we poll until it is ready. */
export const fusionStatus = shallowRef<FusionStatus | null>(null)
let fusionPoll = 0

async function pollFusion() {
  const id = ++fusionPoll
  const scene = state.scene
  if (!scene || state.view !== 'fusion') return
  const { source, voxel, maskMoving } = fusionLayers
  try {
    const s = await api.fusionStatus(scene.token, source, voxel, maskMoving)
    if (id !== fusionPoll) return
    fusionStatus.value = s
    if (s.state === 'running') window.setTimeout(() => id === fusionPoll && pollFusion(), 1500)
  } catch (e) {
    if (id === fusionPoll) fusionStatus.value = { key: '', state: 'error', message: String(e) }
  }
}

watch(
  () => [state.view, state.scene?.token, fusionLayers.source, fusionLayers.voxel, fusionLayers.maskMoving] as const,
  ([view]) => {
    fusionStatus.value = null
    if (view === 'fusion') pollFusion()
  },
  { immediate: true },
)

/** Which keyframes of the current scene have a Gaussian splat for the chosen
 *  options, and the build job if one runs. Splats are never built by
 *  looking at them: a build starts only from startSplatBuild, and the
 *  backend runs one at a time. We poll while a job is active. */
export const sceneSplat = shallowRef<SceneSplatStatus | null>(null)
export const splatBuildError = shallowRef<string | null>(null)
let sceneSplatPoll = 0

function jobActive(s: SceneSplatStatus | null) {
  return s?.job?.state === 'running' || s?.job?.state === 'cancelling'
}

async function pollSceneSplat() {
  const id = ++sceneSplatPoll
  const scene = state.scene
  if (!scene || state.view !== 'splat') return
  const { views, posed } = splatLayers
  try {
    const s = await api.sceneSplat(scene.token, views, posed)
    if (id !== sceneSplatPoll) return
    sceneSplat.value = s
    if (jobActive(s)) window.setTimeout(() => id === sceneSplatPoll && pollSceneSplat(), 1500)
  } catch (e) {
    if (id === sceneSplatPoll) splatBuildError.value = String(e)
  }
}

watch(
  () => [state.view, state.scene?.token, splatLayers.views, splatLayers.posed] as const,
  ([view]) => {
    sceneSplat.value = null
    splatBuildError.value = null
    if (view === 'splat') pollSceneSplat()
  },
  { immediate: true },
)

/** Build the splats the scene is missing, or only the current keyframe's. */
export async function startSplatBuild(scope: 'scene' | 'keyframe') {
  const scene = state.scene
  const f = frame.value
  if (!scene || !f) return
  const { views, posed } = splatLayers
  splatBuildError.value = null
  try {
    sceneSplat.value = scope === 'scene' ? await api.buildSceneSplat(scene.token, views, posed) : await api.buildSampleSplat(f.detail.token, views, posed)
  } catch (e) {
    splatBuildError.value = String(e)
  }
  pollSceneSplat()
}

export async function cancelSplatBuild() {
  try {
    await api.cancelSplat()
  } catch (e) {
    splatBuildError.value = String(e)
  }
  pollSceneSplat()
}

/** The current keyframe's splat: its stats when built, else its state. */
export const splatStatus = shallowRef<SplatStatus | null>(null)
let splatRequest = 0

watch(
  () => [state.view, frame.value?.detail.token, sceneSplat.value] as const,
  async ([view, token, scene]) => {
    const id = ++splatRequest
    const kf = scene?.keyframes.find((k) => k.token === token)
    if (view !== 'splat' || !token || !scene || !kf) {
      splatStatus.value = null
      return
    }
    if (!kf.ready) {
      const job = scene.job
      const inJob = jobActive(scene) && job!.keys.includes(kf.key)
      const where = !inJob ? 'missing' : job!.current?.key === kf.key ? 'running' : 'queued'
      splatStatus.value = { key: kf.key, state: where, progress: job?.progress, message: job?.message }
      return
    }
    if (splatStatus.value?.key === kf.key && splatStatus.value.state === 'ready') return
    try {
      const s = await api.splatStatus(token, scene.views, scene.posed)
      if (id === splatRequest) splatStatus.value = s
    } catch (e) {
      if (id === splatRequest) splatStatus.value = { key: kf.key, state: 'error', message: String(e) }
    }
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
 *  camera), or #depth/…, #fusion/…, #splat/… for the other views. */
function readHash() {
  const parts = location.hash.replace(/^#\/?/, '').split('/')
  const view: ViewMode = (VIEW_MODES as string[]).includes(parts[0]) && parts[0] !== 'explore' ? (parts[0] as ViewMode) : 'explore'
  if (view !== 'explore') parts.shift()
  const [name, index, cam] = parts
  return { view, name: name || null, index: index ? Number(index) - 1 : 0, cam: cam || null }
}

function writeHash() {
  const f = frame.value
  if (!f) return
  const parts = [f.detail.scene_name, String(f.detail.index + 1)]
  if (state.view !== 'explore') parts.unshift(state.view)
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
      const busy = state.loadingFrame || (state.view === 'splat' && state.loadingSplat)
      if (!busy) loadFrame(f.detail.next)
    }, 1000 / fps)
  },
)
