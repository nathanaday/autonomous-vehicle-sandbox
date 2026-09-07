<script setup lang="ts">
import { computed } from 'vue'
import Occ3dTile from './Occ3dTile.vue'
import { frame } from '../state'

const ORDER = ['CAM_FRONT_LEFT', 'CAM_FRONT', 'CAM_FRONT_RIGHT', 'CAM_BACK_LEFT', 'CAM_BACK', 'CAM_BACK_RIGHT']

const cams = computed(() => {
  const list = frame.value?.detail.cameras ?? []
  return ORDER.map((ch) => list.find((c) => c.channel === ch)).filter((c) => c !== undefined)
})
</script>

<template>
  <section class="grid">
    <Occ3dTile v-for="cam in cams" :key="cam.channel" :cam="cam" />
  </section>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  grid-template-rows: repeat(2, minmax(0, 1fr));
  gap: 8px 10px;
  padding: 10px 14px;
  min-height: 0;
  background: var(--ground);
}
</style>
