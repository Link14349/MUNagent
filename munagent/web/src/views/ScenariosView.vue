<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { api, type ScenarioSummary } from "../api";
import { designerApi } from "../api/designerApi";

interface ScenarioRow extends ScenarioSummary {
  chat_count?: number;
  last_chat_at?: string | null;
}

const SCENARIO_ID_RE = /^[a-z0-9-]+$/;

const router = useRouter();
const scenarios = ref<ScenarioRow[]>([]);
const loading = ref(true);
const error = ref("");
const showCreate = ref(false);
const newId = ref("");
const newTitle = ref("");
const createError = ref("");
const creating = ref(false);
const createIdRef = ref<HTMLInputElement | null>(null);
const dupSource = ref<ScenarioRow | null>(null);
const dupId = ref("");
const dupTitle = ref("");
const dupError = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const list = await api.listScenarios();
    scenarios.value = await designerApi.enrichSummaries(list);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function validateScenarioId(id: string): string | null {
  if (!id) return "请填写场景 ID";
  if (!SCENARIO_ID_RE.test(id)) return "ID 只能包含小写字母、数字和连字符 (a-z0-9-)";
  return null;
}

function onEnterSubmit(e: KeyboardEvent, submit: () => void | Promise<void>) {
  if (e.isComposing || e.key !== "Enter" || e.shiftKey) return;
  e.preventDefault();
  void submit();
}

function openCreate() {
  newId.value = "";
  newTitle.value = "";
  createError.value = "";
  showCreate.value = true;
}

watch(showCreate, async (open) => {
  if (!open) return;
  await nextTick();
  createIdRef.value?.focus();
});

async function createDesign() {
  if (creating.value) return;
  const id = newId.value.trim();
  const title = newTitle.value.trim();
  const idErr = validateScenarioId(id);
  if (idErr) {
    createError.value = idErr;
    return;
  }
  if (!title) {
    createError.value = "请填写标题";
    return;
  }
  createError.value = "";
  creating.value = true;
  try {
    await api.createScenario({ id, title });
    showCreate.value = false;
    await router.push(`/design/${id}?mode=chat`);
  } catch (e) {
    createError.value = e instanceof Error ? e.message : String(e);
  } finally {
    creating.value = false;
  }
}

function openDuplicate(s: ScenarioRow) {
  dupSource.value = s;
  dupId.value = `${s.id}-copy`;
  dupTitle.value = `${s.title} (副本)`;
  dupError.value = "";
}

async function confirmDuplicate() {
  if (!dupSource.value || creating.value) return;
  const id = dupId.value.trim();
  const title = dupTitle.value.trim();
  const idErr = validateScenarioId(id);
  if (idErr) {
    dupError.value = idErr;
    return;
  }
  if (!title) {
    dupError.value = "请填写标题";
    return;
  }
  dupError.value = "";
  creating.value = true;
  try {
    await designerApi.duplicate(dupSource.value.id, id, title);
    dupSource.value = null;
    await router.push(`/design/${id}?mode=chat`);
  } catch (e) {
    dupError.value = e instanceof Error ? e.message : String(e);
  } finally {
    creating.value = false;
  }
}

