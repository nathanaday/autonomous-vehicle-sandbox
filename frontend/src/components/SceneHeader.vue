<script setup lang="ts">
import { computed } from 'vue'
import { formatLocation } from '../geometry'
import { state, type ViewMode } from '../state'

const scene = computed(() => state.scene)
const date = computed(() => {
  if (!scene.value) return ''
  const d = new Date(scene.value.date_captured + 'T00:00:00Z')
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' })
})

const views: { id: ViewMode; label: string; hint: string }[] = [
  { id: 'explore', label: 'Sensors', hint: 'Every sensor in the raw dataset' },
  { id: 'depth', label: 'Depth Anything', hint: 'Stock monocular depth against the lidar' },
  { id: 'fusion', label: 'Fused mesh', hint: 'The whole scene fused into one surface' },
]

function setView(v: ViewMode) {
  state.view = v
  state.lightboxCamera = null
}
</script>

<template>
  <header class="header">
    <div class="brand">
      <span class="title">nuScenes</span>
      <span class="muted">v1.0-mini</span>
    </div>
    <template v-if="scene">
      <div class="scene">
        <div class="row">
          <h1 class="name">{{ scene.name }}</h1>
          <span class="chip" v-for="t in scene.tags" :key="t" :class="t">{{ t }}</span>
          <span class="place muted">{{ formatLocation(scene.location) }}, {{ date }}</span>
          <span class="stats muted num">{{ scene.nbr_samples }} keyframes, {{ scene.duration_s.toFixed(0) }} s, {{ scene.nbr_instances }} objects</span>
        </div>
        <p class="desc">{{ scene.description }}</p>
      </div>
      <button class="change" @click="state.scenePickerOpen = true" title="Choose another scene (s)">Change scene</button>
    </template>
    <nav class="views" aria-label="View">
      <button v-for="v in views" :key="v.id" :class="{ on: state.view === v.id }" :title="v.hint" @click="setView(v.id)">{{ v.label }}</button>
    </nav>
  </header>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 8px 18px;
  border-bottom: 1px solid var(--line);
  min-height: 54px;
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding-right: 18px;
  border-right: 1px solid var(--line);
  flex: none;
}
.title {
  font-weight: 600;
  font-size: 15px;
  letter-spacing: -0.01em;
}
.scene {
  min-width: 0;
  flex: 1;
}
.row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: nowrap;
  white-space: nowrap;
  overflow: hidden;
}
.name {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.place {
  margin-left: 4px;
}
.stats {
  font-size: 12px;
}
.desc {
  margin: 1px 0 0;
  color: var(--muted);
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.change {
  flex: none;
  padding: 5px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--line-strong);
  color: var(--text);
  background: var(--panel);
}
.change:hover {
  border-color: var(--accent);
}
.views {
  display: inline-flex;
  flex: none;
  gap: 2px;
  padding: 2px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.views button {
  padding: 4px 11px;
  border-radius: 4px;
  color: var(--muted);
}
.views button:hover {
  color: var(--text);
}
.views button.on {
  color: var(--text);
  background: var(--line-strong);
}
@media (max-width: 1300px) {
  .stats {
    display: none;
  }
}
</style>
