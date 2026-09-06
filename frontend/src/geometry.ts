import type { Annotation, CameraFrame, Mat4 } from './api'

// ----- colors -----------------------------------------------------------

export const COLORS = {
  lidar: '#9DD7FF',
  radar: '#FFB347',
  ego: '#FFFFFF',
  path: '#6C7A8C',
  camera: '#C9D3E0',
}

/** Category family -> box color. Keys match the prefix of nuScenes category names. */
export const CATEGORY_COLORS: Record<string, string> = {
  'human.pedestrian': '#FF7A6B',
  'vehicle.car': '#5FD3C4',
  'vehicle.truck': '#43B8E8',
  'vehicle.bus': '#43B8E8',
  'vehicle.construction': '#43B8E8',
  'vehicle.trailer': '#43B8E8',
  'vehicle.emergency': '#43B8E8',
  'vehicle.bicycle': '#C8A6FF',
  'vehicle.motorcycle': '#C8A6FF',
  'movable_object': '#E8D25A',
  'static_object': '#A5B3C4',
  animal: '#FF7A6B',
}

export function categoryColor(category: string): string {
  const key = Object.keys(CATEGORY_COLORS).find((k) => category.startsWith(k))
  return key ? CATEGORY_COLORS[key] : '#A5B3C4'
}

export function categoryLabel(category: string): string {
  const parts = category.split('.')
  const last = parts[parts.length - 1]
  return last.replace(/_/g, ' ')
}

/** Distance colormap for depth overlays: warm near, cool far. */
export function depthColor(d: number, dmax = 60): [number, number, number] {
  const t = Math.min(1, Math.max(0, d / dmax))
  // amber -> magenta -> blue
  const stops: [number, number, number][] = [
    [255, 190, 90],
    [255, 110, 120],
    [170, 100, 220],
    [80, 140, 255],
    [120, 220, 255],
  ]
  const s = t * (stops.length - 1)
  const i = Math.min(stops.length - 2, Math.floor(s))
  const f = s - i
  const a = stops[i], b = stops[i + 1]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
}

/** Height colormap for the 3D lidar view: dim ground, bright tops. */
export function heightColor(z: number): [number, number, number] {
  const t = Math.min(1, Math.max(0, (z + 2) / 6))
  const lo: [number, number, number] = [60, 90, 130]
  const hi: [number, number, number] = [200, 235, 255]
  return [lo[0] + (hi[0] - lo[0]) * t, lo[1] + (hi[1] - lo[1]) * t, lo[2] + (hi[2] - lo[2]) * t]
}

export function intensityColor(i: number): [number, number, number] {
  const t = Math.min(1, i / 120)
  return [70 + 185 * t, 110 + 130 * t, 160 + 95 * t]
}

// ----- projection -------------------------------------------------------

export interface Projected {
  u: number
  v: number
  depth: number
}

/** Project a point in the reference ego frame into camera pixels. Returns
 *  null when the point is behind the camera or outside the image. */
export function projectPoint(cam: CameraFrame, x: number, y: number, z: number): Projected | null {
  const m = cam.ref_to_cam
  const cx = m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3]
  const cy = m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3]
  const cz = m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3]
  if (cz < 0.5) return null
  const k = cam.intrinsic
  const u = (k[0][0] * cx + k[0][2] * cz) / cz
  const v = (k[1][1] * cy + k[1][2] * cz) / cz
  if (u < 0 || u >= cam.width || v < 0 || v >= cam.height) return null
  return { u, v, depth: cz }
}

/** Same as projectPoint but without the image-bounds test, for box edges. */
export function projectLoose(cam: CameraFrame, x: number, y: number, z: number): Projected | null {
  const m = cam.ref_to_cam
  const cx = m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3]
  const cy = m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3]
  const cz = m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3]
  if (cz < 0.5) return null
  const k = cam.intrinsic
  return { u: (k[0][0] * cx + k[0][2] * cz) / cz, v: (k[1][1] * cy + k[1][2] * cz) / cz, depth: cz }
}

/** Eight corners of an annotation box in the reference frame.
 *  Order: bottom 0-3 (front-left, front-right, back-right, back-left), top 4-7. */
export function boxCorners(a: Annotation): number[][] {
  const [w, l, h] = a.size
  const c = Math.cos(a.yaw), s = Math.sin(a.yaw)
  const [cx, cy, cz] = a.center
  const out: number[][] = []
  for (const dz of [-h / 2, h / 2]) {
    for (const [dx, dy] of [[l / 2, w / 2], [l / 2, -w / 2], [-l / 2, -w / 2], [-l / 2, w / 2]]) {
      out.push([cx + dx * c - dy * s, cy + dx * s + dy * c, cz + dz])
    }
  }
  return out
}

export const BOX_EDGES: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 0],
  [4, 5], [5, 6], [6, 7], [7, 4],
  [0, 4], [1, 5], [2, 6], [3, 7],
]

export function horizontalFovDeg(cam: { intrinsic: number[][]; width: number }): number {
  return (2 * Math.atan(cam.width / (2 * cam.intrinsic[0][0])) * 180) / Math.PI
}

export function mat4Position(m: Mat4): [number, number, number] {
  return [m[0][3], m[1][3], m[2][3]]
}

export function formatTimestamp(us: number): string {
  const d = new Date(us / 1000)
  const pad = (n: number, w = 2) => String(n).padStart(w, '0')
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(Math.floor((us % 1e6) / 1000), 3)} UTC`
}

const LOCATIONS: Record<string, string> = {
  'singapore-onenorth': 'Singapore, One North',
  'singapore-queenstown': 'Singapore, Queenstown',
  'singapore-hollandvillage': 'Singapore, Holland Village',
  'boston-seaport': 'Boston, Seaport',
}

export function formatLocation(loc: string): string {
  return LOCATIONS[loc] ?? loc
}

/** Fit an image of size (W,H) into a box of size (w,h) with object-fit: cover.
 *  Returns the scale and the top-left offset of the drawn image. */
export function coverTransform(W: number, H: number, w: number, h: number) {
  const scale = Math.max(w / W, h / H)
  return { scale, offsetX: (w - W * scale) / 2, offsetY: (h - H * scale) / 2 }
}

export function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}
