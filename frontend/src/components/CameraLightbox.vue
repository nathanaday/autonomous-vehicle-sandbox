<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'
import { depthColor, horizontalFovDeg } from '../geometry'
import { drawOverlay } from '../overlay'
import { frame, layers, state } from '../state'

const cam = computed(() => frame.value?.detail.cameras.find((c) => c.channel === state.lightboxCamera) ?? null)
const canvas = ref<HTMLCanvasElement | null>(null)
const box = ref<HTMLDivElement | null>(null)

const counts = computed(() => {
  const f = frame.value, c = cam.value
  if (!f || !c) return null
  // count the annotations the tile actually shows so the caption is honest
  let radar = 0
  for (let i = 0; i < f.radar.length; i += 8) {
    const m = c.ref_to_cam
    const z = m[2][0] * f.radar[i] + m[2][1] * f.radar[i + 1] + m[2][2] * f.radar[i + 2] + m[2][3]
    if (z <= 0.5) continue
    const x = m[0][0] * f.radar[i] + m[0][1] * f.radar[i + 1] + m[0][2] * f.radar[i + 2] + m[0][3]
    const u = (c.intrinsic[0][0] * x) / z + c.intrinsic[0][2]
    if (u >= 0 && u < c.width) radar++
  }
  return { radar }
})

let ro: ResizeObserver | null = null
function redraw() {
  const c = canvas.value, f = frame.value, el = box.value, k = cam.value
  if (!c || !f || !el || !k) return
  const dpr = Math.min(2, window.devicePixelRatio || 1)
  c.width = el.clientWidth * dpr
  c.height = el.clientHeight * dpr
  drawOverlay(c.getContext('2d')!, k, f, {
    lidar: layers.overlayLidar,
    radar: layers.overlayRadar,
    boxes: layers.overlayBoxes,
    scale: (el.clientWidth * dpr) / k.width,
    highlight: state.hoveredAnnotation,
  })
}
watch(() => [frame.value, cam.value, layers.overlayLidar, layers.overlayRadar, layers.overlayBoxes, state.hoveredAnnotation], redraw, { flush: 'post' })
onMounted(() => {
  ro = new ResizeObserver(redraw)
  if (box.value) ro.observe(box.value)
})
onUnmounted(() => ro?.disconnect())

const gradient = computed(() => {
  const stops = [0, 0.25, 0.5, 0.75, 1].map((t) => {
    const [r, g, b] = depthColor(t * 60)
    return `rgb(${r | 0},${g | 0},${b | 0}) ${t * 100}%`
  })
  return `linear-gradient(90deg, ${stops.join(',')})`
})

function step(delta: number) {
  const list = frame.value?.detail.cameras ?? []
  const i = list.findIndex((c) => c.channel === state.lightboxCamera)
  if (i < 0) return
  state.lightboxCamera = list[(i + delta + list.length) % list.length].channel
}
</script>

<template>
  <div class="backdrop" @click.self="state.lightboxCamera = null" v-if="cam">
    <div class="panel">
      <div class="top">
        <div class="title">
          <strong>{{ cam.channel }}</strong>
          <span class="muted num">{{ cam.width }}×{{ cam.height }}, {{ horizontalFovDeg(cam).toFixed(1) }}° horizontal fov, focal {{ cam.intrinsic[0][0].toFixed(0) }} px</span>
        </div>
        <div class="actions">
          <button class="toggle" :class="{ on: layers.overlayLidar }" @click="layers.overlayLidar = !layers.overlayLidar">
            <span>Lidar depth</span><span class="knob"></span>
          </button>
          <button class="toggle" :class="{ on: layers.overlayRadar }" @click="layers.overlayRadar = !layers.overlayRadar">
            <span>Radar</span><span class="knob"></span>
          </button>
          <button class="toggle" :class="{ on: layers.overlayBoxes }" @click="layers.overlayBoxes = !layers.overlayBoxes">
            <span>Boxes</span><span class="knob"></span>
          </button>
          <button class="close" @click="state.lightboxCamera = null" aria-label="Close">
            <svg width="14" height="14" viewBox="0 0 14 14"><path d="M2 2l10 10M12 2 2 12" stroke="currentColor" stroke-width="1.6" /></svg>
          </button>
        </div>
      </div>
      <div class="image" ref="box">
        <img :src="api.imageUrl(cam.sd_token)" :alt="cam.channel" />
        <canvas ref="canvas" class="overlay"></canvas>
        <button class="nav prev" @click="step(-1)" aria-label="Previous camera">‹</button>
        <button class="nav next" @click="step(1)" aria-label="Next camera">›</button>
      </div>
      <div class="bottom num">
        <span class="muted">Mounted at x {{ cam.translation[0].toFixed(2) }} m, y {{ cam.translation[1].toFixed(2) }} m, z {{ cam.translation[2].toFixed(2) }} m on the car</span>
        <span class="muted">Captured {{ cam.dt_ms > 0 ? '+' : '' }}{{ cam.dt_ms.toFixed(1) }} ms from the lidar sweep</span>
        <span v-if="counts" class="muted">{{ counts.radar }} radar returns in view</span>
        <span class="legend" v-if="layers.overlayLidar">
          <span class="muted">0 m</span>
          <span class="bar" :style="{ background: gradient }"></span>
          <span class="muted">60 m</span>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  background: rgba(6, 10, 16, 0.78);
  display: grid;
  place-items: center;
  z-index: 10;
  padding: 24px;
}
.panel {
  width: min(1400px, 100%);
  max-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--panel);
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  padding: 12px 14px 12px;
}
.top,
.bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.title {
  display: flex;
  gap: 10px;
  align-items: baseline;
}
.actions {
  display: flex;
  gap: 14px;
  align-items: center;
}
.actions .toggle {
  width: auto;
  gap: 8px;
  padding: 0;
}
.close {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: var(--radius);
  color: var(--muted);
}
.close:hover {
  color: var(--text);
  background: var(--panel-2);
}
.image {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: var(--radius);
  overflow: hidden;
  background: #000;
}
.image img,
.overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.overlay {
  pointer-events: none;
}
.nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 36px;
  height: 56px;
  font-size: 30px;
  line-height: 1;
  color: #fff;
  background: rgba(0, 0, 0, 0.35);
  border-radius: var(--radius);
  opacity: 0;
  transition: opacity 120ms;
}
.image:hover .nav {
  opacity: 1;
}
.nav.prev {
  left: 10px;
}
.nav.next {
  right: 10px;
}
.legend {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.legend .bar {
  display: inline-block;
  width: 140px;
  height: 8px;
  border-radius: 4px;
}
</style>
