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

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${url}`)
  return r.json()
}

async function getFloat32(url: string): Promise<Float32Array> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${url}`)
  return new Float32Array(await r.arrayBuffer())
}

export const api = {
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
}
