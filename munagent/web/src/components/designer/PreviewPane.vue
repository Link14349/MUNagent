<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { marked } from "marked";
import { injectDesigner } from "../../composables/useDesigner";
import { designerApi } from "../../api/designerApi";

const d = injectDesigner();
const content = ref("");

const html = computed(() => {
  const path = d.previewPath;
  if (!path) return "";
  if (path.endsWith(".md")) return marked.parse(content.value) as string;
  return `<pre class="yaml">${escapeHtml(content.value)}</pre>`;
});

watch(
  () => d.previewPath,
  async (path) => {
    if (!path) {
      content.value = "";
      return;
    }
    try {
      const f = await designerApi.getFile(d.scenarioId, path);
      content.value = f.content;
    } catch {
      content.value = "(无法加载)";
    }
  },
  { immediate: true }
);

function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

const emit = defineEmits<{ openInEdit: [] }>();
</script>

<template>
  <div class="preview">
    <div class="bar">
      <span>{{ d.previewPath || "选择文件预览" }}</span>
      <button v-if="d.previewPath" type="button" class="link" @click="emit('openInEdit')">
        在编辑模式打开
      </button>
    </div>
    <div v-if="d.previewPath" class="body prose" v-html="html" />
    <div v-else class="empty">单击文件树中的文件进行预览</div>
  </div>
</template>

<style scoped>
.preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.bar {
  display: flex;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
  font-size: 0.8rem;
  color: var(--text-muted);
}
.link {
  border: none;
  background: none;
  color: var(--accent);
}
.body {
  flex: 1;
  overflow: auto;
  padding: 1rem;
  font-size: 0.9rem;
}
.empty {
  margin: auto;
  color: var(--text-muted);
  font-size: 0.9rem;
}
:deep(pre.yaml) {
  margin: 0;
  white-space: pre-wrap;
  font-family: ui-monospace, monospace;
  font-size: 0.85rem;
}
:deep(.prose h1) {
  font-size: 1.25rem;
}
</style>
