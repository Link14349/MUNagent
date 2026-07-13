<script setup lang="ts">
import { ref, watch } from "vue";
import ModalDialog from "../ui/ModalDialog.vue";
import { designerApi } from "../../api/designerApi";

const props = defineProps<{
  open: boolean;
  scenarioId: string;
  hasErrors: boolean;
}>();

const emit = defineEmits<{ close: []; success: [] }>();

const includeRaw = ref(false);
const loading = ref(false);
const error = ref("");

watch(
  () => props.open,
  (open) => {
    if (!open) return;
    includeRaw.value = false;
    loading.value = false;
    error.value = "";
  }
);

async function submit() {
  loading.value = true;
  error.value = "";
  try {
    await designerApi.exportZip(props.scenarioId, includeRaw.value);
    emit("success");
    emit("close");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <ModalDialog
    :open="open"
    title="导出场景包"
    :dismiss-on-backdrop="!loading"
    @close="emit('close')"
  >
    <p class="lead">将当前场景打包为 ZIP 并下载到本地。</p>

    <div v-if="hasErrors" class="warn-box">
      校验仍有错误。导出不会阻止下载, 但包内内容可能不完整或无法通过校验。
    </div>

    <label class="check-row">
      <input v-model="includeRaw" type="checkbox" :disabled="loading" />
      <span>包含 <code>references/raw/</code> 原始文件 (PDF 等, 体积较大)</span>
    </label>

    <p v-if="error" class="error">{{ error }}</p>

    <template #footer>
      <button type="button" class="btn ghost" :disabled="loading" @click="emit('close')">取消</button>
      <button type="button" class="btn primary" :disabled="loading" @click="submit">
        {{ loading ? "导出中…" : "导出 ZIP" }}
      </button>
    </template>
  </ModalDialog>
</template>

<style scoped>
.lead {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.9rem;
  line-height: 1.5;
}

.warn-box {
  padding: 0.65rem 0.75rem;
  border-radius: 8px;
  border: 1px solid #e6c200;
  background: #fffbe6;
  color: #7a6200;
  font-size: 0.85rem;
  line-height: 1.45;
}

.check-row {
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  font-size: 0.9rem;
  line-height: 1.45;
  cursor: pointer;
}

.check-row input {
  margin-top: 0.2rem;
}

.check-row code {
  font-size: 0.82rem;
  background: var(--chip-bg);
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
}

.error {
  margin: 0;
  color: #ba2525;
  font-size: 0.85rem;
}

.btn {
  padding: 0.45rem 0.9rem;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--panel-bg);
  font-size: 0.88rem;
}

.btn.primary {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.btn.ghost {
  color: var(--text-muted);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
