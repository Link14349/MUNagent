<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import ModalDialog from "../ui/ModalDialog.vue";
import { designerApi } from "../../api/designerApi";

const props = defineProps<{
  open: boolean;
  scenarioId: string;
  /** 从文件夹右键新建时预填目录前缀, 如 seats */
  defaultDir?: string;
}>();

const emit = defineEmits<{ close: []; created: [path: string] }>();

const path = ref("");
const loading = ref(false);
const error = ref("");
const inputRef = ref<HTMLInputElement | null>(null);

const placeholder = computed(() => {
  const dir = props.defaultDir || "";
  if (dir === "seats") return "new_delegate.yaml";
  if (dir.startsWith("references")) return "doc.md";
  return dir ? "filename.md" : "notes.md 或 seats/new_delegate.yaml";
});

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    path.value = props.defaultDir ? `${props.defaultDir}/` : "";
    loading.value = false;
    error.value = "";
    await nextTick();
    inputRef.value?.focus();
    if (props.defaultDir && inputRef.value) {
      const el = inputRef.value;
      el.setSelectionRange(el.value.length, el.value.length);
    }
  }
);

function defaultContent(filePath: string) {
  if (filePath.endsWith(".md")) return "# 新文件\n\n";
  if (filePath.endsWith(".yaml") || filePath.endsWith(".yml")) return "";
  return "";
}

async function submit() {
  const trimmed = path.value.trim();
  if (!trimmed) {
    error.value = "请输入文件路径";
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    await designerApi.putFile(props.scenarioId, trimmed, defaultContent(trimmed));
    emit("created", trimmed);
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
    title="新建文件"
    :dismiss-on-backdrop="!loading"
    @close="emit('close')"
  >
    <form id="create-file-form" @submit.prevent="submit">
      <label class="field">
        <span>路径 (相对场景包根目录)</span>
        <input
          ref="inputRef"
          v-model="path"
          type="text"
          required
          :placeholder="placeholder"
          :disabled="loading"
          spellcheck="false"
        />
      </label>
      <p class="tip">
        支持文本文件, 如 <code>.md</code> / <code>.yaml</code> / <code>.txt</code>。
        新建席位时须与 <code>venues.yaml</code> 中的席位清单保持一致。
      </p>
      <p v-if="error" class="error">{{ error }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn ghost" :disabled="loading" @click="emit('close')">取消</button>
      <button type="submit" form="create-file-form" class="btn primary" :disabled="loading">
        {{ loading ? "创建中…" : "创建并打开" }}
      </button>
    </template>
  </ModalDialog>
</template>

<style scoped>
.field {
  display: grid;
  gap: 0.35rem;
  font-size: 0.9rem;
}

.field input {
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
}

.field input:focus {
  outline: 2px solid var(--accent-soft);
  border-color: var(--accent);
}

.tip {
  margin: 0;
  font-size: 0.82rem;
  color: var(--text-muted);
  line-height: 1.45;
}

.tip code {
  font-size: 0.8rem;
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
