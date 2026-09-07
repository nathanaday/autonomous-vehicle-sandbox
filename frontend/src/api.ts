export type Mat4 = number[][]

export interface SceneSummary {
  token: string
  name: string
  description: string
  location: string
  date_captured: string
  vehicle: string
  logfile: string
  nbr_samples: number
  duration_s: number
  first_sample_token: string
  thumbnail_sd_token: string
  tags: string[]
  nbr_instances: number
  category_counts: Record<string, number>
  sweep_counts: Record<string, number>
  features: { depth: boolean; fusion: boolean; splat: boolean; gs3d: boolean; occ3d: boolean }
}

export interface SceneSample {
  token: string
  timestamp: number
  ego_translation: number[]
  ego_rotation: number[]
  nbr_annotations: number
}

export interface SensorInfo {
  channel: string
  modality: 'camera' | 'lidar' | 'radar'
  translation: number[]
  rotation: number[]
  camera_intrinsic: number[][]
  width: number
  height: number
  fileformat: string
}

export interface SceneDetail extends SceneSummary {
  samples: SceneSample[]
  sensors: SensorInfo[]
}

export interface CameraFrame {
  channel: string
  sd_token: string
  filename: string
  timestamp: number
  dt_ms: number
  width: number
  height: number
  intrinsic: number[][]
  translation: number[]
  rotation: number[]
  cam_to_ref: Mat4
  ref_to_cam: Mat4
}

export interface RadarFrame {
  channel: string
  sd_token: string
  filename: string
  timestamp: number
  dt_ms: number
  translation: number[]
  rotation: number[]
  yaw_deg: number
  nbr_points_raw: number
  nbr_points: number
}

export interface LidarFrame {
  channel: string
  sd_token: string
  filename: string
  timestamp: number
  dt_ms: number
  translation: number[]
  rotation: number[]
  nbr_points: number
}

export interface Annotation {
  token: string
  instance_token: string
  category: string
  attributes: string[]
  visibility: string
  center: number[]
  size: number[]
  yaw: number
  num_lidar_pts: number
  num_radar_pts: number
}

export interface TrajectoryPoint {
  token: string
  position: number[]
  yaw: number
  t_s: number
}

export interface FrameDetail {
  token: string
  scene_token: string
  scene_name: string
  index: number
  count: number
  timestamp: number
  t_s: number
  prev: string | null
  next: string | null
  ego_pose: { translation: number[]; rotation: number[]; ref_to_global: Mat4 }
  cameras: CameraFrame[]
  lidar: LidarFrame
  radars: RadarFrame[]
  annotations: Annotation[]
  trajectory: TrajectoryPoint[]
}

/** Lidar: 5 floats per point (x y z intensity ring). Radar: 8 floats
 *  (x y z vx vy rcs dyn_prop channel). Both in the reference ego frame. */
export interface Frame {
  detail: FrameDetail
  lidar: Float32Array
  radar: Float32Array
}

export const LIDAR_STRIDE = 5
export const RADAR_STRIDE = 8

export interface DepthModelInfo {
  model: string
  output: string
}

export interface DepthMetrics {
  n_lidar: number
  abs_rel: number
  rmse: number
  delta1: number
}

export interface CameraDepthStats extends DepthMetrics {
  channel: string
  sd_token: string
  pred_shape: number[]
  scale: number
  shift: number
}

export interface DepthDetail {
  token: string
  model: DepthModelInfo
  cameras: CameraDepthStats[]
  overall: DepthMetrics
}

/** cloud: 7 floats per point (x y z r g b camera_index) in the reference ego
 *  frame. lidar: 5 floats per point (camera_index u v z_lidar z_pred). */
export interface DepthFrame {
  detail: DepthDetail
  cloud: Float32Array
  lidar: Float32Array
}

export interface SceneDepthFrame extends DepthMetrics {
  token: string
  cameras: Record<string, number>
}

export interface SceneDepthSummary {
  scene_token: string
  frames: SceneDepthFrame[]
  abs_rel: number
  rmse: number
  delta1: number
}

