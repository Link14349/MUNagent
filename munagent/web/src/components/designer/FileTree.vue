<script setup lang="ts">
import { computed, watch } from "vue";
import type { FileNode } from "../../types/designer";
import { useFileTreeExpand } from "../../composables/useFileTreeExpand";
import FileTreeNode from "./FileTreeNode.vue";

const props = defineProps<{
  scenarioId: string;
  nodes: FileNode[];
  selected?: string | null;
  compact?: boolean;
  highlightPaths?: string[];
}>();

const emit = defineEmits<{
  select: [path: string];
  createFile: [];
}>();

const { collapsed, toggleDir, isExpanded, revealPath } = useFileTreeExpand(props.scenarioId);

/** 订阅 composable 内的 collapsed, 否则折叠状态变化不会触发重渲染 */
const collapsedKey = computed(() => [...collapsed.value].sort().join("\0"));

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
    <ul class="root" :data-collapsed-key="collapsedKey">
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
