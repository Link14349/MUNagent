<script setup lang="ts">
defineProps<{
  side: "left" | "right";
  collapsed: boolean;
  icon: string;
  label: string;
}>();

const emit = defineEmits<{ "update:collapsed": [boolean] }>();
</script>

<template>
  <aside :class="['designer-sidebar', side, { collapsed }]">
    <template v-if="!collapsed">
      <button
        v-if="side === 'right'"
        type="button"
        class="edge-toggle"
        :title="`折叠${label}`"
        @click="emit('update:collapsed', true)"
      >
        ▶
      </button>
      <div class="sidebar-body">
        <slot />
      </div>
      <button
        v-if="side === 'left'"
        type="button"
        class="edge-toggle"
        :title="`折叠${label}`"
        @click="emit('update:collapsed', true)"
      >
        ◀
      </button>
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
  border-right: 1px solid var(--border);
}
.designer-sidebar.right {
  border-left: 1px solid var(--border);
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
.edge-toggle {
  flex-shrink: 0;
  width: 22px;
  align-self: stretch;
  border: none;
  background: var(--panel-bg);
  color: var(--text-muted);
  cursor: pointer;
  padding: 0;
  font-size: 0.65rem;
  display: flex;
  align-items: center;
  justify-content: center;
}
.designer-sidebar.left .edge-toggle {
  border-left: 1px solid var(--border);
}
.designer-sidebar.right .edge-toggle {
  border-right: 1px solid var(--border);
}
.edge-toggle:hover {
  background: var(--hover);
  color: var(--text);
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
.collapsed-rail:hover {
  background: var(--hover);
  color: var(--accent);
}
.rail-icon {
  font-size: 1.15rem;
  line-height: 1;
}
</style>
