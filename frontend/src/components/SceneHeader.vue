<script setup lang="ts">
import { computed } from 'vue'
import { formatLocation } from '../geometry'
import { state } from '../state'

const scene = computed(() => state.scene)
const date = computed(() => {
  if (!scene.value) return ''
  const d = new Date(scene.value.date_captured + 'T00:00:00Z')
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' })
})
</script>

<template>
  <header class="header" v-if="scene">
    <div class="left">
      <h1 class="name">{{ scene.name }}</h1>
      <span class="chip" v-for="t in scene.tags" :key="t" :class="t">{{ t }}</span>
      <span class="place muted">{{ formatLocation(scene.location) }}, {{ date }}</span>
    </div>
    <p class="desc">{{ scene.description }}</p>
  </header>
</template>

<style scoped>
.header {
  display: flex;
  align-items: baseline;
  gap: 18px;
  padding: 10px 18px;
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
}
</style>
