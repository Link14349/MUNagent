<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api, type ConfigPublic } from "../api";

const loading = ref(true);
const saving = ref(false);
const message = ref("");
const error = ref("");

const form = reactive({
  deepseekBaseUrl: "",
  deepseekApiKey: "",
  mineruUrl: "",
  searchProvider: "tavily",
  searchApiKey: "",
  roles: {} as Record<string, { provider: string; model: string }>,
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const cfg: ConfigPublic = await api.getConfig();
    const ds = cfg.providers.deepseek;
    if (ds) {
      form.deepseekBaseUrl = ds.base_url;
      form.deepseekApiKey = "";
    }
    form.mineruUrl = cfg.tools.mineru.base_url;
    form.searchProvider = cfg.tools.search.provider;
    form.searchApiKey = "";
    form.roles = { ...cfg.roles };
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  message.value = "";
  error.value = "";
  try {
    const providers: Record<string, Record<string, string>> = {
      deepseek: { base_url: form.deepseekBaseUrl },
    };
    if (form.deepseekApiKey.trim()) {
      providers.deepseek.api_key = form.deepseekApiKey.trim();
    }
    const tools: Record<string, unknown> = {
      mineru: { base_url: form.mineruUrl },
      search: { provider: form.searchProvider },
    };
    if (form.searchApiKey.trim()) {
      (tools.search as Record<string, string>).api_key = form.searchApiKey.trim();
    }
    const updated = await api.putConfig({ providers, roles: form.roles, tools });
    message.value = `已保存。DeepSeek key: ${updated.providers.deepseek?.api_key_masked}`;
    form.deepseekApiKey = "";
    form.searchApiKey = "";
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

async function test(target: string) {
  message.value = "";
  error.value = "";
  try {
    const res = await api.testConfig(target);
    if (res.ok) message.value = res.message;
    else error.value = res.message;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

onMounted(load);
</script>

<template>
  <section>
    <h1>设置</h1>
    <p v-if="loading">加载中…</p>
    <form v-else class="form" @submit.prevent="save">
      <fieldset>
        <legend>LLM — DeepSeek</legend>
        <label>
          Base URL
          <input v-model="form.deepseekBaseUrl" required />
        </label>
        <label>
          API Key（留空则不修改）
          <input v-model="form.deepseekApiKey" type="password" autocomplete="off" placeholder="sk-..." />
        </label>
        <button type="button" class="secondary" @click="test('provider:deepseek')">测试连接</button>
      </fieldset>

      <fieldset>
        <legend>工具 — MinerU</legend>
        <label>
          Base URL
          <input v-model="form.mineruUrl" />
        </label>
        <button type="button" class="secondary" @click="test('tool:mineru')">测试连接</button>
      </fieldset>

      <fieldset>
        <legend>工具 — 搜索</legend>
        <label>
          Provider
          <select v-model="form.searchProvider">
            <option value="tavily">tavily</option>
            <option value="serper">serper</option>
            <option value="bocha">bocha</option>
          </select>
        </label>
        <label>
          API Key（留空则不修改）
          <input v-model="form.searchApiKey" type="password" autocomplete="off" />
        </label>
        <button type="button" class="secondary" @click="test('tool:search')">测试连接</button>
      </fieldset>

      <fieldset>
        <legend>角色模型路由</legend>
        <div v-for="(role, name) in form.roles" :key="name" class="role-row">
          <strong>{{ name }}</strong>
          <input v-model="role.model" placeholder="model" />
        </div>
      </fieldset>

      <button type="submit" :disabled="saving">{{ saving ? "保存中…" : "保存配置" }}</button>
      <p v-if="message" class="ok">{{ message }}</p>
      <p v-if="error" class="error">{{ error }}</p>
    </form>
  </section>
</template>

<style scoped>
.form {
  display: grid;
  gap: 1.25rem;
  max-width: 560px;
}
fieldset {
  border: 1px solid #cbd2d9;
  border-radius: 8px;
  padding: 1rem;
  background: #fff;
}
legend {
  padding: 0 0.5rem;
  font-weight: 600;
}
label {
  display: grid;
  gap: 0.25rem;
  margin-bottom: 0.75rem;
  font-size: 0.9rem;
}
input,
select {
  padding: 0.5rem;
  border: 1px solid #cbd2d9;
  border-radius: 4px;
}
button[type="submit"] {
  justify-self: start;
  padding: 0.55rem 1.2rem;
  background: #1d5bbf;
  color: #fff;
  border: none;
  border-radius: 6px;
}
.secondary {
  padding: 0.4rem 0.8rem;
  margin-bottom: 0.5rem;
  background: #f0f4f8;
  border: 1px solid #cbd2d9;
  border-radius: 6px;
}
.role-row {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.5rem;
}
.ok {
  color: #0f7b6c;
}
.error {
  color: #ba2525;
}
</style>
