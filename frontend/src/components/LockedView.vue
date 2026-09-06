<script setup lang="ts">
import { computed } from 'vue'
import { state, viewLock } from '../state'

const lock = computed(() => viewLock(state.view))
const names: Record<string, string> = {
  depth: 'Depth Anything V2 predictions for every keyframe camera image',
  fusion: 'fused meshes of each scene from camera depth and from lidar',
  splat: 'Depth Anything 3 Gaussian splats of every keyframe',
}
</script>

<template>
  <section class="locked" v-if="lock">
    <div class="card">
      <h2>This view needs the {{ lock.name }} bundle</h2>
      <p>The cache has no {{ names[lock.name] }} for any scene. Fetch the bundle from the repository's releases, then restart the backend:</p>
      <pre>{{ lock.make }}</pre>
      <p class="muted">Or compute the results yourself with the compute CLI. See README, Data, for the bundles and what each one unlocks.</p>
    </div>
  </section>
</template>

<style scoped>
.locked {
  display: grid;
  place-items: center;
  padding: 24px;
}
.card {
  max-width: 520px;
  padding: 20px 24px;
  background: var(--panel);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
}
h2 {
  margin: 0 0 10px;
  font-size: 15px;
}
p {
  margin: 0 0 10px;
  line-height: 1.5;
}
pre {
  margin: 0 0 12px;
  padding: 8px 12px;
  background: var(--ground);
  border-radius: var(--radius);
  font-size: 13px;
}
.muted {
  font-size: 12px;
}
</style>
