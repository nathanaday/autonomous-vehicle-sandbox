<script setup lang="ts">
import { computed } from 'vue'
import DepthTile from './DepthTile.vue'
import { frame } from '../state'

/** Same physical arrangement as the explorer grid. The index matches the
 *  camera_index the backend writes into the depth binaries, which follows
 *  the backend's CAMERA_CHANNELS order. */
const ORDER = ['CAM_FRONT_LEFT', 'CAM_FRONT', 'CAM_FRONT_RIGHT', 'CAM_BACK_LEFT', 'CAM_BACK', 'CAM_BACK_RIGHT']

const cams = computed(() => {
  const list = frame.value?.detail.cameras ?? []
  return ORDER.map((ch) => list.find((c) => c.channel === ch)).filter((c) => c !== undefined)
})
</script>

<template>
  <section class="grid">
    <DepthTile v-for="(cam, i) in cams" :key="cam.channel" :cam="cam" :index="i" />
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
