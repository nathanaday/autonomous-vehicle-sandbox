<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, DEPTH_LIDAR_STRIDE, type CameraFrame } from '../api'
import { channelLabel, coverTransform, errorColor } from '../geometry'
import { depth, depthLayers, state } from '../state'

const props = defineProps<{ cam: CameraFrame; index: number }>()

const stats = computed(() => depth.value?.detail.cameras.find((c) => c.channel === props.cam.channel) ?? null)
const box = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)

/** Both images swap only once the new pair has decoded, so stepping frames
 *  never shows a photo from one keyframe against depth from another. */
const shown = ref({ photo: api.imageUrl(props.cam.sd_token, 800), depth: null as string | null })
watch(
  () => depth.value,
  (d) => {
    const tok = props.cam.sd_token
    if (!d || !d.detail.cameras.some((c) => c.sd_token === tok)) return
    const photo = api.imageUrl(tok, 800), dep = api.depthImageUrl(tok, 800)
    let left = 2
    const done = () => {
      if (--left === 0 && props.cam.sd_token === tok) shown.value = { photo, depth: dep }
    }
    for (const url of [photo, dep]) {
      const img = new Image()
      img.onload = done
      img.onerror = done
      img.src = url
    }
  },
  { immediate: true },
)

const wipeStyle = computed(() => {
  if (depthLayers.tile === 'depth') return { clipPath: 'inset(0 0 0 0)' }
  if (depthLayers.tile === 'error') return { clipPath: 'inset(0 0 0 100%)' }
  return { clipPath: `inset(0 0 0 ${(depthLayers.wipe * 100).toFixed(2)}%)` }
})

function onMove(e: MouseEvent) {
  if (depthLayers.tile !== 'wipe' || !box.value) return
  const r = box.value.getBoundingClientRect()
  depthLayers.wipe = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
}

/** Lidar points colored by how far the fitted prediction misses them:
 *  coral when the model puts the point too close, blue when too far. */
function drawError() {
  const c = canvas.value, el = box.value, d = depth.value
  if (!c || !el) return
  const dpr = Math.min(2, window.devicePixelRatio || 1)
  c.width = el.clientWidth * dpr
  c.height = el.clientHeight * dpr
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, c.width, c.height)
  if (depthLayers.tile !== 'error' || !d || !stats.value) return
  const fit = coverTransform(props.cam.width, props.cam.height, c.width, c.height)
  const pts = d.lidar
  const r = Math.max(1.5, 1.4 * dpr)
  for (let i = 0; i < pts.length; i += DEPTH_LIDAR_STRIDE) {
    if (pts[i] !== props.index) continue
    const u = pts[i + 1] * fit.scale + fit.offsetX
    const v = pts[i + 2] * fit.scale + fit.offsetY
    const logRatio = Math.log(pts[i + 4] / pts[i + 3])
    ctx.fillStyle = errorColor(logRatio)
    ctx.fillRect(u - r / 2, v - r / 2, r, r)
  }
}


let ro: ResizeObserver | null = null
watch(() => [depth.value, depthLayers.tile, props.cam], drawError, { flush: 'post' })
onMounted(() => {
  ro = new ResizeObserver(drawError)
  if (box.value) ro.observe(box.value)
  drawError()
})
onUnmounted(() => ro?.disconnect())
</script>

<template>
  <div class="tile">
    <div class="image" ref="box" @mousemove="onMove">
      <img class="photo" :src="shown.photo" :alt="cam.channel" decoding="async" />
      <img v-if="shown.depth" class="depth" :src="shown.depth" alt="" decoding="async" :style="wipeStyle" />
      <div v-else class="pending">Running Depth Anything</div>
      <canvas ref="canvas" class="overlay"></canvas>
      <span v-if="depthLayers.tile === 'wipe' && shown.depth" class="wipe-line" :style="{ left: (depthLayers.wipe * 100).toFixed(2) + '%' }"></span>
      <span class="label">{{ channelLabel(cam.channel) }}</span>
    </div>
    <div class="meta num" v-if="stats">
      <span :title="'Mean absolute relative error against lidar after the scale and shift fit'">AbsRel {{ (stats.abs_rel * 100).toFixed(1) }}%</span>
      <span :title="'Share of lidar points the prediction places within 25% of their true depth'">δ1 {{ (stats.delta1 * 100).toFixed(0) }}%</span>
      <span class="muted">{{ stats.n_lidar.toLocaleString() }} lidar pts</span>
    </div>
    <div class="meta muted" v-else-if="state.loadingDepth">Fitting to lidar</div>
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
  cursor: col-resize;
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
.pending {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 12px;
  background: rgba(15, 22, 32, 0.55);
}
.wipe-line {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(255, 255, 255, 0.85);
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
.meta {
  display: flex;
  gap: 12px;
  padding: 4px 2px 0;
  font-size: 11.5px;
  white-space: nowrap;
}
</style>
