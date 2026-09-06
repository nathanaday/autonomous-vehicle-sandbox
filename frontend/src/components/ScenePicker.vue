<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, type SceneSummary } from '../api'
import { formatLocation } from '../geometry'
import { depthScenes, features, loadScene, state } from '../state'

function pick(token: string) {
  loadScene(token)
  state.scenePickerOpen = false
}

/** Features with results in the cache for at least one scene. A scene is
 *  "computed" when it has results for all of them; the rest are raw sensor
 *  data, which is what a full v1.0-mini next to the three-scene bundles
 *  looks like. */
type CacheFeature = 'depth' | 'fusion' | 'splat'
const installed = computed<CacheFeature[]>(() => {
  const f = features.value
  if (!f) return []
  return (['depth', 'fusion', 'splat'] as const).filter((name) => f[name].present)
})
const computedScenes = computed(() => state.scenes.filter((s) => installed.value.every((name) => s.features[name])))
const otherScenes = computed(() => state.scenes.filter((s) => !computedScenes.value.includes(s)))
const split = computed(() => computedScenes.value.length > 0 && otherScenes.value.length > 0)

const labels: Record<CacheFeature, string> = { depth: 'Depth Anything', fusion: 'fused meshes', splat: 'Gaussian splats' }
const chips: Record<CacheFeature, string> = { depth: 'depth', fusion: 'mesh', splat: 'splat' }
const installedLabel = computed(() => installed.value.map((n) => labels[n]).join(', '))

const moreOpen = ref(otherScenes.value.some((s) => s.token === state.scene?.token))

const sections = computed(() =>
  split.value
    ? [
        { id: 'computed', title: 'With precomputed results', hint: `${installedLabel.value}, ready to view`, scenes: computedScenes.value, collapsible: false },
        { id: 'more', title: `More scenes`, hint: 'Missing results for some views. The compute CLI can add them.', scenes: otherScenes.value, collapsible: true },
      ]
    : [{ id: 'all', title: '', hint: '', scenes: state.scenes as SceneSummary[], collapsible: false }],
)
</script>

<template>
  <div class="backdrop" @click.self="state.scenePickerOpen = false">
    <div class="panel" role="dialog" aria-modal="true" aria-label="Choose a scene">
      <div class="top">
        <div>
          <h2>Choose a scene</h2>
          <div class="muted">nuScenes v1.0-mini, {{ state.scenes.length }} scenes of about 20 seconds each</div>
        </div>
        <button class="close" @click="state.scenePickerOpen = false" aria-label="Close">
          <svg width="14" height="14" viewBox="0 0 14 14"><path d="M2 2l10 10M12 2 2 12" stroke="currentColor" stroke-width="1.6" /></svg>
        </button>
      </div>
      <div class="sections">
        <section v-for="sec in sections" :key="sec.id" :class="{ collapsed: sec.collapsible && !moreOpen }">
          <button v-if="sec.collapsible" class="section-toggle" @click="moreOpen = !moreOpen" :aria-expanded="moreOpen">
            <svg class="chevron" width="10" height="10" viewBox="0 0 10 10"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.6" /></svg>
            <span class="section-title">{{ sec.title }}</span>
            <span class="muted num">{{ sec.scenes.length }}</span>
            <span class="muted hint">{{ sec.hint }}</span>
          </button>
          <div v-else-if="sec.title" class="section-head">
            <span class="section-title">{{ sec.title }}</span>
            <span class="muted hint">{{ sec.hint }}</span>
          </div>
          <ul class="grid" v-if="!sec.collapsible || moreOpen">
            <li v-for="s in sec.scenes" :key="s.token">
              <button class="card" :class="{ active: state.scene?.token === s.token }" @click="pick(s.token)" :autofocus="state.scene?.token === s.token">
                <img class="thumb" :src="api.imageUrl(s.thumbnail_sd_token, 480)" alt="" loading="lazy" />
                <div class="body">
                  <div class="row">
                    <span class="name">{{ s.name }}</span>
                    <span class="chip" v-for="t in s.tags" :key="t" :class="t">{{ t }}</span>
                  </div>
                  <div class="where muted">{{ formatLocation(s.location) }}, {{ s.date_captured }}</div>
                  <div class="desc">{{ s.description }}</div>
                  <div class="meta muted num">
                    <span>{{ s.nbr_samples }} keyframes</span>
                    <span>{{ s.duration_s.toFixed(0) }} s</span>
                    <span>{{ s.nbr_instances }} objects</span>
                  </div>
                  <div class="features" v-if="installed.length">
                    <span v-for="name in installed" :key="name" class="feat" :class="{ on: s.features[name] }" :title="labels[name] + (s.features[name] ? ' in the cache' : ' not computed')">{{ chips[name] }}</span>
                  </div>
                  <div class="depth num" v-if="state.view === 'depth'">
                    <template v-if="depthScenes[s.token]">
                      <span class="bar"><i :style="{ width: Math.min(100, depthScenes[s.token].abs_rel * 300) + '%' }"></i></span>
                      <span>Depth AbsRel {{ (depthScenes[s.token].abs_rel * 100).toFixed(1) }}%</span>
                    </template>
                    <span v-else class="muted">Measuring depth error</span>
                  </div>
                </div>
              </button>
            </li>
          </ul>
        </section>
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
  width: min(1360px, 100%);
  max-height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  overflow: hidden;
}
.top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--line);
}
h2 {
  margin: 0 0 2px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
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
.sections {
  overflow-y: auto;
  padding: 4px 20px 20px;
}
.section-head,
.section-toggle {
  display: flex;
  align-items: baseline;
  gap: 10px;
  width: 100%;
  padding: 14px 0 8px;
  text-align: left;
}
.section-toggle {
  border-top: 1px solid var(--line);
  margin-top: 8px;
  color: var(--muted);
}
.section-toggle:hover {
  color: var(--text);
}
.section-title {
  font-weight: 600;
  color: var(--text);
}
.hint {
  font-size: 12px;
}
.chevron {
  align-self: center;
  transition: transform 150ms;
}
.collapsed .chevron {
  transform: rotate(-90deg);
}
.grid {
  list-style: none;
  margin: 0;
  padding: 0 0 4px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.card {
  display: block;
  width: 100%;
  height: 100%;
  text-align: left;
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--line);
  background: var(--ground);
}
.card:hover {
  border-color: var(--line-strong);
}
.card.active {
  border-color: var(--accent);
}
.thumb {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  filter: saturate(0.85);
}
.card:hover .thumb,
.card.active .thumb {
  filter: none;
}
.body {
  padding: 10px 12px 12px;
}
.row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.name {
  font-weight: 600;
}
.where {
  font-size: 12px;
}
.desc {
  margin-top: 4px;
  font-size: 12px;
  opacity: 0.85;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta {
  margin-top: 6px;
  display: flex;
  gap: 12px;
  font-size: 11.5px;
}
.depth {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
}
.depth .bar {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: var(--line);
  overflow: hidden;
}
.depth .bar i {
  display: block;
  height: 100%;
  background: var(--radar);
  border-radius: 2px;
}
.features {
  display: flex;
  gap: 6px;
  margin-top: 6px;
  font-size: 11px;
}
.feat {
  padding: 0 5px;
  border-radius: 3px;
  border: 1px solid var(--line);
  opacity: 0.4;
  text-decoration: line-through;
}
.feat.on {
  opacity: 1;
  text-decoration: none;
  border-color: var(--line-strong);
}
</style>