export type FusionSource = 'camera' | 'lidar'

export interface FusionPose {
  token: string
  ego_to_scene: Mat4
}

export interface FusionStatus {
  key: string
  state: 'ready' | 'missing' | 'error'
  message?: string
  scene_token?: string
  source?: FusionSource
  voxel?: number
  mask_moving?: boolean
  moving_instances?: number
  keyframes?: number
  views?: number
  vertices?: number
  triangles?: number
  raw_triangles?: number
  seconds?: number
  bounds_min?: number[]
  bounds_max?: number[]
  poses?: FusionPose[]
}

export interface SplatViewMeta {
  channel: string
  sample_token: string
  sd_token: string
  gaussian_fit_scale?: number
  gaussian_fit_rms_m?: number
  c2w?: Mat4
  lidar?: { n: number; abs_rel: number; delta1: number; median_scale_to_lidar: number; abs_rel_after_scale: number }
}

/** One keyframe's splat: its stats once computed, otherwise 'missing' with
 *  the compute command in the message. */
export interface SplatStatus {
  key: string
  state: 'ready' | 'missing' | 'error'
  message?: string
  sample_token?: string
  model?: string
  device?: string
  posed?: boolean
  process_res?: number[]
  views?: SplatViewMeta[]
  n_views?: number
  n_gaussians?: number
  n_gaussians_raw?: number
  sky_fraction?: number | null
  metric_scale_factor?: number | null
  pose?: { similarity_scale: number; rotation_error_deg: number[]; position_error_m: number[] } | null
  seconds?: { load: number; inference: number; total: number }
  ply_bytes?: number
}

export interface SceneSplatStatus {
  scene_token: string
  views: number
  posed: boolean
  keyframes: { token: string; key: string; ready: boolean }[]
  n_ready: number
  n_total: number
  message?: string
}

/** One trained splat of a whole scene (official 3DGS), with its stats and
 *  the per-keyframe ego poses in the scene frame. */
export interface Gs3dVariant {
  key: string
  label: string
  state: 'ready'
  scene_token: string
  scene_name: string
  images: 'kf' | 'sweeps'
  mask_moving: boolean
  depth_prior: boolean
  method: string
  iterations: number
  eval_holdout: boolean
  trainer_args: string[]
  n_images: number
  n_keyframe_images: number
  n_masked_images: number
  moving_instances: number
  n_points_init: number
  n_gaussians: number
  psnr: Record<string, number>
  gpu: string | null
  seconds: number
  ply_bytes: number
  poses: FusionPose[]
}

export interface SceneGs3dStatus {
  scene_token: string
  variants: Gs3dVariant[]
  message?: string
}

/** Which features have results in the cache for at least one scene. Each
 *  unlocks views; a view whose feature has nothing shows how to fetch its
 *  data bundle instead of its content. */
export type FeatureName = 'dataset' | 'depth' | 'fusion' | 'splat' | 'gs3d' | 'occ3d'
export interface FeatureInfo {
  present: boolean
  views: string[]
  make: string
}
export type Features = Record<FeatureName, FeatureInfo>

/** Occ3D-nuScenes semantic occupancy labels: a 200 x 200 x 16 grid of 0.4 m
 *  voxels in the ego frame, one class per voxel, with two visibility masks. */
export interface Occ3dClass {
  id: number
  name: string
  color: string
}

export interface Occ3dGridSpec {
  shape: number[]
  voxel: number
  origin: number[]
}

export interface SceneOcc3dStatus {
  scene_name: string
  keyframes: { token: string; ready: boolean; n_occupied: number }[]
  n_ready: number
  n_total: number
  grid: Occ3dGridSpec
  classes: Occ3dClass[]
  message?: string
}

export interface Occ3dStats {
  token: string
  n_occupied: number
  n_free: number
  n_lidar_visible: number
  n_camera_visible: number
  n_occupied_lidar_visible: number
  n_occupied_camera_visible: number
  class_counts: number[]
  class_counts_camera: number[]
  class_counts_lidar: number[]
  lidar: { n: number; n_in_grid: number; hit_occupied: number; hit_observed: number; ground_offset_m: number | null }
}

