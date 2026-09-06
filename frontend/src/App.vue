<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import ScenePicker from './components/ScenePicker.vue'
import SceneHeader from './components/SceneHeader.vue'
import CameraGrid from './components/CameraGrid.vue'
import PointCloudView from './components/PointCloudView.vue'
import Inspector from './components/Inspector.vue'
import DepthGrid from './components/DepthGrid.vue'
import DepthCloudView from './components/DepthCloudView.vue'
import DepthInspector from './components/DepthInspector.vue'
import FusionView from './components/FusionView.vue'
import FusionInspector from './components/FusionInspector.vue'
import SplatView from './components/SplatView.vue'
import SplatInspector from './components/SplatInspector.vue'
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
  } else if (e.key === 'Escape') {
    state.lightboxCamera = null
    state.scenePickerOpen = false
  } else if (e.key === 's') state.scenePickerOpen = !state.scenePickerOpen
}

onMounted(() => {
  loadScenes()
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="shell">
    <main class="main">
      <SceneHeader />
      <!-- Only one view is mounted at a time so its WebGL context and
           textures are released before the other one allocates its own. -->
      <div class="stage" v-if="state.view === 'explore'">
        <div class="views">
          <CameraGrid class="cameras" />
          <PointCloudView class="cloud" />
        </div>
        <Inspector class="inspector" />
      </div>
      <div class="stage" v-else-if="state.view === 'depth'">
        <div class="views">
          <DepthGrid class="cameras" />
          <DepthCloudView class="cloud" />
        </div>
        <DepthInspector class="inspector" />
      </div>
      <div class="stage" v-else-if="state.view === 'fusion'">
        <FusionView class="cloud" />
        <FusionInspector class="inspector" />
      </div>
      <div class="stage" v-else>
        <SplatView class="cloud" />
        <SplatInspector class="inspector" />
      </div>
      <Timeline />
    </main>
    <CameraLightbox v-if="state.lightboxCamera && state.view === 'explore'" />
    <ScenePicker v-if="state.scenePickerOpen" />
    <div v-if="state.error" class="error">{{ state.error }}</div>
  </div>
</template>

<style scoped>
.shell {
  height: 100%;
}
.main {
  display: grid;
  grid-template-rows: auto 1fr auto;
  height: 100%;
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
  .stage {
    grid-template-columns: 1fr;
  }
  .inspector {
    display: none;
  }
}
</style>
