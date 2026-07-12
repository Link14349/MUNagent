<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api, type ScenarioDetail } from "../api";

const route = useRoute();
const detail = ref<ScenarioDetail | null>(null);
const selectedFile = ref("");
const loading = ref(true);
const error = ref("");

const fileList = computed(() =>
  detail.value ? Object.keys(detail.value.files).sort() : []
);

const fileContent = computed(() =>
  detail.value && selectedFile.value ? detail.value.files[selectedFile.value] : ""
);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const id = route.params.id as string;
    detail.value = await api.getScenario(id);
    const files = Object.keys(detail.value.files).sort();
    selectedFile.value = files[0] || "";
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section v-if="loading">加载中…</section>
  <section v-else-if="error" class="error">{{ error }}</section>
  <section v-else-if="detail">
    <RouterLink to="/">← 返回</RouterLink>
    <h1>{{ detail.title }}</h1>
    <p class="meta">
      {{ detail.id }} · {{ detail.source === "builtin" ? "内置" : "用户" }}
      <span v-if="detail.readonly">· 只读</span>
    </p>

    <div class="browser">
      <aside>
        <h2>文件</h2>
        <ul>
          <li
            v-for="f in fileList"
            :key="f"
            :class="{ active: f === selectedFile }"
            @click="selectedFile = f"
          >
            {{ f }}
          </li>
        </ul>
      </aside>
      <pre class="content">{{ fileContent }}</pre>
    </div>
  </section>
</template>

<style scoped>
.meta {
  color: #627d98;
}
.browser {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 1rem;
  margin-top: 1rem;
  min-height: 420px;
}
aside {
  background: #fff;
  border-radius: 8px;
  padding: 0.75rem;
  box-shadow: 0 1px 3px rgb(0 0 0 / 8%);
}
aside ul {
  list-style: none;
  padding: 0;
  margin: 0;
  font-size: 0.85rem;
}
aside li {
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  word-break: break-all;
}
aside li.active {
  background: #e6f0ff;
  color: #1d5bbf;
}
.content {
  background: #fff;
  border-radius: 8px;
  padding: 1rem;
  margin: 0;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.85rem;
  line-height: 1.5;
  box-shadow: 0 1px 3px rgb(0 0 0 / 8%);
}
.error {
  color: #ba2525;
}
</style>
