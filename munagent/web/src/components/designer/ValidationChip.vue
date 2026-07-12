<script setup lang="ts">
import { computed, ref } from "vue";
import { injectDesigner } from "../../composables/useDesigner";

const d = injectDesigner();
const open = ref(false);

const errors = computed(() => d.validation.filter((v) => v.level === "error"));
const warnings = computed(() => d.validation.filter((v) => v.level === "warning"));
const ok = computed(() => !errors.value.length);

const emit = defineEmits<{ jump: [path: string] }>();
</script>

<template>
  <div class="chip-wrap">
    <button type="button" class="chip" :class="{ bad: !ok }" @click="open = !open">
      {{ ok ? "✔ 校验通过" : `✘ ${errors.length} 处问题` }}
      <span v-if="warnings.length && ok" class="warn"> · {{ warnings.length }} 警告</span>
    </button>
    <div v-if="open" class="drawer">
      <div class="drawer-head">
        <strong>校验结果</strong>
        <button type="button" @click="open = false">×</button>
      </div>
      <p v-if="!d.validation.length" class="empty">无问题</p>
      <ul>
        <li v-for="(issue, i) in d.validation" :key="i" @click="issue.path && emit('jump', issue.path)">
          <span :class="issue.level">{{ issue.level === "error" ? "✘" : "!" }}</span>
          {{ issue.message }}
          <span v-if="issue.path" class="path">{{ issue.path }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.chip-wrap {
  position: relative;
}
.chip {
  border: 1px solid var(--border);
  background: var(--panel-bg);
  border-radius: 999px;
  padding: 0.25rem 0.65rem;
  font-size: 0.8rem;
  color: #0d7a4a;
}
.chip.bad {
  color: #ba2525;
}
.warn {
  color: #b8860b;
}
.drawer {
  position: absolute;
  top: calc(100% + 0.35rem);
  right: 0;
  width: 320px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgb(0 0 0 / 8%);
  z-index: 20;
  padding: 0.5rem 0;
}
.drawer-head {
  display: flex;
  justify-content: space-between;
  padding: 0.35rem 0.75rem 0.5rem;
  border-bottom: 1px solid var(--border);
}
.drawer-head button {
  border: none;
  background: none;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0.35rem 0;
  max-height: 280px;
  overflow: auto;
}
li {
  padding: 0.45rem 0.75rem;
  font-size: 0.82rem;
  cursor: pointer;
}
li:hover {
  background: var(--hover);
}
.path {
  display: block;
  color: var(--accent);
  font-size: 0.75rem;
  margin-top: 0.15rem;
}
.empty {
  padding: 0.75rem;
  color: var(--text-muted);
  font-size: 0.85rem;
}
</style>
