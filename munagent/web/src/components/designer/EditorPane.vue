<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { injectDesigner } from "../../composables/useDesigner";
import CodeEditor from "./CodeEditor.vue";

const d = injectDesigner();
let saveTimer: ReturnType<typeof setTimeout> | null = null;

const activeTab = computed(() =>
  d.openFiles.find((t) => t.path === d.activeFilePath)
);

function selectTab(path: string) {
  d.activeFilePath = path;
  d.contextFile = path;
}

function saveNow() {
  const tab = activeTab.value;
  if (!tab || d.readonly) return;
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  if (!tab.dirty) return;
  void d.saveFile(tab.path);
}

function onEditorChange(value: string) {
  const tab = activeTab.value;
  if (!tab) return;
  tab.content = value;
  tab.dirty = tab.content !== tab.savedContent;
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => d.saveFile(tab.path), 800);
}

function onKeydown(e: KeyboardEvent) {
  if (!(e.metaKey || e.ctrlKey)) return;
  const key = e.key.toLowerCase();
  if (key === "s") {
    e.preventDefault();
    saveNow();
    return;
  }
  if (key === "w" && d.activeFilePath) {
    e.preventDefault();
    d.closeTab(d.activeFilePath);
  }
}

onMounted(() => window.addEventListener("keydown", onKeydown, true));
onUnmounted(() => {
  window.removeEventListener("keydown", onKeydown, true);
  if (saveTimer) clearTimeout(saveTimer);
});

function resolveConflict(path: string, useAgent: boolean) {
  const tab = d.openFiles.find((t) => t.path === path);
  if (!tab) return;
  if (useAgent && tab.agentConflict) {
    tab.content = tab.agentConflict;
    tab.savedContent = tab.agentConflict;
    tab.dirty = false;
  }
  tab.agentConflict = undefined;
}

watch(
  () => d.activeFilePath,
  (p) => {
    if (p) d.contextFile = p;
  }
);
</script>

<template>
  <div class="editor-pane">
    <div v-if="!d.openFiles.length" class="empty">从左侧文件树打开文件</div>
    <template v-else>
      <div class="tabs">
        <button
          v-for="tab in d.openFiles"
          :key="tab.path"
          type="button"
          :class="['tab', { active: tab.path === d.activeFilePath }]"
          @click="selectTab(tab.path)"
        >
          {{ tab.path.split("/").pop() }}
          <span v-if="tab.dirty" class="dot">●</span>
          <span class="close" @click.stop="d.closeTab(tab.path)">×</span>
        </button>
      </div>
      <div v-if="activeTab?.agentConflict" class="conflict">
        Agent 已更新此文件
        <button type="button" @click="resolveConflict(activeTab.path, false)">保留我的</button>
        <button type="button" @click="resolveConflict(activeTab.path, true)">用 agent 的</button>
      </div>
      <CodeEditor
        v-if="activeTab"
        :key="activeTab.path"
        class="editor"
        :model-value="activeTab.content"
        :path="activeTab.path"
        @update:model-value="onEditorChange"
      />
    </template>
  </div>
</template>

<style scoped>
.editor-pane {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--panel-bg);
  border: none;
  border-radius: 0;
  overflow: hidden;
}
.empty {
  margin: auto;
  color: var(--text-muted);
}
.tabs {
  display: flex;
  gap: 2px;
  padding: 0.35rem 0.5rem 0;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  flex-shrink: 0;
}
.tab {
  border: none;
  background: transparent;
  padding: 0.4rem 0.65rem;
  font-size: 0.8rem;
  border-radius: 6px 6px 0 0;
  color: var(--text-muted);
}
.tab.active {
  background: var(--bg);
  color: var(--text);
  font-weight: 600;
}
.dot {
  color: var(--accent);
  margin-left: 0.2rem;
}
.close {
  margin-left: 0.35rem;
  opacity: 0.5;
}
.conflict {
  padding: 0.5rem 0.75rem;
  background: #fff8e6;
  border-bottom: 1px solid #f0d78c;
  font-size: 0.85rem;
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-shrink: 0;
}
.editor {
  flex: 1;
  min-height: 0;
}
</style>
