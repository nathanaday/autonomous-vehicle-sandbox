<script setup lang="ts">
import { api } from '../api'
import { formatLocation } from '../geometry'
import { depthScenes, loadScene, state } from '../state'
</script>

<template>
  <nav class="rail">
    <div class="head">
      <div class="title">nuScenes</div>
      <div class="muted">v1.0-mini, {{ state.scenes.length }} scenes</div>
    </div>
    <ul class="list">
      <li v-for="s in state.scenes" :key="s.token">
        <button
          class="card"
          :class="{ active: state.scene?.token === s.token }"
          @click="loadScene(s.token)"
        >
          <img class="thumb" :src="api.imageUrl(s.thumbnail_sd_token, 320)" alt="" loading="lazy" />
          <div class="body">
            <div class="row">
              <span class="name">{{ s.name }}</span>
              <span class="chip" v-for="t in s.tags" :key="t" :class="t">{{ t }}</span>
            </div>
            <div class="where muted">{{ formatLocation(s.location) }}</div>
            <div class="desc">{{ s.description }}</div>
            <div class="meta muted num">
              <span>{{ s.nbr_samples }} keyframes</span>
              <span>{{ s.duration_s.toFixed(0) }} s</span>
              <span>{{ s.nbr_instances }} objects</span>
            </div>
            <div class="depth num" v-if="state.view === 'depth'">
              <template v-if="depthScenes[s.token]">
                <span class="bar"><i :style="{ width: Math.min(100, depthScenes[s.token].abs_rel * 300) + '%' }"></i></span>
                <span>AbsRel {{ (depthScenes[s.token].abs_rel * 100).toFixed(1) }}%</span>
              </template>
              <span v-else class="muted">Measuring</span>
            </div>
          </div>
        </button>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.rail {
  display: flex;
  flex-direction: column;
  background: var(--panel);
}
.head {
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--line);
}
.title {
  font-weight: 600;
  font-size: 15px;
  letter-spacing: -0.01em;
}
.list {
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.card {
  display: block;
  width: 100%;
  text-align: left;
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid transparent;
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
  aspect-ratio: 16 / 7;
  object-fit: cover;
  filter: saturate(0.85);
}
.card.active .thumb {
  filter: none;
}
.body {
  padding: 8px 10px 10px;
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
  color: var(--text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  opacity: 0.85;
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
</style>
