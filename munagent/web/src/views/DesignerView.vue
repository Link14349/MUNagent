<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { provideDesigner } from "../composables/useDesigner";
import { SIDEBAR_DEFAULTS, useSidebarWidths } from "../composables/useSidebarWidths";
import FileTree from "../components/designer/FileTree.vue";
import EditorPane from "../components/designer/EditorPane.vue";
import PreviewPane from "../components/designer/PreviewPane.vue";
import ChatPanel from "../components/designer/ChatPanel.vue";
import ChatListPane from "../components/designer/ChatListPane.vue";
import ValidationChip from "../components/designer/ValidationChip.vue";
import HistoryDrawer from "../components/designer/HistoryDrawer.vue";
import DesignerSidebar from "../components/designer/DesignerSidebar.vue";
import ExportDialog from "../components/designer/ExportDialog.vue";

const route = useRoute();
const router = useRouter();
const scenarioId = computed(() => route.params.id as string);
const d = provideDesigner(scenarioId.value);

const historyOpen = ref(false);
const exportOpen = ref(false);
const leftCollapsed = ref(false);
const rightCollapsed = ref(false);

const COLLAPSED_W = 48;
const { widths, setWidth, resetWidth } = useSidebarWidths(scenarioId);

function paneKey(pane: "left" | "right") {
  return `designer-${scenarioId.value}-${pane}-collapsed`;
}

function loadPaneState() {
  leftCollapsed.value = localStorage.getItem(paneKey("left")) === "1";
  rightCollapsed.value = localStorage.getItem(paneKey("right")) === "1";
}

watch(leftCollapsed, (v) => localStorage.setItem(paneKey("left"), v ? "1" : "0"));
watch(rightCollapsed, (v) => localStorage.setItem(paneKey("right"), v ? "1" : "0"));

const layoutStyle = computed(() => {
  const mode = d.mode;
  const leftW = leftCollapsed.value ? COLLAPSED_W : widths[mode].left;
  const rightW = rightCollapsed.value ? COLLAPSED_W : widths[mode].right;
  return { gridTemplateColumns: `${leftW}px 1fr ${rightW}px` };
});

function onLeftWidth(w: number) {
  setWidth(d.mode, "left", w);
}

function onRightWidth(w: number) {
  setWidth(d.mode, "right", w);
}

function onLeftReset() {
  resetWidth(d.mode, "left");
}

function onRightReset() {
  resetWidth(d.mode, "right");
}

onMounted(async () => {
  loadPaneState();
  await d.init();
  const modeQ = route.query.mode as "edit" | "chat" | undefined;
  if (modeQ) d.setMode(modeQ);
  window.addEventListener("keydown", onKey);
});

onUnmounted(() => window.removeEventListener("keydown", onKey));

function onKey(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "e") {
    e.preventDefault();
    toggleMode();
  }
}

function toggleMode() {
  const next = d.mode === "edit" ? "chat" : "edit";
  d.setMode(next);
  router.replace({ query: { ...route.query, mode: next } });
}

function onTreeSelect(path: string) {
  if (d.mode === "edit") void d.openFile(path);
  else d.setPreview(path);
}

function onPreviewFile(path: string) {
  d.setPreview(path);
}

function onOpenInEdit(path: string) {
  d.setMode("edit");
  router.replace({ query: { ...route.query, mode: "edit", file: path } });
  void d.openFile(path);
}

function onValidationJump(path: string) {
  d.setMode("edit");
  void d.openFile(path);
}

async function duplicate() {
  const newId = prompt("副本 ID (a-z0-9-)", `${scenarioId.value}-copy`);
  if (!newId?.trim()) return;
  const newTitle = prompt("副本标题", `${d.title} (副本)`) || newId;
  const id = await d.duplicateScenario(newId.trim(), newTitle);
  await router.push(`/design/${id}?mode=chat`);
}

function formatTokens(n: number) {
  if (n < 1000) return `${n}`;
  return `${(n / 1000).toFixed(1)}k`;
}
</script>

