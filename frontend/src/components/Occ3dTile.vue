<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, OCC3D_CAMERA_BIT, OCC3D_CLASS_MASK, OCC3D_FREE, type CameraFrame } from '../api'
import { channelLabel, coverTransform, projectPoint } from '../geometry'
import { occ3d, occ3dLayers, sceneOcc3d } from '../state'

const props = defineProps<{ cam: CameraFrame }>()

const box = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const shown = ref(api.imageUrl(props.cam.sd_token, 800))

watch(
  () => props.cam.sd_token,
  (tok) => {
    const url = api.imageUrl(tok, 800)
    const img = new Image()
    img.onload = () => {
      if (props.cam.sd_token === tok) shown.value = url
    }
    img.src = url
  },
)

const grid = computed(() => sceneOcc3d.value?.grid ?? { shape: [200, 200, 16], voxel: 0.4, origin: [-40, -40, -1] })

/** Cells of the depth buffer, in image pixels. Coarser than the image so a
 *  frame of 30,000 voxels rasterises in a few milliseconds. */
const CELL = 6

/** Camera-visible occupied voxels rendered into a coarse depth buffer, each
 *  as a square the size of a voxel at its distance, so the nearest voxel
 *  wins at every cell and the photo shows through one translucent layer. */
function draw() {
  const c = canvas.value, el = box.value, o = occ3d.value
  if (!c || !el) return
  const dpr = Math.min(2, window.devicePixelRatio || 1)
  c.width = el.clientWidth * dpr
  c.height = el.clientHeight * dpr
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, c.width, c.height)
  if (!o || !occ3dLayers.overlay || !sceneOcc3d.value) return
  const cam = props.cam
  const fit = coverTransform(cam.width, cam.height, c.width, c.height)
  const { shape, voxel, origin } = grid.value
  const [, ny, nz] = shape
  const half = voxel / 2
  const zMax = Math.min(nz, occ3dLayers.maxLayer)
  const hidden = occ3dLayers.hidden
  const bytes = o.grid
  const f = cam.intrinsic[0][0]

  const cw = Math.ceil(cam.width / CELL), ch = Math.ceil(cam.height / CELL)
  const depth = new Float32Array(cw * ch).fill(Infinity)
  const cls = new Uint8Array(cw * ch)
  for (let i = 0; i < bytes.length; i++) {
    const b = bytes[i]
    const k = b & OCC3D_CLASS_MASK
    if (k === OCC3D_FREE || hidden[k] || !(b & OCC3D_CAMERA_BIT)) continue
    const iz = i % nz
    if (iz >= zMax) continue
    const iy = ((i - iz) / nz) % ny
    const ix = (i - iz - iy * nz) / (ny * nz)
    const p = projectPoint(cam, origin[0] + ix * voxel + half, origin[1] + iy * voxel + half, origin[2] + iz * voxel + half + occ3dLayers.lift)
    if (!p) continue
    const r = (f * voxel) / p.depth / 2
    const u0 = Math.max(0, Math.floor((p.u - r) / CELL)), u1 = Math.min(cw - 1, Math.floor((p.u + r) / CELL))
    const v0 = Math.max(0, Math.floor((p.v - r) / CELL)), v1 = Math.min(ch - 1, Math.floor((p.v + r) / CELL))
    for (let v = v0; v <= v1; v++) {
      for (let u = u0; u <= u1; u++) {
        const j = v * cw + u
        if (p.depth < depth[j]) {
          depth[j] = p.depth
          cls[j] = k
        }
      }
    }
  }

  // one pixel per cell, scaled up without smoothing so the cells stay crisp
  const rgb = sceneOcc3d.value.classes.map((k) => [parseInt(k.color.slice(1, 3), 16), parseInt(k.color.slice(3, 5), 16), parseInt(k.color.slice(5, 7), 16)])
  const img = new ImageData(cw, ch)
  const alpha = Math.round(255 * occ3dLayers.overlayAlpha)
  for (let j = 0; j < cw * ch; j++) {
    if (depth[j] === Infinity) continue
    const [r, g, b] = rgb[cls[j]]
    img.data[j * 4] = r
    img.data[j * 4 + 1] = g
    img.data[j * 4 + 2] = b
    img.data[j * 4 + 3] = alpha
  }
  const off = offscreen(cw, ch)
  off.getContext('2d')!.putImageData(img, 0, 0)
  ctx.imageSmoothingEnabled = false
  ctx.drawImage(off, 0, 0, cw, ch, fit.offsetX, fit.offsetY, cw * CELL * fit.scale, ch * CELL * fit.scale)
}

let scratch: HTMLCanvasElement | null = null
function offscreen(w: number, h: number): HTMLCanvasElement {
  if (!scratch) scratch = document.createElement('canvas')
  if (scratch.width !== w || scratch.height !== h) {
    scratch.width = w
    scratch.height = h
  }
  return scratch
}

let ro: ResizeObserver | null = null
watch(
  () => [occ3d.value, sceneOcc3d.value, occ3dLayers.overlay, occ3dLayers.overlayAlpha, occ3dLayers.maxLayer, occ3dLayers.lift, { ...occ3dLayers.hidden }, props.cam] as const,
  draw,
  { flush: 'post' },
)
onMounted(() => {
  ro = new ResizeObserver(draw)
  if (box.value) ro.observe(box.value)
  draw()
})
onUnmounted(() => ro?.disconnect())
</script>

<template>
  <div class="tile">
    <div class="image" ref="box">
      <img class="photo" :src="shown" :alt="cam.channel" decoding="async" />
      <canvas ref="canvas" class="overlay"></canvas>
      <span class="label">{{ channelLabel(cam.channel) }}</span>
    </div>
  </div>
</template>

<style scoped>
.tile {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}
.image {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  border-radius: var(--radius);
  background: #000;
  aspect-ratio: 16 / 9;
}
.image img,
.overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.overlay {
  pointer-events: none;
}
.label {
  position: absolute;
  left: 8px;
  top: 6px;
  font-size: 11.5px;
  font-weight: 600;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
}
</style>
