<script setup lang="ts">
import type { FileNode } from "../../types/designer";
import { canDeleteFile } from "../../utils/scenarioFiles";

const props = defineProps<{
  node: FileNode;
  selected?: string | null;
  highlightPaths?: string[];
  readonly?: boolean;
  isExpanded: (path: string) => boolean;
  toggleDir: (path: string) => void;
}>();

const emit = defineEmits<{
  select: [path: string];
  contextMenu: [payload: { path: string; kind: "file" | "dir"; x: number; y: number }];
}>();

const expanded = () => props.isExpanded(props.node.path);

function onFileContextMenu(e: MouseEvent) {
  if (props.node.kind !== "file") return;
  if (!canDeleteFile(props.node.path, !!props.readonly)) return;
  e.preventDefault();
  e.stopPropagation();
  emit("contextMenu", { path: props.node.path, kind: "file", x: e.clientX, y: e.clientY });
}

function onDirContextMenu(e: MouseEvent) {
  if (props.readonly || props.node.kind !== "dir") return;
  e.preventDefault();
  e.stopPropagation();
  emit("contextMenu", { path: props.node.path, kind: "dir", x: e.clientX, y: e.clientY });
}
</script>

<template>
  <li
    v-if="props.node.kind === 'file'"
    :class="['file', { sel: selected === props.node.path, hi: highlightPaths?.includes(props.node.path) }]"
    @click="emit('select', props.node.path)"
    @contextmenu="onFileContextMenu"
  >
    <span class="indent" />
    {{ props.node.name }}
  </li>
  <li v-else class="dir">
    <button type="button" class="dir-head" @click="toggleDir(props.node.path)" @contextmenu="onDirContextMenu">
      <span class="chevron">{{ expanded() ? "▾" : "▸" }}</span>
      <span class="name">{{ props.node.name }}</span>
    </button>
    <ul v-show="expanded()">
      <FileTreeNode
        v-for="child in props.node.children"
        :key="child.path"
        :node="child"
        :selected="selected"
        :highlight-paths="highlightPaths"
        :readonly="readonly"
        :is-expanded="isExpanded"
        :toggle-dir="toggleDir"
        @select="emit('select', $event)"
        @context-menu="emit('contextMenu', $event)"
      />
    </ul>
  </li>
</template>

<style scoped>
.file {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.85rem 0.25rem 0.5rem;
  cursor: pointer;
}
.indent {
  width: 0.9rem;
  flex-shrink: 0;
}
.file:hover,
.file.sel {
  background: var(--hover);
}
.file.sel {
  font-weight: 600;
}
.file.hi {
  color: var(--accent);
}
.dir-head {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  width: 100%;
  padding: 0.25rem 0.85rem 0.25rem 0.5rem;
  border: none;
  background: transparent;
  text-align: left;
  color: var(--text-muted);
  font-weight: 500;
  font-size: inherit;
}
.dir-head:hover {
  background: var(--hover);
}
.chevron {
  width: 0.9rem;
  flex-shrink: 0;
  font-size: 0.7rem;
  color: var(--text-muted);
}
.name {
  color: var(--text);
}
ul {
  list-style: none;
  margin: 0;
  padding-left: 0.65rem;
}
</style>
