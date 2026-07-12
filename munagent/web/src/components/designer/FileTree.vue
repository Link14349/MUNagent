<script setup lang="ts">
import { ref, watch } from "vue";
import type { FileNode } from "../../types/designer";
import FileTreeNode from "./FileTreeNode.vue";

const props = defineProps<{
  nodes: FileNode[];
  selected?: string | null;
  compact?: boolean;
  highlightPaths?: string[];
}>();

const emit = defineEmits<{
  select: [path: string];
  createFile: [];
}>();

/** 记录折叠的目录 path; 默认全部展开 */
const collapsed = ref(new Set<string>());

function toggleDir(path: string) {
  const next = new Set(collapsed.value);
  if (next.has(path)) next.delete(path);
  else next.add(path);
  collapsed.value = next;
}

function isExpanded(path: string) {
  return !collapsed.value.has(path);
}

function revealPath(path: string) {
  const parts = path.split("/");
  if (parts.length <= 1) return;
  const next = new Set(collapsed.value);
  for (let i = 1; i < parts.length; i++) {
    next.delete(parts.slice(0, i).join("/"));
  }
  collapsed.value = next;
}

watch(
  () => props.selected,
  (p) => {
    if (p) revealPath(p);
  },
  { immediate: true }
);
</script>

<template>
  <div class="tree" :class="{ compact }">
    <div class="head">
      <span>文件</span>
      <button type="button" class="link" @click="emit('createFile')">+ 新建</button>
    </div>
    <ul class="root">
      <FileTreeNode
        v-for="node in nodes"
        :key="node.path"
        :node="node"
        :selected="selected"
        :highlight-paths="highlightPaths"
        :is-expanded="isExpanded"
        :toggle-dir="toggleDir"
        @select="emit('select', $event)"
      />
    </ul>
  </div>
</template>

<style scoped>
.tree {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-size: 0.85rem;
  background: var(--panel-bg);
}
.head {
  display: flex;
  justify-content: space-between;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--border);
  font-weight: 600;
  color: var(--text-muted);
}
.link {
  border: none;
  background: none;
  color: var(--accent);
  font-size: 0.8rem;
}
.root {
  list-style: none;
  margin: 0;
  padding: 0.35rem 0;
  flex: 1;
  min-height: 0;
  overflow: auto;
}
</style>
