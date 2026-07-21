<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";

defineProps<{
  x: number;
  y: number;
}>();

const emit = defineEmits<{ rename: []; delete: []; close: [] }>();

function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") emit("close");
}

onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <Teleport to="body">
    <div class="menu-backdrop" @click="emit('close')" @contextmenu.prevent="emit('close')">
      <div
        class="menu"
        role="menu"
        :style="{ left: `${x}px`, top: `${y}px` }"
        @click.stop
      >
        <button type="button" role="menuitem" @click="emit('rename')">修改会话标题</button>
        <button type="button" class="danger" role="menuitem" @click="emit('delete')">删除会话</button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: 900;
}

.menu {
  position: fixed;
  min-width: 148px;
  padding: 0.25rem;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgb(0 0 0 / 12%);
}

.menu button {
  display: block;
  width: 100%;
  padding: 0.45rem 0.65rem;
  border: none;
  background: transparent;
  border-radius: 6px;
  text-align: left;
  font-size: 0.85rem;
}

.menu button:hover {
  background: var(--hover);
}

.menu button.danger {
  color: #ba2525;
}

.menu button.danger:hover {
  background: #fff0f0;
}
</style>
