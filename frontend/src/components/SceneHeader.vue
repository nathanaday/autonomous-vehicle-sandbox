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
]

function setView(v: ViewMode) {
  state.view = v
  state.lightboxCamera = null
}
</script>

<template>
  <header class="header" v-if="scene">
    <div class="left">
      <h1 class="name">{{ scene.name }}</h1>
      <span class="chip" v-for="t in scene.tags" :key="t" :class="t">{{ t }}</span>
      <span class="place muted">{{ formatLocation(scene.location) }}, {{ date }}</span>
    </div>
    <p class="desc">{{ scene.description }}</p>
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
  padding: 7px 18px;
  border-bottom: 1px solid var(--line);
  min-height: 42px;
}
.left {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex: none;
}
.name {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.place {
  margin-left: 6px;
}
.desc {
  margin: 0;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  flex: 1;
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
</style>
