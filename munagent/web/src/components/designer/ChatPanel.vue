<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { ChatRecord } from "../../types/designer";
import { injectDesigner } from "../../composables/useDesigner";
import { mergeToolCallsForDisplay, recordStableKey } from "../../utils/mergeToolCalls";
import ChatMessage from "./ChatMessage.vue";
import MarkdownBody from "./MarkdownBody.vue";
import TodoPlanBar from "./TodoPlanBar.vue";

const props = defineProps<{
  wide?: boolean;
  showHeader?: boolean;
}>();

const emit = defineEmits<{
  previewFile: [path: string];
  openInEdit: [path: string];
}>();

const d = injectDesigner();
const input = ref("");
const sendError = ref("");
const inputEl = ref<HTMLTextAreaElement | null>(null);
const streamRef = ref<HTMLElement | null>(null);
const focused = ref(false);
/** 用户未主动上滑时, 流式/新消息才自动滚到底 */
const stickToBottom = ref(true);
const SCROLL_STICK_PX = 64;

const displayRecords = computed(() => {
  const merged = mergeToolCallsForDisplay(
    d.records.filter((r) => r.type !== "meta")
  );
  return merged;
});

const chips = computed(() => {
  const empty = d.records.filter((r) => r.type === "user_message").length === 0;
  if (empty) {
    return ["从主题生成整套场景", "帮我设计一个历史危机委员会"];
  }
  return ["检查一致性", "继续完善当前文件"];
});

const emptyGuide =
  "描述你想做的历史场景, Agent 可检索资料、生成与修改场景文件, 并协助一致性检查。";

async function send() {
  const text = input.value.trim();
  if (!text || d.activeTask || d.readonly) return;
  sendError.value = "";
  try {
    await d.sendMessage(text);
    input.value = "";
    resetInputHeight();
    stickToBottom.value = true;
    scrollToBottom(true);
  } catch (e) {
    sendError.value = e instanceof Error ? e.message : "发送失败";
  }
}

function fillChip(text: string) {
  input.value = text;
  nextTick(() => {
    autoResize();
    inputEl.value?.focus();
  });
}

