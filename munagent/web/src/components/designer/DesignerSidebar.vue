<script setup lang="ts">
import { ref } from "vue";
import { SIDEBAR_LIMITS } from "../../composables/useSidebarWidths";

const props = defineProps<{
  side: "left" | "right";
  collapsed: boolean;
  icon: string;
  label: string;
  width: number;
  defaultWidth: number;
}>();

const emit = defineEmits<{
  "update:collapsed": [boolean];
  "update:width": [number];
  "reset-width": [];
}>();

const resizing = ref(false);

function clampWidth(w: number) {
  const { min, max } = SIDEBAR_LIMITS[props.side];
  return Math.min(max, Math.max(min, w));
}

function onResizePointerDown(e: PointerEvent) {
  if (props.collapsed) return;
  e.preventDefault();
  const handle = e.currentTarget as HTMLElement;
  handle.setPointerCapture(e.pointerId);
  resizing.value = true;

  const startX = e.clientX;
  const startW = props.width;
  document.body.style.cursor = "col-resize";
  document.body.style.userSelect = "none";

  const onMove = (ev: PointerEvent) => {
    const delta = ev.clientX - startX;
    const next = props.side === "left" ? startW + delta : startW - delta;
    emit("update:width", clampWidth(next));
  };

  const onUp = () => {
    resizing.value = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onUp);
  };

  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  window.addEventListener("pointercancel", onUp);
}

function onResizeDblClick() {
  if (props.collapsed) return;
  emit("reset-width");
}
</script>

<template>
  <aside :class="['designer-sidebar', side, { collapsed, resizing }]">
    <template v-if="!collapsed">
      <div class="sidebar-body">
        <slot />
      </div>
      <div class="sidebar-edge">
        <button
          type="button"
          class="edge-toggle"
          :title="`折叠${label}`"
          @click="emit('update:collapsed', true)"
        >
          {{ side === "left" ? "◀" : "▶" }}
        </button>
        <div
          class="resize-handle"
          role="separator"
          aria-orientation="vertical"
          :aria-label="`调整${label}宽度`"
          :title="`拖动调整宽度, 双击恢复默认 (${defaultWidth}px)`"
          @pointerdown="onResizePointerDown"
          @dblclick="onResizeDblClick"
        />
      </div>
    </template>
    <button
      v-else
      type="button"
      class="collapsed-rail"
      :title="`展开${label}`"
      @click="emit('update:collapsed', false)"
    >
      <span class="rail-icon">{{ icon }}</span>
    </button>
  </aside>
</template>

<style scoped>
.designer-sidebar {
  display: flex;
  height: 100%;
  min-height: 0;
  align-self: stretch;
  overflow: hidden;
  background: var(--panel-bg);
}
.designer-sidebar.left {
  border-right: none;
}
.designer-sidebar.right {
  border-left: none;
}
.sidebar-body {
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.sidebar-edge {
  display: flex;
  flex-shrink: 0;
  align-self: stretch;
  background: var(--panel-bg);
}
.designer-sidebar.left .sidebar-edge {
  border-left: 1px solid var(--border);
}
.designer-sidebar.right .sidebar-edge {
  border-right: 1px solid var(--border);
  order: -1;
}
.edge-toggle {
  flex-shrink: 0;
  width: 12px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0;
  font-size: 0.55rem;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.edge-toggle:hover {
  background: var(--hover);
  color: var(--text);
}
.resize-handle {
  flex-shrink: 0;
  width: 3px;
  align-self: stretch;
  cursor: col-resize;
  touch-action: none;
  position: relative;
}
.resize-handle::after {
  content: "";
  position: absolute;
  inset: 0 -2px;
}
.resize-handle:hover,
.designer-sidebar.resizing .resize-handle {
  background: var(--accent);
  opacity: 0.35;
}
.collapsed-rail {
  width: 100%;
  height: 100%;
  border: none;
  background: var(--panel-bg);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 0.85rem;
  color: var(--text-muted);
}
.designer-sidebar.left.collapsed {
  border-right: 1px solid var(--border);
}
.designer-sidebar.right.collapsed {
  border-left: 1px solid var(--border);
}
.collapsed-rail:hover {
  background: var(--hover);
  color: var(--accent);
}
.rail-icon {
  font-size: 1.15rem;
  line-height: 1;
}
</style>
