<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import ModalDialog from "../ui/ModalDialog.vue";
import { injectDesigner } from "../../composables/useDesigner";

const props = defineProps<{
  open: boolean;
  chatId: string;
  initialTitle: string;
}>();

const emit = defineEmits<{ close: []; renamed: [title: string] }>();

const d = injectDesigner();
const title = ref("");
const loading = ref(false);
const error = ref("");
const inputRef = ref<HTMLInputElement | null>(null);

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    title.value = props.initialTitle;
    loading.value = false;
    error.value = "";
    await nextTick();
    inputRef.value?.focus();
    inputRef.value?.select();
  }
);

async function submit() {
  const next = title.value.trim();
  if (!next) {
    error.value = "标题不能为空";
    return;
  }
  if (next === props.initialTitle) {
    emit("close");
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    await d.renameChat(props.chatId, next);
    emit("renamed", next);
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
    title="修改会话标题"
    :dismiss-on-backdrop="!loading"
    @close="emit('close')"
  >
    <form id="rename-chat-form" @submit.prevent="submit">
      <label class="field">
        <span>标题</span>
        <input
          ref="inputRef"
          v-model="title"
          type="text"
          maxlength="64"
          autocomplete="off"
          :disabled="loading"
        />
      </label>
      <p v-if="error" class="error">{{ error }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn ghost" :disabled="loading" @click="emit('close')">取消</button>
      <button type="submit" form="rename-chat-form" class="btn primary" :disabled="loading">
        {{ loading ? "保存中…" : "保存" }}
      </button>
    </template>
  </ModalDialog>
</template>

<style scoped>
.field {
  display: grid;
  gap: 0.35rem;
  font-size: 0.85rem;
}

.field span {
  color: var(--text-muted);
}

.field input {
  width: 100%;
  padding: 0.5rem 0.65rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  font-size: 0.9rem;
}

.field input:focus {
  outline: 2px solid var(--accent-soft);
  border-color: var(--accent);
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
