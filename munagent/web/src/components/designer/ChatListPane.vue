<script setup lang="ts">
import { ref } from "vue";
import type { ChatMeta } from "../../types/designer";
import { injectDesigner } from "../../composables/useDesigner";
import ChatContextMenu from "./ChatContextMenu.vue";
import RenameChatDialog from "./RenameChatDialog.vue";
import DeleteChatDialog from "./DeleteChatDialog.vue";

const d = injectDesigner();

const menu = ref<{ x: number; y: number; chat: ChatMeta } | null>(null);
const renameTarget = ref<ChatMeta | null>(null);
const deleteTarget = ref<ChatMeta | null>(null);

function relTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

function openMenu(e: MouseEvent, chat: ChatMeta) {
  if (d.readonly) return;
  menu.value = { x: e.clientX, y: e.clientY, chat };
}

function closeMenu() {
  menu.value = null;
}

function openRename() {
  if (!menu.value) return;
  renameTarget.value = menu.value.chat;
  closeMenu();
}

function openDelete() {
  if (!menu.value) return;
  deleteTarget.value = menu.value.chat;
  closeMenu();
}
</script>

<template>
  <div class="list-pane">
    <div class="head">
      <span>对话</span>
      <button type="button" class="link" :disabled="d.readonly" @click="d.newChat()">+ 新对话</button>
    </div>
    <ul>
      <li
        v-for="c in d.chats"
        :key="c.id"
        :class="{ active: c.id === d.activeChatId }"
        @click="d.selectChat(c.id)"
        @contextmenu.prevent="openMenu($event, c)"
      >
        <div class="title">{{ c.title }}</div>
        <div class="meta">{{ relTime(c.updated_at) }} · {{ c.turns }} 轮</div>
      </li>
    </ul>

    <ChatContextMenu
      v-if="menu"
      :x="menu.x"
      :y="menu.y"
      @close="closeMenu"
      @rename="openRename"
      @delete="openDelete"
    />

    <RenameChatDialog
      v-if="renameTarget"
      :open="!!renameTarget"
      :chat-id="renameTarget.id"
      :initial-title="renameTarget.title"
      @close="renameTarget = null"
    />

    <DeleteChatDialog
      v-if="deleteTarget"
      :open="!!deleteTarget"
      :chat-id="deleteTarget.id"
      :chat-title="deleteTarget.title"
      @close="deleteTarget = null"
    />
  </div>
</template>

<style scoped>
.list-pane {
  height: 100%;
  min-height: 0;
  background: var(--panel-bg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.head {
  display: flex;
  justify-content: space-between;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--border);
  font-weight: 600;
  color: var(--text-muted);
}
.link {
  border: none;
  background: none;
  color: var(--accent);
  font-size: 0.8rem;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0.35rem 0;
  overflow: auto;
  flex: 1;
}
li {
  padding: 0.55rem 0.85rem;
  cursor: pointer;
  border-left: 3px solid transparent;
}
li:hover {
  background: var(--hover);
}
li.active {
  background: var(--accent-soft);
  border-left-color: var(--accent);
}
.title {
  font-size: 0.88rem;
  font-weight: 500;
}
.meta {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: 0.15rem;
}
</style>
