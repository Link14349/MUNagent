<script setup lang="ts">
import { onUnmounted, watch } from "vue";

const props = withDefaults(
  defineProps<{
    open: boolean;
    title?: string;
    width?: string;
    dismissOnBackdrop?: boolean;
  }>(),
  {
    width: "min(420px, 92vw)",
    dismissOnBackdrop: true,
  }
);

const emit = defineEmits<{ close: [] }>();

function onBackdrop() {
  if (props.dismissOnBackdrop) emit("close");
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && props.open) emit("close");
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      window.addEventListener("keydown", onKeydown);
    } else {
      window.removeEventListener("keydown", onKeydown);
    }
  },
  { immediate: true }
);

onUnmounted(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="open" class="modal-backdrop" @click.self="onBackdrop">
        <div
          class="modal-dialog"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          :style="{ width }"
          @click.stop
        >
          <header v-if="title || $slots.header" class="modal-header">
            <slot name="header">
              <h2>{{ title }}</h2>
            </slot>
            <button type="button" class="modal-close" aria-label="关闭" @click="emit('close')">×</button>
          </header>
          <div class="modal-body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="modal-footer">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: rgb(0 0 0 / 32%);
  backdrop-filter: blur(2px);
}

.modal-dialog {
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 16px 48px rgb(0 0 0 / 12%);
  display: flex;
  flex-direction: column;
  max-height: min(88vh, 640px);
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1.15rem 0.65rem;
  border-bottom: 1px solid var(--border);
}

.modal-header h2 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
}

.modal-close {
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 1.35rem;
  line-height: 1;
  padding: 0.15rem 0.35rem;
  border-radius: 6px;
}

.modal-close:hover {
  background: var(--hover);
  color: var(--text);
}

.modal-body {
  padding: 1rem 1.15rem;
  overflow: auto;
  display: grid;
  gap: 0.85rem;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 0.75rem 1.15rem 1rem;
  border-top: 1px solid var(--border);
  background: var(--bg);
}

.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.16s ease;
}

.modal-fade-enter-active .modal-dialog,
.modal-fade-leave-active .modal-dialog {
  transition: transform 0.16s ease, opacity 0.16s ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}

.modal-fade-enter-from .modal-dialog,
.modal-fade-leave-to .modal-dialog {
  opacity: 0;
  transform: translateY(8px) scale(0.98);
}
</style>
