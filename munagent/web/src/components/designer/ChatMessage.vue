<script setup lang="ts">
import { computed, ref } from "vue";
import type { ChatRecord } from "../../types/designer";
import { diffLineStats, parseUnifiedDiff } from "../../utils/diff";
import { formatToolArgs } from "../../utils/formatToolArgs";
import { injectDesigner } from "../../composables/useDesigner";
import MarkdownBody from "./MarkdownBody.vue";

const props = defineProps<{ record: ChatRecord; expandedTools?: boolean }>();

const emit = defineEmits<{
  previewFile: [path: string];
  revert: [seq: number];
}>();

const d = injectDesigner();
const showDiff = ref(false);
const showTool = ref(false);

const isTool = computed(() => props.record.type === "tool_call");
const isEdit = computed(() => props.record.type === "file_edit");

const editStats = computed(() => {
  if (props.record.type !== "file_edit") return null;
  return diffLineStats(props.record.diff);
});

const diffLines = computed(() => {
  if (props.record.type !== "file_edit") return [];
  return parseUnifiedDiff(props.record.diff);
});

const toolArgsDisplay = computed(() => {
  if (props.record.type !== "tool_call") return "";
  return formatToolArgs(props.record);
});

</script>

<template>
  <div v-if="record.type === 'user_message'" class="bubble user">{{ record.text }}</div>

  <div v-else-if="record.type === 'agent_text'" class="bubble agent">
    <MarkdownBody :source="record.text" />
  </div>

  <div
    v-else-if="isTool && record.type === 'tool_call'"
    class="tool-card"
    :class="record.status"
    @click="showTool = !showTool"
  >
    <span class="tool-icon" :class="record.status" aria-hidden="true">
      <span v-if="record.status === 'running'" class="spinner" />
      <span v-else-if="record.status === 'error'">✗</span>
      <span v-else>✓</span>
    </span>
    <span class="name">{{ record.tool }}</span>
    <span class="args">{{ toolArgsDisplay }}</span>
    <pre v-if="showTool && record.result_summary" class="result">{{ record.result_summary }}</pre>
  </div>

  <div v-else-if="isEdit && record.type === 'file_edit'" class="edit-card">
    <div class="head" @click="showDiff = !showDiff">
      ✎ {{ record.path }}
      <span v-if="editStats" class="badge">+{{ editStats.additions }}/-{{ editStats.deletions }}</span>
    </div>
    <div v-if="showDiff" class="diff">
      <div v-for="(line, i) in diffLines" :key="i" :class="['line', line.kind]">{{ line.text }}</div>
    </div>
    <div class="actions">
      <button type="button" @click="emit('previewFile', record.path)">查看文件</button>
      <button type="button" :disabled="d.readonly" @click="emit('revert', record.seq)">撤销</button>
    </div>
  </div>

  <div v-else-if="record.type === 'system'" class="system">{{ record.text }}</div>

  <div v-else-if="record.type === 'usage'" class="usage">
    本轮 {{ (record.input_tokens / 1000).toFixed(1) }}k→{{ (record.output_tokens / 1000).toFixed(1) }}k tokens
    · {{ record.tool_calls }} 次工具
  </div>
</template>

<style scoped>
.bubble {
  max-width: 92%;
  padding: 0.65rem 0.85rem;
  border-radius: 10px;
  font-size: 0.9rem;
  line-height: 1.5;
}
.user {
  margin-left: auto;
  background: var(--accent-soft);
  color: var(--text);
  white-space: pre-wrap;
}
.agent {
  background: var(--panel-bg);
  border: 1px solid var(--border);
}
.tool-card,
.edit-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.5rem 0.65rem;
  font-size: 0.82rem;
  background: var(--panel-bg);
  cursor: pointer;
}
.tool-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.15rem 0.35rem;
}
.tool-card.running {
  opacity: 0.92;
}
.tool-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  flex-shrink: 0;
  transition: color 0.15s ease;
}
.tool-icon.ok {
  color: #055d20;
}
.tool-icon.error {
  color: #9a031e;
}
.spinner {
  width: 0.72rem;
  height: 0.72rem;
  border: 2px solid var(--border);
  border-top-color: var(--accent, #666);
  border-radius: 50%;
  animation: tool-spin 0.7s linear infinite;
}
@keyframes tool-spin {
  to {
    transform: rotate(360deg);
  }
}
.tool-card .name {
  font-weight: 600;
  margin: 0 0.35rem;
  flex-shrink: 0;
}
.args {
  color: var(--text-muted);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.result {
  margin: 0.35rem 0 0;
  font-size: 0.75rem;
  color: var(--text-muted);
}
.edit-card .head {
  font-weight: 600;
}
.badge {
  margin-left: 0.35rem;
  font-size: 0.75rem;
  color: var(--accent);
}
.diff {
  margin-top: 0.35rem;
  font-family: ui-monospace, monospace;
  font-size: 0.75rem;
  max-height: 200px;
  overflow: auto;
}
.line.add {
  background: #e6ffed;
  color: #055d20;
}
.line.del {
  background: #ffebe9;
  color: #9a031e;
}
.line.hunk {
  color: var(--text-muted);
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.35rem;
}
.actions button {
  font-size: 0.75rem;
  padding: 0.2rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
}
.system {
  text-align: center;
  color: var(--text-muted);
  font-size: 0.8rem;
  padding: 0.25rem;
}
.usage {
  text-align: right;
  font-size: 0.75rem;
  color: var(--text-muted);
  padding: 0.15rem 0;
}
</style>