function autoResize() {
  const el = inputEl.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 144)}px`;
}

function resetInputHeight() {
  const el = inputEl.value;
  if (!el) return;
  el.style.height = "auto";
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    void send();
  }
}

const canSend = computed(() => !!input.value.trim() && !d.readonly && !d.activeTask);

function onPreview(path: string) {
  if (d.mode === "chat") {
    d.setPreview(path);
    emit("previewFile", path);
  } else {
    emit("openInEdit", path);
    void d.openFile(path);
  }
}

function isNearBottom(el: HTMLElement) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= SCROLL_STICK_PX;
}

function onStreamScroll() {
  const el = streamRef.value;
  if (!el) return;
  stickToBottom.value = isNearBottom(el);
}

function scrollToBottom(force = false) {
  if (!force && !stickToBottom.value) return;
  nextTick(() => {
    const el = streamRef.value;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  });
}

watch(() => d.records.length, () => scrollToBottom());
watch(() => d.streamingText, () => scrollToBottom());
watch(
  () => d.activeChatId,
  () => {
    stickToBottom.value = true;
    scrollToBottom(true);
  }
);
</script>

<template>
  <div class="chat-panel" :class="{ wide }">
    <header v-if="showHeader !== false" class="head">
      <select :value="d.activeChatId ?? ''" @change="d.selectChat(($event.target as HTMLSelectElement).value)">
        <option v-for="c in d.chats" :key="c.id" :value="c.id">{{ c.title }}</option>
      </select>
      <button type="button" class="link" :disabled="d.readonly" @click="d.newChat()">+ 新对话</button>
    </header>

    <div ref="streamRef" class="stream" @scroll="onStreamScroll">
      <p v-if="!displayRecords.length && !d.streamingText" class="guide">{{ emptyGuide }}</p>
      <template v-for="(rec, idx) in displayRecords" :key="recordStableKey(rec, idx)">
        <ChatMessage
          v-if="rec.type !== 'stream'"
          :record="rec"
          @preview-file="onPreview"
          @revert="d.revertEdit"
        />
      </template>
      <div v-if="d.streamingText" class="bubble agent streaming">
        <MarkdownBody :source="d.streamingText" />
      </div>
    </div>

    <footer class="composer-wrap">
      <TodoPlanBar v-if="d.currentTodo" :todo="d.currentTodo" />
      <div v-if="d.activeTask" class="running">
        Agent 正在工作…
        <button type="button" @click="d.abortTask()">中止</button>
      </div>
      <template v-else>
        <p v-if="sendError" class="send-error">{{ sendError }}</p>
        <div v-if="d.mode === 'edit' && d.contextFile" class="ctx">
          <span class="ctx-tag">{{ d.contextFile }}</span>
          <button type="button" class="x" title="取消附带" @click="d.contextFile = null">×</button>
        </div>
        <div v-if="chips.length" class="chips">
          <button v-for="c in chips" :key="c" type="button" @click="fillChip(c)">{{ c }}</button>
        </div>
        <div class="composer" :class="{ focused, disabled: d.readonly }">
          <textarea
            ref="inputEl"
            v-model="input"
            rows="1"
            placeholder="输入指令…"
            :disabled="d.readonly"
            @input="autoResize"
            @keydown="onKeydown"
            @focus="focused = true"
            @blur="focused = false"
          />
          <button
            type="button"
            class="send"
            title="发送"
            :disabled="!canSend"
            @click="send"
          >
            <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true">
              <path
                fill="currentColor"
                d="M10 3.5a.75.75 0 01.75.75v6.69l2.22-2.22a.75.75 0 111.06 1.06l-3.5 3.5a.75.75 0 01-1.06 0l-3.5-3.5a.75.75 0 111.06-1.06l2.22 2.22V4.25A.75.75 0 0110 3.5z"
              />
            </svg>
          </button>
        </div>
      </template>
    </footer>
  </div>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg);
}
.chat-panel.wide .composer-wrap {
  max-width: 760px;
  margin: 0 auto;
  width: 100%;
}
.head {
  display: flex;
  gap: 0.5rem;
  padding: 0.5rem 0.85rem;
  border-bottom: 1px solid var(--border);
  background: var(--panel-bg);
}
.head select {
  flex: 1;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.35rem 0.55rem;
  background: var(--bg);
  color: var(--text);
  font-size: 0.85rem;
}
.link {
  border: none;
  background: none;
  color: var(--text-muted);
  white-space: nowrap;
  font-size: 0.85rem;
}
.link:hover {
  color: var(--text);
}
.stream {
  flex: 1;
  overflow: auto;
  padding: 1rem 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}
.guide {
  color: var(--text-muted);
  font-size: 0.88rem;
  line-height: 1.6;
  margin: 2rem auto 1rem;
  max-width: 420px;
  text-align: center;
}
.bubble.streaming {
  opacity: 0.85;
}
.running {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85rem;
  color: var(--text-muted);
  padding: 0.55rem 0.65rem;
  margin-bottom: 0.45rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel-bg);
}
.running button {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.25rem 0.6rem;
  background: var(--bg);
  font-size: 0.8rem;
}
.composer-wrap {
  flex-shrink: 0;
  padding: 0.5rem 0.85rem 0.85rem;
  background: var(--bg);
}
.send-error {
  margin: 0 0 0.45rem;
  font-size: 0.82rem;
  color: #b42318;
  line-height: 1.4;
}
.ctx {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  margin-bottom: 0.4rem;
}
.ctx-tag {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.72rem;
  color: var(--text-muted);
  background: var(--chip-bg);
  border-radius: 6px;
  padding: 0.18rem 0.45rem;
  max-width: calc(100% - 1.5rem);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.x {
  border: none;
  background: none;
  color: var(--text-muted);
  font-size: 0.95rem;
  line-height: 1;
  padding: 0 0.2rem;
  opacity: 0.6;
}
.x:hover {
  opacity: 1;
  color: var(--text);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-bottom: 0.45rem;
}
.chips button {
  font-size: 0.75rem;
  padding: 0.28rem 0.6rem;
  border: none;
  border-radius: 6px;
  background: var(--chip-bg);
  color: var(--text-muted);
  transition: background 0.12s, color 0.12s;
}
.chips button:hover {
  background: #e2e2de;
  color: var(--text);
}
.composer {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  border: 1px solid var(--composer-border);
  border-radius: 10px;
  background: var(--composer-bg);
  padding: 0.45rem 0.45rem 0.45rem 0.7rem;
  box-shadow: 0 1px 2px rgb(0 0 0 / 4%);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.composer.focused {
  border-color: #c4c4c0;
  box-shadow: 0 1px 4px rgb(0 0 0 / 6%);
}
.composer.disabled {
  opacity: 0.55;
}
.composer textarea {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font-size: 0.88rem;
  line-height: 1.45;
  min-height: 1.45em;
  max-height: 8.5em;
  overflow-y: auto;
  padding: 0.15rem 0;
  color: var(--text);
}
.composer textarea::placeholder {
  color: #9b9b94;
}
.send {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 50%;
  background: var(--text);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.12s, opacity 0.12s;
}
.send:hover:not(:disabled) {
  background: #000;
}
.send:disabled {
  background: #ecece8;
  color: #b8b8b2;
  cursor: default;
}
</style>
