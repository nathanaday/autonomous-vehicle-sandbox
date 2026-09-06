<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import SceneRail from './components/SceneRail.vue'
import SceneHeader from './components/SceneHeader.vue'
import CameraGrid from './components/CameraGrid.vue'
import PointCloudView from './components/PointCloudView.vue'
import Inspector from './components/Inspector.vue'
import Timeline from './components/Timeline.vue'
import CameraLightbox from './components/CameraLightbox.vue'
import { loadScenes, state, stepFrame } from './state'

function onKey(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement) return
  if (e.key === 'ArrowRight' || e.key === 'l') stepFrame(1)
  else if (e.key === 'ArrowLeft' || e.key === 'h') stepFrame(-1)
  else if (e.key === ' ') {
    e.preventDefault()
    state.playing = !state.playing
  } else if (e.key === 'Escape') state.lightboxCamera = null
}

onMounted(() => {
  loadScenes()
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="shell">
    <SceneRail class="rail" />
    <main class="main">
      <SceneHeader />
      <div class="stage">
        <div class="views">
          <CameraGrid class="cameras" />
          <PointCloudView class="cloud" />
        </div>
        <Inspector class="inspector" />
      </div>
      <Timeline />
    </main>
    <CameraLightbox v-if="state.lightboxCamera" />
    <div v-if="state.error" class="error">{{ state.error }}</div>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: var(--rail-w) 1fr;
  height: 100%;
}
.rail {
  border-right: 1px solid var(--line);
  min-height: 0;
}
.main {
  display: grid;
  grid-template-rows: auto 1fr auto;
  min-width: 0;
  min-height: 0;
}
.stage {
  display: grid;
  grid-template-columns: 1fr var(--inspector-w);
  min-height: 0;
}
.views {
  display: grid;
  grid-template-rows: minmax(160px, 34%) 1fr;
  min-height: 0;
  min-width: 0;
}
.cameras {
  border-bottom: 1px solid var(--line);
}
.cloud {
  min-height: 0;
}
.inspector {
  border-left: 1px solid var(--line);
  min-height: 0;
}
.error {
  position: fixed;
  left: 50%;
  bottom: 64px;
  transform: translateX(-50%);
  background: #4a1f24;
  color: #ffd2d2;
  border: 1px solid #8a3a44;
  padding: 8px 14px;
  border-radius: var(--radius);
}
@media (max-width: 1100px) {
  .shell {
    grid-template-columns: 1fr;
  }
  .rail {
    display: none;
  }
  .stage {
    grid-template-columns: 1fr;
  }
  .inspector {
    display: none;
  }
}
</style>
