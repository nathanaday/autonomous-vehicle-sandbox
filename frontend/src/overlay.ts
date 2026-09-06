import { LIDAR_STRIDE, RADAR_STRIDE, type CameraFrame, type Frame } from './api'
import { BOX_EDGES, boxCorners, categoryColor, COLORS, depthColor, projectLoose, projectPoint } from './geometry'

export interface OverlayOptions {
  lidar: boolean
  radar: boolean
  boxes: boolean
  /** canvas pixels per image pixel */
  scale: number
  /** canvas position of the image's top-left corner, for cropped tiles */
  offsetX?: number
  offsetY?: number
  /** every nth lidar point; 1 draws all */
  lidarStep?: number
  highlight?: string | null
}

/** Draw the projected sensor data for one camera onto a 2D canvas whose
 *  size is the image size times `scale`. */
export function drawOverlay(ctx: CanvasRenderingContext2D, cam: CameraFrame, frame: Frame, o: OverlayOptions) {
  const s = o.scale
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height)
  ctx.setTransform(1, 0, 0, 1, o.offsetX ?? 0, o.offsetY ?? 0)

  if (o.lidar) {
    const step = (o.lidarStep ?? 1) * LIDAR_STRIDE
    const r = Math.max(1, 1.6 * s * 2)
    const pts = frame.lidar
    for (let i = 0; i < pts.length; i += step) {
      const p = projectPoint(cam, pts[i], pts[i + 1], pts[i + 2])
      if (!p) continue
      const [cr, cg, cb] = depthColor(p.depth)
      ctx.fillStyle = `rgb(${cr | 0},${cg | 0},${cb | 0})`
      ctx.fillRect(p.u * s - r / 2, p.v * s - r / 2, r, r)
    }
  }

  if (o.boxes) {
    ctx.lineWidth = Math.max(1, 1.2 * s * 2)
    for (const a of frame.detail.annotations) {
      const corners = boxCorners(a).map((c) => projectLoose(cam, c[0], c[1], c[2]))
      if (corners.some((c) => !c)) continue
      const inside = corners.some(
        (c) => c && c.u >= 0 && c.u < cam.width && c.v >= 0 && c.v < cam.height,
      )
      if (!inside) continue
      const hi = o.highlight === a.token
      ctx.strokeStyle = categoryColor(a.category)
      ctx.globalAlpha = hi ? 1 : 0.85
      ctx.lineWidth = hi ? Math.max(2, 2.4 * s * 2) : Math.max(1, 1.2 * s * 2)
      ctx.beginPath()
      for (const [i, j] of BOX_EDGES) {
        const p = corners[i]!, q = corners[j]!
        ctx.moveTo(p.u * s, p.v * s)
        ctx.lineTo(q.u * s, q.v * s)
      }
      ctx.stroke()
      // front face marker: fill the front face faintly so heading reads
      ctx.globalAlpha = 0.18
      ctx.fillStyle = categoryColor(a.category)
      ctx.beginPath()
      for (const idx of [0, 1, 5, 4]) {
        const p = corners[idx]!
        if (idx === 0) ctx.moveTo(p.u * s, p.v * s)
        else ctx.lineTo(p.u * s, p.v * s)
      }
      ctx.closePath()
      ctx.fill()
      ctx.globalAlpha = 1
    }
  }

  if (o.radar) {
    const pts = frame.radar
    const r = Math.max(3, 5 * s * 2)
    for (let i = 0; i < pts.length; i += RADAR_STRIDE) {
      const p = projectPoint(cam, pts[i], pts[i + 1], pts[i + 2])
      if (!p) continue
      ctx.beginPath()
      ctx.arc(p.u * s, p.v * s, r, 0, Math.PI * 2)
      ctx.fillStyle = COLORS.radar
      ctx.globalAlpha = 0.9
      ctx.fill()
      ctx.globalAlpha = 1
      ctx.lineWidth = Math.max(1, s * 2)
      ctx.strokeStyle = '#3a2a10'
      ctx.stroke()
      // velocity: draw the point 0.5 s later along its compensated velocity
      const vx = pts[i + 3], vy = pts[i + 4]
      if (Math.hypot(vx, vy) > 0.5) {
        const q = projectLoose(cam, pts[i] + vx * 0.5, pts[i + 1] + vy * 0.5, pts[i + 2])
        if (q) {
          ctx.beginPath()
          ctx.moveTo(p.u * s, p.v * s)
          ctx.lineTo(q.u * s, q.v * s)
          ctx.strokeStyle = COLORS.radar
          ctx.lineWidth = Math.max(1, 1.5 * s * 2)
          ctx.stroke()
        }
      }
    }
  }
}
