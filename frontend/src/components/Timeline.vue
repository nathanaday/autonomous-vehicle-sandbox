<script setup lang="ts">
import { computed } from 'vue'
import { formatTimestamp } from '../geometry'
import { depthScenes, frame, goToIndex, sceneOcc3d, sceneSplat, state, stepFrame } from '../state'

const detail = computed(() => frame.value?.detail ?? null)
const samples = computed(() => state.scene?.samples ?? [])
const maxAnnotations = computed(() => Math.max(1, ...samples.value.map((s) => s.nbr_annotations)))

/** In the depth view the bars show depth error per keyframe instead of
 *  object count, once the scene summary has loaded. */
const errors = computed(() => {
  if (state.view !== 'depth' || !state.scene) return null
  const summary = depthScenes[state.scene.token]
  if (!summary) return null
  return new Map(summary.frames.map((f) => [f.token, f.abs_rel]))
})
const maxError = computed(() => (errors.value ? Math.max(0.01, ...errors.value.values()) : 1))

/** In the splat view the bars show which keyframes have a splat in the cache. */
const built = computed(() => {
  const sc = state.view === 'splat' ? sceneSplat.value : null
  if (!sc || sc.scene_token !== state.scene?.token) return null
  return new Map(sc.keyframes.map((k) => [k.token, k.ready]))
})

/** In the occupancy view the bars show occupied voxels per keyframe. */
const occupied = computed(() => {
  const sc = state.view === 'occ3d' ? sceneOcc3d.value : null
  if (!sc || sc.scene_name !== state.scene?.name) return null
  return new Map(sc.keyframes.map((k) => [k.token, k.n_occupied]))
})
const maxOccupied = computed(() => (occupied.value ? Math.max(1, ...occupied.value.values()) : 1))

function barHeight(s: { token: string; nbr_annotations: number }) {
  if (built.value) return built.value.get(s.token) ? 100 : 20
  if (occupied.value) return 15 + (85 * (occupied.value.get(s.token) ?? 0)) / maxOccupied.value
  if (errors.value) return 15 + (85 * (errors.value.get(s.token) ?? 0)) / maxError.value
  return 25 + (75 * s.nbr_annotations) / maxAnnotations.value
}
function barTitle(s: { token: string; nbr_annotations: number }, i: number) {
  if (built.value) return `Keyframe ${i + 1}, ${built.value.get(s.token) ? 'splat computed' : 'no splat'}`
  const o = occupied.value?.get(s.token)
  if (o !== undefined) return `Keyframe ${i + 1}, ${o.toLocaleString()} occupied voxels`
  const e = errors.value?.get(s.token)
  return e !== undefined ? `Keyframe ${i + 1}, AbsRel ${(e * 100).toFixed(1)}%` : `Keyframe ${i + 1}, ${s.nbr_annotations} objects`
}
const speeds = [1, 2, 5, 10]

function cycleSpeed() {
  const i = speeds.indexOf(state.fps)
  state.fps = speeds[(i + 1) % speeds.length]
}
</script>

<template>
  <footer class="timeline">
    <div class="controls">
      <button class="btn" title="Previous keyframe (←)" @click="stepFrame(-1)" aria-label="Previous keyframe">
        <svg width="14" height="14" viewBox="0 0 14 14"><path d="M10 2 4 7l6 5z" fill="currentColor" /></svg>
      </button>
      <button class="btn play" :title="state.playing ? 'Pause (space)' : 'Play (space)'" @click="state.playing = !state.playing" :aria-label="state.playing ? 'Pause' : 'Play'">
        <svg v-if="!state.playing" width="14" height="14" viewBox="0 0 14 14"><path d="M3 2v10l9-5z" fill="currentColor" /></svg>
        <svg v-else width="14" height="14" viewBox="0 0 14 14"><path d="M3 2h3v10H3zM8 2h3v10H8z" fill="currentColor" /></svg>
      </button>
      <button class="btn" title="Next keyframe (→)" @click="stepFrame(1)" aria-label="Next keyframe">
        <svg width="14" height="14" viewBox="0 0 14 14"><path d="M4 2l6 5-6 5z" fill="currentColor" /></svg>
      </button>
      <button class="speed num" @click="cycleSpeed" title="Playback rate in keyframes per second. Keyframes are recorded at 2 per second.">
        {{ state.fps }}×
      </button>
    </div>

    <div class="scrubber" v-if="detail">
      <div class="ticks" role="slider" :aria-valuenow="detail.index" :aria-valuemin="0" :aria-valuemax="detail.count - 1" aria-label="Keyframe">
        <button
          v-for="(s, i) in samples"
          :key="s.token"
          class="tick"
          :class="{ current: i === detail.index, past: i < detail.index, unbuilt: built ? !built.get(s.token) : false }"
          :title="barTitle(s, i)"
          @click="goToIndex(i)"
        >
          <span class="bar" :style="{ height: barHeight(s) + '%' }"></span>
        </button>
      </div>
    </div>

    <div class="readout num" v-if="detail">
      <span class="frame">Keyframe {{ detail.index + 1 }} of {{ detail.count }}</span>
      <span class="muted">t = {{ detail.t_s.toFixed(1) }} s</span>
      <span class="muted bars-hint" v-if="built">bars: keyframes with a splat</span>
      <span class="muted bars-hint" v-else-if="errors">bars: depth error per keyframe</span>
      <span class="muted stamp">{{ formatTimestamp(detail.timestamp) }}</span>
    </div>
  </footer>
</template>

<style scoped>
.timeline {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 18px;
  padding: 8px 18px;
  border-top: 1px solid var(--line);
  background: var(--panel);
}
.controls {
  display: flex;
  align-items: center;
  gap: 4px;
}
.btn {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: var(--radius);
  color: var(--muted);
}
.btn:hover {
  color: var(--text);
  background: var(--panel-2);
}
.play {
  color: var(--text);
  background: var(--panel-2);
}
.speed {
  margin-left: 6px;
  padding: 3px 8px;
  border-radius: var(--radius);
  color: var(--muted);
  min-width: 36px;
}
.speed:hover {
  color: var(--text);
  background: var(--panel-2);
}
.scrubber {
  min-width: 0;
}
.ticks {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 28px;
}
.tick {
  flex: 1 1 0;
  height: 100%;
  display: flex;
  align-items: flex-end;
  border-radius: 2px;
}
.tick .bar {
  display: block;
  width: 100%;
  background: var(--line-strong);
  border-radius: 2px;
  transition: background 100ms;
}
.tick.past .bar {
  background: #4b6a8a;
}
.tick.current .bar {
  background: var(--accent);
}
.tick.unbuilt .bar {
  opacity: 0.35;
}
.readout {
  display: flex;
  gap: 14px;
  align-items: baseline;
  white-space: nowrap;
}
.frame {
  font-weight: 600;
}
.stamp,
.bars-hint {
  font-size: 12px;
}
@media (max-width: 1300px) {
  .stamp {
    display: none;
  }
}
</style>