<template>
  <div class="designer">
    <header class="top">
      <div class="left">
        <RouterLink to="/scenarios" class="brand">MUNagent</RouterLink>
        <span class="sep">|</span>
        <span class="title">{{ d.title }}</span>
        <span v-if="d.readonly" class="ro">只读 · <button type="button" @click="duplicate">另存为副本</button></span>
      </div>
      <div class="center">
        <div class="mode-switch">
          <button type="button" :class="{ on: d.mode === 'edit' }" @click="d.setMode('edit'); router.replace({ query: { ...route.query, mode: 'edit' } })">
            编辑
          </button>
          <button type="button" :class="{ on: d.mode === 'chat' }" @click="d.setMode('chat'); router.replace({ query: { ...route.query, mode: 'chat' } })">
            对话
          </button>
        </div>
        <ValidationChip @jump="onValidationJump" />
      </div>
      <div class="right">
        <button type="button" @click="historyOpen = true">🕘 历史</button>
        <button type="button" class="export" :class="{ warn: d.validation.some((v) => v.level === 'error') }" @click="exportOpen = true">
          导出
        </button>
      </div>
    </header>

    <div v-if="d.mode === 'edit'" class="layout edit" :style="layoutStyle">
      <DesignerSidebar
        side="left"
        icon="📁"
        label="文件树"
        :collapsed="leftCollapsed"
        :width="widths.edit.left"
        :default-width="SIDEBAR_DEFAULTS.edit.left"
        @update:collapsed="leftCollapsed = $event"
        @update:width="onLeftWidth"
        @reset-width="onLeftReset"
      >
        <FileTree
          :scenario-id="scenarioId"
          :nodes="d.fileTree"
          :selected="d.activeFilePath"
          @select="onTreeSelect"
        />
      </DesignerSidebar>

      <main class="center-pane">
        <EditorPane />
      </main>

      <DesignerSidebar
        side="right"
        icon="💬"
        label="对话"
        :collapsed="rightCollapsed"
        :width="widths.edit.right"
        :default-width="SIDEBAR_DEFAULTS.edit.right"
        @update:collapsed="rightCollapsed = $event"
        @update:width="onRightWidth"
        @reset-width="onRightReset"
      >
        <ChatPanel show-header @open-in-edit="onOpenInEdit" @preview-file="onPreviewFile" />
      </DesignerSidebar>
    </div>

    <div v-else class="layout chat" :style="layoutStyle">
      <DesignerSidebar
        side="left"
        icon="📋"
        label="对话列表"
        :collapsed="leftCollapsed"
        :width="widths.chat.left"
        :default-width="SIDEBAR_DEFAULTS.chat.left"
        @update:collapsed="leftCollapsed = $event"
        @update:width="onLeftWidth"
        @reset-width="onLeftReset"
      >
        <ChatListPane />
      </DesignerSidebar>

      <main class="center-pane chat-main">
        <ChatPanel wide :show-header="false" @open-in-edit="onOpenInEdit" @preview-file="onPreviewFile" />
      </main>

      <DesignerSidebar
        side="right"
        icon="📄"
        label="预览"
        :collapsed="rightCollapsed"
        :width="widths.chat.right"
        :default-width="SIDEBAR_DEFAULTS.chat.right"
        @update:collapsed="rightCollapsed = $event"
        @update:width="onRightWidth"
        @reset-width="onRightReset"
      >
        <div class="preview-stack">
          <FileTree
            v-show="!d.previewPath"
            :scenario-id="scenarioId"
            compact
            :nodes="d.fileTree"
            @select="onTreeSelect"
          />
          <PreviewPane
            v-show="!!d.previewPath"
            @open-in-edit="() => d.previewPath && onOpenInEdit(d.previewPath)"
            @back="d.setPreview(null)"
          />
        </div>
      </DesignerSidebar>
    </div>

    <footer class="status">
      <span v-if="d.activeFilePath && d.mode === 'edit'">{{ d.activeFilePath }}</span>
      <span v-else-if="d.previewPath && d.mode === 'chat'">{{ d.previewPath }}</span>
      <span v-else>—</span>
      <span>本场景 tokens: {{ formatTokens(d.totalTokens) }}</span>
    </footer>

    <HistoryDrawer :open="historyOpen" @close="historyOpen = false" />
    <ExportDialog
      :open="exportOpen"
      :scenario-id="scenarioId"
      :has-errors="d.validation.some((v) => v.level === 'error')"
      @close="exportOpen = false"
    />
  </div>
</template>

<style scoped>
.designer {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  overflow: hidden;
}
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.55rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--panel-bg);
  flex-shrink: 0;
}
.left,
.center,
.right {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}
.brand {
  font-weight: 700;
  color: var(--text);
  text-decoration: none;
}
.sep,
.title {
  color: var(--text-muted);
}
.ro {
  font-size: 0.8rem;
  color: #b8860b;
}
.ro button {
  border: none;
  background: none;
  color: var(--accent);
  text-decoration: underline;
}
.mode-switch {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.mode-switch button {
  border: none;
  background: transparent;
  padding: 0.3rem 0.75rem;
  font-size: 0.82rem;
}
.mode-switch button.on {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}
.right button {
  border: 1px solid var(--border);
  background: var(--bg);
  border-radius: 6px;
  padding: 0.3rem 0.65rem;
  font-size: 0.82rem;
}
.export.warn {
  border-color: #e6c200;
  background: #fffbe6;
}
.layout {
  flex: 1;
  display: grid;
  min-height: 0;
  height: 100%;
  grid-template-rows: minmax(0, 1fr);
  align-items: stretch;
}
.center-pane {
  min-height: 0;
  padding: 0;
  overflow: hidden;
}
.chat-main {
  padding: 0;
}
.preview-stack {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 0.35rem 0.35rem 0.35rem 0;
}
.preview-stack :deep(.tree),
.preview-stack :deep(.preview) {
  flex: 1;
  min-height: 0;
}
.status {
  display: flex;
  justify-content: space-between;
  padding: 0.35rem 1rem;
  font-size: 0.78rem;
  color: var(--text-muted);
  border-top: 1px solid var(--border);
  background: var(--panel-bg);
  flex-shrink: 0;
}
</style>
