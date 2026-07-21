<script setup lang="ts">
import { ref, watch } from "vue";
import ModalDialog from "../ui/ModalDialog.vue";
import { injectDesigner } from "../../composables/useDesigner";

const props = defineProps<{
  open: boolean;
  chatId: string;
  chatTitle: string;
}>();

const emit = defineEmits<{ close: []; deleted: [] }>();

const d = injectDesigner();
const loading = ref(false);
const error = ref("");

watch(
  () => props.open,
  (open) => {
    if (!open) return;
    loading.value = false;
    error.value = "";
  }
);

async function submit() {
  loading.value = true;
  error.value = "";
  try {
    await d.deleteChat(props.chatId);
    emit("deleted");
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
    title="删除会话"
    :dismiss-on-backdrop="!loading"
    @close="emit('close')"
  >
    <p class="lead">
      确定删除会话 <strong>{{ chatTitle }}</strong>？对话记录将永久删除，此操作不可撤销。
    </p>
    <p v-if="error" class="error">{{ error }}</p>

    <template #footer>
      <button type="button" class="btn ghost" :disabled="loading" @click="emit('close')">取消</button>
      <button type="button" class="btn danger" :disabled="loading" @click="submit">
        {{ loading ? "删除中…" : "删除" }}
      </button>
    </template>
  </ModalDialog>
</template>

<style scoped>
.lead {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.5;
}

.lead strong {
  font-weight: 600;
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

.btn.danger {
  background: #ba2525;
  color: #fff;
  border-color: #ba2525;
}

.btn.ghost {
  color: var(--text-muted);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
