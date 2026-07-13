<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import type { FileNode } from "../../types/designer";
import { useFileTreeExpand } from "../../composables/useFileTreeExpand";
import { useDesigner } from "../../composables/useDesigner";
import FileTreeNode from "./FileTreeNode.vue";
import FileContextMenu from "./FileContextMenu.vue";
import DeleteFileDialog from "./DeleteFileDialog.vue";
import CreateFileDialog from "./CreateFileDialog.vue";

const props = defineProps<{
  scenarioId: string;
  nodes: FileNode[];
  selected?: string | null;
  compact?: boolean;
  highlightPaths?: string[];
  readonly?: boolean;
}>();

const emit = defineEmits<{
  select: [path: string];
}>();

const d = useDesigner(props.scenarioId);
const readonly = computed(() => props.readonly ?? d.readonly);

const { collapsed, toggleDir, isExpanded, revealPath } = useFileTreeExpand(props.scenarioId);

/** 订阅 composable 内的 collapsed, 否则折叠状态变化不会触发重渲染 */
const collapsedKey = computed(() => [...collapsed.value].sort().join("\0"));

const menu = ref<{ path: string; kind: "file" | "dir"; x: number; y: number } | null>(null);
const deleteOpen = ref(false);
const deletePath = ref("");
const createOpen = ref(false);
const createDir = ref("");

watch(
  () => props.selected,
  (p) => {
    if (p) revealPath(p);
  },
  { immediate: true }
);

function closeMenu() {
  menu.value = null;
}

function onContextMenu(payload: { path: string; kind: "file" | "dir"; x: number; y: number }) {
  menu.value = payload;
}

function openDeleteDialog() {
  if (!menu.value) return;
  deletePath.value = menu.value.path;
  deleteOpen.value = true;
  closeMenu();
}

function openCreateDialog(dir = "") {
  createDir.value = dir;
  createOpen.value = true;
  closeMenu();
}

function openCreateFromMenu() {
  if (!menu.value || menu.value.kind !== "dir") return;
  openCreateDialog(menu.value.path);
}

async function onFileCreated(path: string) {
  await d.refreshFiles();
  revealPath(path);
  if (d.mode === "edit") {
    await d.openFile(path);
  } else {
    d.setPreview(path);
  }
}

onMounted(() => {
  window.addEventListener("click", closeMenu);
  window.addEventListener("scroll", closeMenu, true);
});

onUnmounted(() => {
  window.removeEventListener("click", closeMenu);
  window.removeEventListener("scroll", closeMenu, true);
});
</script>

<template>
  <div class="tree" :class="{ compact }">
    <div class="head">
      <span>文件</span>
      <button v-if="!readonly" type="button" class="link" @click="openCreateDialog()">+ 新建</button>
    </div>
    <ul class="root" :data-collapsed-key="collapsedKey">
      <FileTreeNode
        v-for="node in nodes"
        :key="node.path"
        :node="node"
        :selected="selected"
        :highlight-paths="highlightPaths"
        :readonly="readonly"
        :is-expanded="isExpanded"
        :toggle-dir="toggleDir"
        @select="emit('select', $event)"
        @context-menu="onContextMenu"
      />
    </ul>

    <FileContextMenu
      v-if="menu"
      :x="menu.x"
      :y="menu.y"
      :path="menu.path"
      :kind="menu.kind"
      @delete="openDeleteDialog"
      @create-file="openCreateFromMenu"
      @close="closeMenu"
    />

    <DeleteFileDialog
      :open="deleteOpen"
      :scenario-id="scenarioId"
      :path="deletePath"
      @close="deleteOpen = false"
    />

    <CreateFileDialog
      :open="createOpen"
      :scenario-id="scenarioId"
      :default-dir="createDir || undefined"
      @close="createOpen = false"
      @created="onFileCreated"
    />
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
