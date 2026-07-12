<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <RouterLink to="/" class="brand">MUNagent</RouterLink>
      <nav>
        <RouterLink to="/">场景包库</RouterLink>
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
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.5rem;
  background: #102a43;
  color: #fff;
}
.brand {
  font-weight: 700;
  color: #fff;
  text-decoration: none;
}
nav {
  display: flex;
  gap: 1rem;
}
nav a {
  color: #d9e2ec;
}
nav a.router-link-active {
  color: #fff;
  font-weight: 600;
}
.main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1.5rem;
}
</style>