function relTime(iso: string | null | undefined) {
  if (!iso) return "无对话";
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

onMounted(load);
</script>

<template>
  <section>
    <h1>场景设计</h1>
    <p class="hint">选择场景进入设计工作台, 或用一句话主题让 Agent 协助生成场景包。</p>

    <div class="actions">
      <button type="button" @click="openCreate">新建设计</button>
      <button type="button" class="ghost" disabled title="P3+ 推演引擎">开始推演</button>
    </div>

    <p v-if="loading">加载中…</p>
    <p v-else-if="error" class="error">{{ error }}</p>

    <ul v-else class="list">
      <li v-for="s in scenarios" :key="s.id" class="card">
        <div class="main">
          <div class="title">{{ s.title }}</div>
          <div class="meta">
            <span>{{ s.id }}</span>
            <span>{{ s.source === "builtin" ? "内置" : "用户" }}</span>
            <span v-if="s.chat_count">{{ s.chat_count }} 个对话 · {{ relTime(s.last_chat_at) }}</span>
          </div>
        </div>
        <div class="btns">
          <RouterLink v-if="!s.readonly" :to="`/design/${s.id}?mode=chat`" class="btn primary">设计</RouterLink>
          <button v-else type="button" class="btn" @click="openDuplicate(s)">另存为副本</button>
          <RouterLink :to="`/scenarios/${s.id}`" class="btn ghost">浏览</RouterLink>
        </div>
      </li>
    </ul>

    <div v-if="showCreate" class="modal" @click.self="showCreate = false">
      <form class="dialog" novalidate @submit.prevent="createDesign">
        <h2>新建设计</h2>
        <label>
          ID (a-z0-9-)
          <input
            ref="createIdRef"
            v-model="newId"
            placeholder="france-1848"
            autocomplete="off"
            :disabled="creating"
            @keydown="onEnterSubmit($event, createDesign)"
          />
        </label>
        <label>
          标题
          <input
            v-model="newTitle"
            placeholder="法国1848"
            autocomplete="off"
            :disabled="creating"
            @keydown="onEnterSubmit($event, createDesign)"
          />
        </label>
        <p class="tip">创建后将进入对话模式, 用第一句话描述你想做的历史场景。</p>
        <p v-if="createError" class="error">{{ createError }}</p>
        <div class="row">
          <button type="button" @click="showCreate = false">取消</button>
          <button type="submit" :disabled="creating">{{ creating ? "创建中…" : "创建并进入" }}</button>
        </div>
      </form>
    </div>

    <div v-if="dupSource" class="modal" @click.self="dupSource = null">
      <form class="dialog" novalidate @submit.prevent="confirmDuplicate">
        <h2>另存为副本</h2>
        <p>基于内置场景「{{ dupSource.title }}」创建可编辑副本。</p>
        <label>
          新 ID
          <input
            v-model="dupId"
            autocomplete="off"
            :disabled="creating"
            @keydown="onEnterSubmit($event, confirmDuplicate)"
          />
        </label>
        <label>
          标题
          <input
            v-model="dupTitle"
            autocomplete="off"
            :disabled="creating"
            @keydown="onEnterSubmit($event, confirmDuplicate)"
          />
        </label>
        <p v-if="dupError" class="error">{{ dupError }}</p>
        <div class="row">
          <button type="button" @click="dupSource = null">取消</button>
          <button type="submit" :disabled="creating">创建副本</button>
        </div>
      </form>
    </div>
  </section>
</template>

<style scoped>
.hint {
  color: var(--text-muted);
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin: 1rem 0;
}
.actions button,
.btn {
  padding: 0.5rem 1rem;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--panel-bg);
  text-decoration: none;
  color: inherit;
  font-size: 0.9rem;
}
.actions button:first-child,
.btn.primary {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.ghost {
  color: var(--text-muted);
}
.list {
  list-style: none;
  padding: 0;
  margin: 1rem 0;
  display: grid;
  gap: 0.75rem;
}
.card {
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}
.title {
  font-size: 1.05rem;
  font-weight: 600;
}
.meta {
  margin-top: 0.35rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  font-size: 0.85rem;
  color: var(--text-muted);
}
.btns {
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
}
.modal {
  position: fixed;
  inset: 0;
  background: rgb(0 0 0 / 25%);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 40;
}
.dialog {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1.25rem;
  width: min(400px, 92vw);
  display: grid;
  gap: 0.75rem;
}
.dialog label {
  display: grid;
  gap: 0.25rem;
  font-size: 0.9rem;
}
.dialog input {
  padding: 0.5rem;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.tip {
  font-size: 0.82rem;
  color: var(--text-muted);
  margin: 0;
}
.dialog .error {
  margin: 0;
  font-size: 0.85rem;
}
.row {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
.error {
  color: #ba2525;
}
</style>
