<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";

const route = useRoute();
const immersive = computed(() => route.name === "design");
</script>

<template>
  <div class="layout" :class="{ immersive }">
    <header v-if="!immersive" class="topbar">
      <RouterLink to="/" class="brand">MUNagent</RouterLink>
      <nav>
        <RouterLink to="/scenarios">场景设计</RouterLink>
        <RouterLink to="/settings">设置</RouterLink>
      </nav>
    </header>
    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}
.layout.immersive {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.layout.immersive .main {
  flex: 1;
  min-height: 0;
  max-width: none;
  margin: 0;
  padding: 0;
  height: 100%;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.5rem;
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border);
  color: var(--text);
}
.brand {
  font-weight: 700;
  color: var(--text);
  text-decoration: none;
}
nav {
  display: flex;
  gap: 1rem;
}
nav a {
  color: var(--text-muted);
  text-decoration: none;
}
nav a.router-link-active {
  color: var(--accent);
  font-weight: 600;
}
.main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1.5rem;
}
</style>
