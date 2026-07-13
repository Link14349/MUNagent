<script setup lang="ts">
import { computed, ref, watch } from "vue";
import ModalDialog from "../ui/ModalDialog.vue";
import { useDesigner } from "../../composables/useDesigner";

const props = defineProps<{
  open: boolean;
  scenarioId: string;
  path: string;
}>();

const emit = defineEmits<{ close: []; deleted: [path: string] }>();

const d = useDesigner(props.scenarioId);
const loading = ref(false);
const error = ref("");

const isSeatFile = computed(() => props.path.startsWith("seats/"));

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
    await d.deleteFile(props.path);
    emit("deleted", props.path);
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
    title="删除文件"
    :dismiss-on-backdrop="!loading"
    @close="emit('close')"
  >
    <p class="lead">
      确定删除 <code>{{ path }}</code>？此操作不可撤销。
    </p>

    <div v-if="isSeatFile" class="warn-box">
      删除席位文件前, 请确认已从 <code>venues.yaml</code> 中移除对应条目
      (含 <code>presiding_seat</code> / <code>veto_seats</code> 联动)。
    </div>

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

.lead code {
  font-size: 0.85rem;
  background: var(--chip-bg);
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
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

.warn-box code {
  font-size: 0.8rem;
  background: rgb(255 255 255 / 55%);
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
