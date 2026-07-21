import { ref, shallowRef, type InjectionKey, inject, provide } from "vue";
import type {
  ChatMeta,
  ChatRecord,
  DesignerEvent,
  DesignerMode,
  FileNode,
  HistorySnapshot,
  ValidationIssue,
} from "../types/designer";
import { designerApi } from "../api/designerApi";
import { eventsAfterSeq } from "../utils/sseSeq";
import { mergeToolCallsForDisplay } from "../utils/mergeToolCalls";

export interface OpenFileTab {
  path: string;
  content: string;
  savedContent: string;
  dirty: boolean;
  agentConflict?: string;
}

export interface DesignerStore {
  scenarioId: string;
  title: string;
  readonly: boolean;
  mode: DesignerMode;
  chats: ChatMeta[];
  activeChatId: string | null;
  records: ChatRecord[];
  currentTodo: string | null;
  streamingText: string;
  activeTask: boolean;
  fileTree: FileNode[];
  openFiles: OpenFileTab[];
  activeFilePath: string | null;
  previewPath: string | null;
  contextFile: string | null;
  composerDraft: string;
  validation: ValidationIssue[];
  history: HistorySnapshot[];
  totalTokens: number;
  init: () => Promise<void>;
  setMode: (m: DesignerMode) => void;
  selectChat: (id: string) => Promise<void>;
  newChat: (title?: string) => Promise<void>;
  sendMessage: (text: string) => Promise<void>;
  abortTask: () => void;
  openFile: (path: string) => Promise<void>;
  saveFile: (path: string) => Promise<void>;
  closeTab: (path: string) => void;
  setPreview: (path: string | null) => void;
  refreshFiles: () => Promise<void>;
  deleteFile: (path: string) => Promise<void>;
  revertEdit: (seq: number) => Promise<void>;
  loadHistory: () => Promise<void>;
  saveSnapshot: (note?: string) => Promise<void>;
  restoreHistory: (snapId: string) => Promise<void>;
  renameChat: (id: string, title: string) => Promise<void>;
  deleteChat: (id: string) => Promise<void>;
  duplicateScenario: (newId: string, newTitle: string) => Promise<string>;
}

const KEY: InjectionKey<DesignerStore> = Symbol("designer");

const instances = new Map<string, DesignerStore>();

