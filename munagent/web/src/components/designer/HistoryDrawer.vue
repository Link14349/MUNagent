<script setup lang="ts">
import { ref, watch } from "vue";
import { designerApi } from "../../api/designerApi";
import { parseUnifiedDiff } from "../../utils/diff";
import { injectDesigner } from "../../composables/useDesigner";
import type { HistoryDiffEntry } from "../../types/designer";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const d = injectDesigner();
const note = ref("");
const view = ref<"list" | "diff">("list");
const diffEntries = ref<HistoryDiffEntry[]>([]);
const diffSnapId = ref("");
const expanded = ref<string | null>(null);

watch(
  () => props.open,
  (v) => {
    if (v) {
      d.loadHistory();
      view.value = "list";
    }
  }
);

function relTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3600000);
  if (h < 24) return h < 1 ? "今天" : `今天`;
  return "昨天";
}

function kindLabel(kind: string) {
  if (kind === "manual") return "手动";
  if (kind === "restore_backup") return "恢复备份";
  return "自动";
}

async function showDiff(snapId: string) {
  diffSnapId.value = snapId;
  diffEntries.value = await designerApi.historyDiff(d.scenarioId, snapId);
  view.value = "diff";
}

async function saveVersion() {
  await d.saveSnapshot(note.value || undefined);
  note.value = "";
}

async function restore(snapId: string) {
  if (d.activeTask) {
    alert("请先中止正在运行的 Agent 任务");
    return;
  }
  if (!confirm("当前状态会先自动备份; 该版本之后的改动将被覆盖。确认恢复?")) return;
  try {
    await d.restoreHistory(snapId);
    emit("close");
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e));
  }
}

async function removeSnapshot(snapId: string) {
  if (!confirm("确认删除该手动版本?")) return;
  await designerApi.deleteSnapshot(d.scenarioId, snapId);
  await d.loadHistory();
}
</script>

<template>
  <div v-if="open" class="overlay" @click.self="emit('close')">
    <aside class="drawer">
      <header>
        <h3>{{ view === "list" ? "历史版本" : "版本对比" }}</h3>
        <button type="button" @click="view === 'list' ? emit('close') : (view = 'list')">
          {{ view === "list" ? "×" : "← 返回" }}
        </button>
      </header>

      <template v-if="view === 'list'">
        <div class="save-row">
          <input v-model="note" placeholder="备注(可选)" />
          <button type="button" @click="saveVersion">保存版本</button>
        </div>
        <ul class="snap-list">
          <li v-for="s in d.history" :key="s.id">
            <div class="row">
              <span class="dot">○</span>
              <div class="info">
                <div>{{ relTime(s.created_at) }} {{ s.created_at.slice(11, 16) }}</div>
                <div class="sub">{{ kindLabel(s.kind) }} · {{ s.reason }}</div>
              </div>
            </div>
            <div class="actions">
              <button type="button" @click="showDiff(s.id)">对比</button>
              <button type="button" :disabled="d.activeTask" @click="restore(s.id)">恢复</button>
              <button v-if="s.kind === 'manual'" type="button" @click="removeSnapshot(s.id)">删除</button>
            </div>
          </li>
          <li v-if="!d.history.length" class="empty">暂无历史版本</li>
        </ul>
      </template>

      <template v-else>
        <ul class="diff-list">
          <li v-for="e in diffEntries" :key="e.path">
            <div class="file-head" @click="expanded = expanded === e.path ? null : e.path">
              {{ e.status }} {{ e.path }} (+{{ e.additions }}/-{{ e.deletions }})
            </div>
            <div v-if="expanded === e.path && e.diff" class="diff-body">
              <div
                v-for="(line, i) in parseUnifiedDiff(e.diff)"
                :key="i"
                :class="['line', line.kind]"
              >
                {{ line.text }}
              </div>
            </div>
          </li>
        </ul>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgb(0 0 0 / 20%);
  z-index: 50;
}
.drawer {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: min(420px, 100vw);
  background: var(--bg);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.85rem 1rem;
  border-bottom: 1px solid var(--border);
}
header h3 {
  margin: 0;
  font-size: 1rem;
}
header button {
  border: none;
  background: none;
  font-size: 1.1rem;
}
.save-row {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
}
.save-row input {
  flex: 1;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.35rem 0.5rem;
}
.save-row button {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.35rem 0.65rem;
  background: var(--panel-bg);
}
.snap-list,
.diff-list {
  list-style: none;
  margin: 0;
  padding: 0.5rem 0;
  overflow: auto;
  flex: 1;
}
.snap-list li {
  padding: 0.65rem 1rem;
  border-bottom: 1px solid var(--border);
}
.row {
  display: flex;
  gap: 0.5rem;
}
.sub {
  font-size: 0.78rem;
  color: var(--text-muted);
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.35rem;
}
.actions button {
  font-size: 0.75rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  padding: 0.15rem 0.45rem;
}
.empty {
  padding: 1rem;
  color: var(--text-muted);
  text-align: center;
}
.file-head {
  padding: 0.5rem 1rem;
  cursor: pointer;
  font-size: 0.85rem;
}
.file-head:hover {
  background: var(--hover);
}
.diff-body {
  font-family: ui-monospace, monospace;
  font-size: 0.75rem;
  padding: 0 1rem 0.5rem;
  max-height: 200px;
  overflow: auto;
}
.line.add {
  background: #e6ffed;
}
.line.del {
  background: #ffebe9;
}
</style>
