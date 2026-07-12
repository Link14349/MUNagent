<script setup lang="ts">
import { useRouter } from "vue-router";

const router = useRouter();

function goDesign() {
  router.push("/scenarios");
}

function goDeduce() {
  alert("场景推演将在后续阶段接入");
}
</script>

<template>
  <section class="landing">
    <h1>MUN Agent</h1>
    <p class="tagline">基于 LLM 的模拟联合国历史委员会场景设计与推演</p>
    <div class="actions">
      <button type="button" class="primary" @click="goDesign">场景设计</button>
      <button type="button" class="secondary" @click="goDeduce">场景推演</button>
    </div>
    <footer class="foot">
      <span>MUNagent · 单机本地工具</span>
    </footer>
  </section>
</template>

<style scoped>
.landing {
  min-height: calc(100vh - 4rem);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 2rem;
}
h1 {
  font-size: 2.75rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin: 0 0 0.5rem;
  color: var(--text);
}
.tagline {
  color: var(--text-muted);
  margin: 0 0 2rem;
  max-width: 420px;
}
.actions {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  justify-content: center;
}
.primary,
.secondary {
  padding: 0.65rem 1.5rem;
  border-radius: 8px;
  font-size: 1rem;
  border: 1px solid var(--border);
}
.primary {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.secondary {
  background: var(--panel-bg);
  color: var(--text-muted);
}
.foot {
  margin-top: 4rem;
  font-size: 0.8rem;
  color: var(--text-muted);
}
</style>
