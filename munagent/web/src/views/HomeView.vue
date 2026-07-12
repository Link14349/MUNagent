<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { api, type ScenarioSummary } from "../api";

const router = useRouter();
const scenarios = ref<ScenarioSummary[]>([]);
const loading = ref(true);
const error = ref("");
const newId = ref("");
const newTitle = ref("");
const creating = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    scenarios.value = await api.listScenarios();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function createScenario() {
  if (!newId.value.trim() || !newTitle.value.trim()) return;
  creating.value = true;
  try {
    const detail = await api.createScenario({
      id: newId.value.trim(),
      title: newTitle.value.trim(),
    });
    await router.push(`/scenarios/${detail.id}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    creating.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section>
    <h1>场景包库</h1>
    <p class="hint">内置示例与用户自建场景包。设计工作台与推演入口将在后续阶段接入。</p>

    <div class="actions">
      <button class="ghost" disabled title="P2 设计工作台">新建设计</button>
      <button class="ghost" disabled title="P3+ 推演引擎">开始推演</button>
    </div>

    <p v-if="loading">加载中…</p>
    <p v-else-if="error" class="error">{{ error }}</p>

    <ul v-else class="list">
      <li v-for="s in scenarios" :key="s.id" class="card">
        <div>
          <RouterLink :to="`/scenarios/${s.id}`" class="title">{{ s.title }}</RouterLink>
          <div class="meta">
            <span>{{ s.id }}</span>
            <span>{{ s.source === "builtin" ? "内置" : "用户" }}</span>
            <span v-if="s.readonly">只读</span>
          </div>
        </div>
      </li>
    </ul>

    <form class="create" @submit.prevent="createScenario">
      <h2>新建空白场景包</h2>
      <label>
        ID (a-z0-9-)
        <input v-model="newId" placeholder="my-crisis" pattern="[a-z0-9-]+" required />
      </label>
      <label>
        标题
        <input v-model="newTitle" placeholder="我的危机场景" required />
      </label>
      <button type="submit" :disabled="creating">{{ creating ? "创建中…" : "创建" }}</button>
    </form>
  </section>
</template>

<style scoped>
.hint {
  color: #52606d;
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin: 1rem 0;
}
.ghost {
  padding: 0.5rem 1rem;
  border: 1px dashed #bcccdc;
  background: #fff;
  color: #829ab1;
  border-radius: 6px;
}
.list {
  list-style: none;
  padding: 0;
  margin: 1rem 0 2rem;
  display: grid;
  gap: 0.75rem;
}
.card {
  background: #fff;
  border-radius: 8px;
  padding: 1rem 1.25rem;
  box-shadow: 0 1px 3px rgb(0 0 0 / 8%);
}
.title {
  font-size: 1.1rem;
  font-weight: 600;
}
.meta {
  margin-top: 0.35rem;
  display: flex;
  gap: 0.75rem;
  font-size: 0.85rem;
  color: #627d98;
}
.create {
  background: #fff;
  padding: 1.25rem;
  border-radius: 8px;
  display: grid;
  gap: 0.75rem;
  max-width: 420px;
}
.create label {
  display: grid;
  gap: 0.25rem;
  font-size: 0.9rem;
}
.create input {
  padding: 0.5rem;
  border: 1px solid #cbd2d9;
  border-radius: 4px;
}
.create button {
  justify-self: start;
  padding: 0.5rem 1rem;
  background: #1d5bbf;
  color: #fff;
  border: none;
  border-radius: 6px;
}
.error {
  color: #ba2525;
}
</style>