export function useDesigner(scenarioId: string): DesignerStore {
  const existing = instances.get(scenarioId);
  if (existing) return existing;

  const mode = ref<DesignerMode>(
    (localStorage.getItem(`designer-mode-${scenarioId}`) as DesignerMode) || "chat"
  );
  const title = ref("");
  const readonly = ref(false);
  const chats = ref<ChatMeta[]>([]);
  const activeChatId = ref<string | null>(null);
  const records = ref<ChatRecord[]>([]);
  const currentTodo = ref<string | null>(null);
  const streamingText = ref("");
  const activeTask = ref(false);
  const fileTree = shallowRef<FileNode[]>([]);
  const openFiles = ref<OpenFileTab[]>([]);
  const activeFilePath = ref<string | null>(null);
  const previewPath = ref<string | null>(null);
  const contextFile = ref<string | null>(null);
  const composerDraft = ref("");
  const validation = ref<ValidationIssue[]>([]);
  const history = ref<HistorySnapshot[]>([]);
  const totalTokens = ref(0);
  let lastSseSeq: number | null = null;
  let unsub: (() => void) | null = null;

  const store: DesignerStore = {
    get scenarioId() {
      return scenarioId;
    },
    get title() {
      return title.value;
    },
    get readonly() {
      return readonly.value;
    },
    get mode() {
      return mode.value;
    },
    get chats() {
      return chats.value;
    },
    get activeChatId() {
      return activeChatId.value;
    },
    get records() {
      return records.value;
    },
    get currentTodo() {
      return currentTodo.value;
    },
    get streamingText() {
      return streamingText.value;
    },
    get activeTask() {
      return activeTask.value;
    },
    get fileTree() {
      return fileTree.value;
    },
    get openFiles() {
      return openFiles.value;
    },
    get activeFilePath() {
      return activeFilePath.value;
    },
    get previewPath() {
      return previewPath.value;
    },
    get contextFile() {
      return contextFile.value;
    },
    set contextFile(v: string | null) {
      contextFile.value = v;
    },
    get composerDraft() {
      return composerDraft.value;
    },
    set composerDraft(v: string) {
      composerDraft.value = v;
    },
    get validation() {
      return validation.value;
    },
    get history() {
      return history.value;
    },
    get totalTokens() {
      return totalTokens.value;
    },

    async init() {
      const state = await designerApi.getDesign(scenarioId);
      title.value = state.title;
      readonly.value = state.readonly;
      chats.value = state.chats;
      validation.value = state.validation;
      fileTree.value = state.fileTree;
      activeTask.value = !!state.active_task;

      if (!chats.value.length) {
        const c = await designerApi.createChat(scenarioId, "初始场景生成");
        chats.value = [c];
      }
      const chatId =
        new URLSearchParams(location.search).get("chat") || chats.value[0]?.id;
      if (chatId) await store.selectChat(chatId);

      const fileQ = new URLSearchParams(location.search).get("file");
      if (fileQ) await store.openFile(fileQ);

      unsub?.();
      unsub = designerApi.subscribeEvents(scenarioId, (ev) => {
        handleEvent(ev);
      });
    },

    setMode(m) {
      mode.value = m;
      localStorage.setItem(`designer-mode-${scenarioId}`, m);
    },

    async selectChat(id) {
      activeChatId.value = id;
      const detail = await designerApi.getChat(scenarioId, id);
      records.value = mergeToolCallsForDisplay(detail.records);
      currentTodo.value = detail.todo;
      streamingText.value = "";
    },

    async newChat(t) {
      const c = await designerApi.createChat(scenarioId, t);
      chats.value = [c, ...chats.value.filter((x) => x.id !== c.id)];
      await store.selectChat(c.id);
    },

    async sendMessage(text) {
      if (!activeChatId.value) {
        throw new Error("对话尚未就绪, 请刷新页面后重试");
      }
      if (activeTask.value) return;
      activeTask.value = true;
      streamingText.value = "";
      try {
        await designerApi.sendMessage(
          scenarioId,
          activeChatId.value,
          text,
          contextFile.value ?? undefined
        );
      } catch (e) {
        activeTask.value = false;
        throw e;
      }
    },

    abortTask() {
      designerApi.abort(scenarioId);
    },

    async openFile(path) {
      const { content } = await designerApi.getFile(scenarioId, path);
      let tab = openFiles.value.find((t) => t.path === path);
      if (!tab) {
        tab = { path, content, savedContent: content, dirty: false };
        openFiles.value.push(tab);
      } else if (!tab.dirty) {
        tab.content = content;
        tab.savedContent = content;
        tab.agentConflict = undefined;
      } else if (content !== tab.savedContent) {
        tab.agentConflict = content;
      }
      activeFilePath.value = path;
      contextFile.value = path;
    },

    async saveFile(path) {
      const tab = openFiles.value.find((t) => t.path === path);
      if (!tab) return;
      validation.value = await designerApi.putFile(scenarioId, path, tab.content);
      tab.savedContent = tab.content;
      tab.dirty = false;
      await store.refreshFiles();
    },

    closeTab(path) {
      openFiles.value = openFiles.value.filter((t) => t.path !== path);
      if (activeFilePath.value === path) {
        activeFilePath.value = openFiles.value[0]?.path ?? null;
      }
    },

    setPreview(path) {
      previewPath.value = path;
    },

    async refreshFiles() {
      const state = await designerApi.getDesign(scenarioId);
      fileTree.value = state.fileTree;
      validation.value = state.validation;
      for (const tab of openFiles.value) {
        try {
          const { content } = await designerApi.getFile(scenarioId, tab.path);
          if (!tab.dirty) {
            tab.content = content;
            tab.savedContent = content;
          } else if (content !== tab.savedContent) {
            tab.agentConflict = content;
          }
        } catch {
          /* file removed */
        }
      }
    },

    async deleteFile(path) {
      validation.value = await designerApi.deleteFile(scenarioId, path);
      store.closeTab(path);
      if (contextFile.value === path) {
        contextFile.value = activeFilePath.value;
      }
      if (previewPath.value === path) {
        previewPath.value = null;
      }
      await store.refreshFiles();
    },

    async revertEdit(seq) {
      if (!activeChatId.value) return;
      await designerApi.revert(scenarioId, activeChatId.value, seq);
      const detail = await designerApi.getChat(scenarioId, activeChatId.value);
      records.value = detail.records;
      currentTodo.value = detail.todo;
      await store.refreshFiles();
    },

    loadHistory() {
      return designerApi.listHistory(scenarioId).then((items) => {
        history.value = items;
      });
    },

    async saveSnapshot(note) {
      const s = await designerApi.createSnapshot(scenarioId, note);
      history.value = [s, ...history.value];
    },

    async restoreHistory(snapId) {
      validation.value = (await designerApi.restoreHistory(scenarioId, snapId)).validation;
      await store.refreshFiles();
      for (const tab of openFiles.value) {
        tab.dirty = false;
        tab.agentConflict = undefined;
      }
      history.value = await designerApi.listHistory(scenarioId);
    },

    async renameChat(id, title) {
      await designerApi.patchChat(scenarioId, id, title);
      const state = await designerApi.getDesign(scenarioId);
      chats.value = state.chats;
    },

    async deleteChat(id) {
      await designerApi.deleteChat(scenarioId, id);
      chats.value = chats.value.filter((c) => c.id !== id);
      if (activeChatId.value !== id) return;
      const next = chats.value[0];
      if (next) {
        await store.selectChat(next.id);
      } else {
        await store.newChat();
      }
    },

    async duplicateScenario(newId, newTitle) {
      return designerApi.duplicate(scenarioId, newId, newTitle);
    },
  };

  function handleEvent(ev: DesignerEvent) {
    const pending = eventsAfterSeq([ev], lastSseSeq);
    if (!pending.length) return;
    lastSseSeq = ev.seq;

    if (ev.type === "text_delta" && ev.chat_id === activeChatId.value) {
      streamingText.value += ev.delta;
    }
    if (ev.type === "record_appended" && ev.chat_id === activeChatId.value) {
      const next =
        ev.record.type === "tool_call"
          ? mergeToolCallsForDisplay([...records.value, ev.record])
          : [...records.value, ev.record];
      records.value = next;
      if (ev.record.type === "agent_text") streamingText.value = "";
      if (ev.record.type === "todo" && "text" in ev.record && typeof ev.record.text === "string") {
        currentTodo.value = ev.record.text;
      }
      if (ev.record.type === "usage") {
        totalTokens.value += ev.record.input_tokens + ev.record.output_tokens;
      }
    }
    if (ev.type === "chat_renamed") {
      const idx = chats.value.findIndex((c) => c.id === ev.chat_id);
      if (idx >= 0) {
        chats.value = chats.value.map((c) =>
          c.id === ev.chat_id ? { ...c, title: ev.title } : c
        );
      }
    }
    if (ev.type === "task_finished") {
      activeTask.value = false;
      if (ev.chat_id === activeChatId.value) {
        streamingText.value = "";
        designerApi.getDesign(scenarioId).then((s) => {
          chats.value = s.chats;
        });
        void store.refreshFiles();
      }
    }
    if (ev.type === "task_started") activeTask.value = true;
    if (ev.type === "files_changed") void store.refreshFiles();
  }

  instances.set(scenarioId, store);
  return store;
}

export function provideDesigner(scenarioId: string) {
  const store = useDesigner(scenarioId);
  provide(KEY, store);
  return store;
}

export function injectDesigner(): DesignerStore {
  const s = inject(KEY);
  if (!s) throw new Error("DesignerStore 未 provide");
  return s;
}
