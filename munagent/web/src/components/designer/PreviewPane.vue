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

const emit = defineEmits<{ openInEdit: []; back: [] }>();
</script>

<template>
  <div class="preview">
    <div class="bar">
      <button type="button" class="back" title="返回文件树" @click="emit('back')">←</button>
      <span class="path" :title="d.previewPath || undefined">{{ d.previewPath }}</span>
      <button type="button" class="link" @click="emit('openInEdit')">编辑</button>
    </div>
    <div class="body prose" v-html="html" />
  </div>
</template>

<style scoped>
.preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.bar {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
  padding: 0.35rem 0.55rem;
  border-bottom: 1px solid var(--border);
  font-size: 0.75rem;
  color: var(--text-muted);
  min-height: 0;
}
.back {
  flex-shrink: 0;
  width: 1.5rem;
  height: 1.5rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text-muted);
  font-size: 0.85rem;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}
.back:hover {
  color: var(--text);
  border-color: #c4c4c0;
}
.path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  line-height: 1.35;
}
.link {
  flex-shrink: 0;
  border: none;
  background: none;
  color: var(--accent);
  white-space: nowrap;
  font-size: 0.75rem;
  padding: 0;
  cursor: pointer;
}
.body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0.75rem;
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
