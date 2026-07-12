<script setup lang="ts">
import { computed, ref } from "vue";
import { parseTodoText, todoProgress } from "../../utils/todo";

const props = defineProps<{ todo: string }>();

const expanded = ref(false);

const items = computed(() => parseTodoText(props.todo));
const progress = computed(() => todoProgress(items.value));
</script>

<template>
  <div class="todo-plan" :class="{ expanded }">
    <button type="button" class="todo-toggle" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="todo-label">当前计划</span>
      <span class="todo-progress">{{ progress.done }}/{{ progress.total }}</span>
      <svg class="chevron" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
        <path
          fill="currentColor"
          d="M4.47 6.47a.75.75 0 011.06 0L8 8.94l2.47-2.47a.75.75 0 111.06 1.06l-3 3a.75.75 0 01-1.06 0l-3-3a.75.75 0 010-1.06z"
        />
      </svg>
    </button>
    <div v-show="expanded" class="todo-body">
      <ul class="todo-list">
        <li v-for="(item, i) in items" :key="i" class="todo-item" :class="{ done: item.done }">
          <span class="checkbox" aria-hidden="true">
            <svg v-if="item.done" viewBox="0 0 16 16" width="12" height="12">
              <path
                fill="currentColor"
                d="M12.207 4.793a1 1 0 010 1.414l-5 5a1 1 0 01-1.414 0l-2.5-2.5a1 1 0 011.414-1.414L6.5 9.086l4.293-4.293a1 1 0 011.414 0z"
              />
            </svg>
          </span>
          <span class="text">{{ item.text }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.todo-plan {
  margin-bottom: 0.45rem;
  border: 1px solid #e4e4e0;
  border-radius: 10px;
  background: #f3f3f0;
  overflow: hidden;
  transition: border-color 0.15s;
}
.todo-plan.expanded {
  border-color: #d8d8d4;
}
.todo-toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  border: none;
  background: transparent;
  padding: 0.42rem 0.65rem;
  font-size: 0.78rem;
  color: var(--text-muted);
  cursor: pointer;
  text-align: left;
  transition: background 0.12s;
}
.todo-toggle:hover {
  background: rgb(0 0 0 / 3%);
}
.todo-label {
  font-weight: 500;
  color: #6b6b66;
}
.todo-progress {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  color: #8a8a84;
}
.chevron {
  flex-shrink: 0;
  color: #9a9a94;
  transition: transform 0.18s ease;
}
.expanded .chevron {
  transform: rotate(180deg);
}
.todo-body {
  border-top: 1px solid #e8e8e4;
  padding: 0.35rem 0.65rem 0.5rem;
}
.todo-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
}
.todo-item {
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  font-size: 0.8rem;
  line-height: 1.45;
  color: var(--text);
}
.todo-item.done .text {
  color: var(--text-muted);
  text-decoration: line-through;
  text-decoration-color: #b8b8b2;
}
.checkbox {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  margin-top: 0.15rem;
  border: 1.5px solid #c4c4be;
  border-radius: 3px;
  background: #fafaf8;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #5a5a54;
}
.todo-item.done .checkbox {
  background: #e8e8e4;
  border-color: #b8b8b2;
}
.text {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}
</style>