/** grid: one byte per voxel in x, y, z order with z fastest. Bits 0-4 hold
 *  the class id (17 = free), bit 5 is set when the lidar saw the voxel and
 *  bit 6 when a camera did. */
export interface Occ3dFrame {
  stats: Occ3dStats
  grid: Uint8Array
}

export const OCC3D_FREE = 17
export const OCC3D_CLASS_MASK = 31
export const OCC3D_LIDAR_BIT = 32
export const OCC3D_CAMERA_BIT = 64

export const DEPTH_CLOUD_STRIDE = 7
export const DEPTH_LIDAR_STRIDE = 5

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) {
    const body = await r.json().catch(() => null)
    throw new Error(body?.detail ?? `${r.status} ${url}`)
  }
  return r.json()
}

async function getFloat32(url: string): Promise<Float32Array> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${url}`)
  return new Float32Array(await r.arrayBuffer())
}

async function getBytes(url: string): Promise<Uint8Array> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${url}`)
  return new Uint8Array(await r.arrayBuffer())
}

export const api = {
  features: () => getJson<Features>('/api/features'),
  scenes: () => getJson<SceneSummary[]>('/api/scenes'),
  scene: (token: string) => getJson<SceneDetail>(`/api/scenes/${token}`),
  async frame(token: string): Promise<Frame> {
    const [detail, lidar, radar] = await Promise.all([
      getJson<FrameDetail>(`/api/samples/${token}`),
      getFloat32(`/api/samples/${token}/lidar.bin`),
      getFloat32(`/api/samples/${token}/radar.bin`),
    ])
    return { detail, lidar, radar }
  },
  imageUrl: (sdToken: string, width?: number) =>
    width ? `/api/image/${sdToken}?w=${width}` : `/api/image/${sdToken}`,
  async depth(token: string): Promise<DepthFrame> {
    const [detail, cloud, lidar] = await Promise.all([
      getJson<DepthDetail>(`/api/samples/${token}/depth`),
      getFloat32(`/api/samples/${token}/depthcloud.bin`),
      getFloat32(`/api/samples/${token}/depthlidar.bin`),
    ])
    return { detail, cloud, lidar }
  },
  sceneDepth: (token: string) => getJson<SceneDepthSummary>(`/api/scenes/${token}/depth`),
  fusionStatus: (token: string, source: FusionSource, voxel: number, mask: boolean) =>
    getJson<FusionStatus>(`/api/scenes/${token}/fusion?source=${source}&voxel=${voxel}&mask=${mask}`),
  fusionMeshUrl: (key: string) => `/api/fusion/${key}.ply`,
  splatStatus: (sampleToken: string, views: number, posed: boolean) =>
    getJson<SplatStatus>(`/api/samples/${sampleToken}/splat?views=${views}&posed=${posed}`),
  sceneSplat: (sceneToken: string, views: number, posed: boolean) =>
    getJson<SceneSplatStatus>(`/api/scenes/${sceneToken}/splat?views=${views}&posed=${posed}`),
  splatUrl: (key: string) => `/api/splat/${key}.ply`,
  sceneGs3d: (sceneToken: string) => getJson<SceneGs3dStatus>(`/api/scenes/${sceneToken}/gs3d`),
  gs3dUrl: (key: string) => `/api/gs3d/${key}.ply`,
  sceneOcc3d: (sceneToken: string) => getJson<SceneOcc3dStatus>(`/api/scenes/${sceneToken}/occ3d`),
  async occ3d(token: string): Promise<Occ3dFrame> {
    const [stats, grid] = await Promise.all([
      getJson<Occ3dStats>(`/api/samples/${token}/occ3d`),
      getBytes(`/api/samples/${token}/occ3d.bin`),
    ])
    return { stats, grid }
  },
  depthImageUrl: (sdToken: string, width?: number) =>
    width ? `/api/depth/${sdToken}.png?w=${width}` : `/api/depth/${sdToken}.png`,
}
