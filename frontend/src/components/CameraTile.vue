<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { api, type CameraFrame } from '../api'
import { coverTransform, horizontalFovDeg } from '../geometry'
import { drawOverlay } from '../overlay'
import { frame, layers, state } from '../state'

const props = defineProps<{ cam: CameraFrame }>()

const canvas = ref<HTMLCanvasElement | null>(null)
const box = ref<HTMLDivElement | null>(null)
const loaded = ref(false)
const shown = ref(api.imageUrl(props.cam.sd_token, 800))

/** Swap the image only after the new one has decoded, so stepping frames
 *  never flashes an empty tile. */
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

let ro: ResizeObserver | null = null

function redraw() {
  const c = canvas.value, f = frame.value, el = box.value
  if (!c || !f || !el) return
  const w = el.clientWidth, h = el.clientHeight
  if (w === 0) return
  const dpr = Math.min(2, window.devicePixelRatio || 1)
  c.width = w * dpr
  c.height = h * dpr
  const ctx = c.getContext('2d')!
  const fit = coverTransform(props.cam.width, props.cam.height, w * dpr, h * dpr)
  drawOverlay(ctx, props.cam, f, {
    lidar: layers.overlayLidar,
    radar: layers.overlayRadar,
    boxes: layers.overlayBoxes,
    ...fit,
    lidarStep: 2,
    highlight: state.hoveredAnnotation,
  })
}

watch(
  () => [frame.value, layers.overlayLidar, layers.overlayRadar, layers.overlayBoxes, state.hoveredAnnotation, props.cam],
  redraw,
  { flush: 'post' },
)

onMounted(() => {
  ro = new ResizeObserver(redraw)
  if (box.value) ro.observe(box.value)
  redraw()
})
onUnmounted(() => ro?.disconnect())
</script>

<template>
  <div class="tile">
    <button class="image" ref="box" @click="state.lightboxCamera = cam.channel" :title="`Open ${cam.channel}`">
      <img :src="shown" :alt="cam.channel" @load="loaded = true" decoding="async" />
      <canvas ref="canvas" class="overlay"></canvas>
      <span class="label">{{ cam.channel.replace('CAM_', '').replace('_', ' ').toLowerCase() }}</span>
    </button>
    <div class="meta num muted">
      <span>{{ cam.width }}×{{ cam.height }}</span>
      <span>{{ horizontalFovDeg(cam).toFixed(0) }}° fov</span>
      <span :title="'Capture time relative to the lidar sweep'">{{ cam.dt_ms > 0 ? '+' : '' }}{{ cam.dt_ms.toFixed(0) }} ms</span>
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
  display: block;
  aspect-ratio: 16 / 9;
}
.image img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
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
  text-transform: capitalize;
}
.image:hover .label {
  text-decoration: underline;
}
.meta {
  display: flex;
  gap: 12px;
  padding: 4px 2px 0;
  font-size: 11.5px;
  white-space: nowrap;
}
</style>
