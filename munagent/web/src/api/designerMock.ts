/**
 * 设计器 Mock API — 后端未就绪时前端自洽演示.
 */

import type {
  ChatMetaRecord,
  ChatRecord,
  DesignerEvent,
  DesignerState,
  FileNode,
  HistoryDiffEntry,
  HistorySnapshot,
  ValidationIssue,
} from "../types/designer";
import { applyUnifiedDiff, reverseUnifiedDiff } from "../utils/diff";
import { api as legacyApi } from "../api";

const stores = new Map<string, MockScenarioStore>();

type EventListener = (ev: DesignerEvent) => void;

class MockScenarioStore {
  scenarioId: string;
  title = "";
  readonly = false;
  files: Record<string, string> = {};
  chats = new Map<string, ChatRecord[]>();
  history: HistorySnapshot[] = [];
  validation: ValidationIssue[] = [];
  activeTask: DesignerState["active_task"] = null;
  sseSeq = 0;
  listeners = new Set<EventListener>();
  private abortFlag = false;

  constructor(scenarioId: string) {
    this.scenarioId = scenarioId;
  }

  subscribe(fn: EventListener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(ev: Omit<DesignerEvent, "seq">) {
    const full = { ...ev, seq: ++this.sseSeq } as DesignerEvent;
    for (const fn of this.listeners) fn(full);
  }

  chatMetaList() {
    return [...this.chats.entries()]
      .map(([id, records]) => {
        const meta = records[0] as ChatMetaRecord | undefined;
        const turns = records.filter((r) => r.type === "user_message").length;
        return {
          id,
          title: meta?.title ?? id,
          created_at: meta?.created_at ?? new Date().toISOString(),
          updated_at: new Date().toISOString(),
          turns,
        };
      })
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }

  fileTree(): FileNode[] {
    const paths = Object.keys(this.files)
      .filter((p) => !p.startsWith("chats/") && !p.startsWith(".history/"))
      .sort();
    return buildTree(paths);
  }

  async ensureLoaded() {
    if (Object.keys(this.files).length) return;
    try {
      const detail = await legacyApi.getScenario(this.scenarioId);
      this.title = detail.title;
      this.readonly = detail.readonly;
      this.files = { ...detail.files };
    } catch {
      this.title = this.scenarioId;
      this.files = {
        "manifest.yaml": `id: ${this.scenarioId}\ntitle: 演示场景\n`,
        "background.md": "# 演示\n\n待编写。\n",
        "venues.yaml": "venues: []\n",
      };
    }
    this.runValidation();
  }

  runValidation() {
    const issues: ValidationIssue[] = [];
    if (!this.files["manifest.yaml"]) {
      issues.push({ level: "error", message: "缺少 manifest.yaml", path: "manifest.yaml" });
    }
    if (!this.files["background.md"]) {
      issues.push({ level: "warning", message: "缺少 background.md", path: "background.md" });
    }
    if (!Object.keys(this.files).some((p) => p.startsWith("seats/"))) {
      issues.push({ level: "warning", message: "seats/ 目录为空" });
    }
    this.validation = issues;
  }

  getState(): DesignerState {
    return {
      active_task: this.activeTask,
      chats: this.chatMetaList(),
      validation: this.validation,
    };
  }

  createChat(title = "新对话") {
    const id = `${formatId()}-${rand4()}`;
    const meta: ChatMetaRecord = {
      type: "meta",
      v: 1,
      id,
      title,
      created_at: new Date().toISOString(),
    };
    this.chats.set(id, [meta]);
    return this.chatMetaList().find((c) => c.id === id)!;
  }

  getChatRecords(chatId: string) {
    return this.chats.get(chatId) ?? [];
  }

  renameChat(chatId: string, title: string) {
    const recs = this.chats.get(chatId);
    if (!recs?.length) throw new Error("对话不存在");
    recs[0] = { ...(recs[0] as ChatMetaRecord), title };
  }

  deleteChat(chatId: string) {
    this.chats.delete(chatId);
  }

  async sendMessage(chatId: string, text: string, contextFile?: string) {
    if (this.activeTask) throw new Error("另一对话正在生成");
    if (this.readonly) throw new Error("只读场景不可对话, 请先另存为副本");

    const recs = this.chats.get(chatId);
    if (!recs) throw new Error("对话不存在");

    const turn = recs.filter((r) => r.type === "user_message").length + 1;
    const taskId = `task-${Date.now()}`;
    this.activeTask = { task_id: taskId, chat_id: chatId, turn };
    this.abortFlag = false;

    const push = (record: Omit<ChatRecord, "seq">) => {
      const full = { ...record, seq: recs.length } as ChatRecord;
      recs.push(full);
      this.emit({ type: "record_appended", chat_id: chatId, record: full });
      return full;
    };

    push({ type: "user_message", turn, ts: now(), text });
    this.emit({ type: "task_started", chat_id: chatId, task_id: taskId, turn });

    await delay(400);
    if (this.abortFlag) return this.finishAborted(chatId, recs);

    const intro = contextFile
      ? `收到, 我会结合当前文件 ${contextFile} 来处理你的请求。`
      : "好的, 我来处理你的请求。";
    for (const ch of intro) {
      this.emit({ type: "text_delta", chat_id: chatId, delta: ch });
      await delay(12);
    }
    push({ type: "agent_text", turn, ts: now(), text: intro });

    await delay(300);
    push({
      type: "tool_call",
      turn,
      ts: now(),
      tool: "list_files",
      args_summary: "seats/",
      status: "ok",
      result_summary: `${Object.keys(this.files).filter((p) => p.startsWith("seats/")).length} 个席位`,
    });

    if (text.includes("席位") || text.includes("生成")) {
      const path = "seats/demo_delegate.yaml";
      const content =
        "id: demo_delegate\nname: 演示代表\nvenue: main\npublic:\n  title: 代表\n  faction: 温和派\n  stance: 待定\n";
      const diff = `--- /dev/null\n+++ ${path}\n@@ -0,0 +1,6 @@\n+id: demo_delegate\n+name: 演示代表\n`;
      this.files[path] = content;
      push({ type: "file_edit", turn, ts: now(), path, op: "create", diff });
      this.runValidation();
      this.emit({ type: "files_changed", paths: [path] });
      push({
        type: "agent_text",
        turn,
        ts: now(),
        text: `已创建 ${path}, 你可以在编辑模式打开细调。`,
      });
    } else {
      push({
        type: "agent_text",
        turn,
        ts: now(),
        text: "我已记录你的意图。你可以让我「检查一致性」或「继续完善当前文件」。",
      });
    }

    push({
      type: "usage",
      turn,
      ts: now(),
      model: "deepseek-v4-pro",
      input_tokens: 4200,
      output_tokens: 680,
      tool_calls: 1,
    });

    this.activeTask = null;
    this.emit({ type: "task_finished", chat_id: chatId, result: "done", error: null });
  }

  private finishAborted(chatId: string, recs: ChatRecord[]) {
    recs.push({
      seq: recs.length,
      turn: this.activeTask?.turn,
      ts: now(),
      type: "system",
      kind: "aborted",
      text: "任务已中止",
    });
    this.activeTask = null;
    this.emit({ type: "task_finished", chat_id: chatId, result: "aborted", error: null });
  }

  abort() {
    this.abortFlag = true;
  }

  getFile(path: string) {
    if (!(path in this.files)) throw new Error("文件不存在");
    return this.files[path];
  }

  putFile(path: string, content: string) {
    if (this.readonly) throw new Error("只读");
    this.files[path] = content;
    this.runValidation();
    this.emit({ type: "files_changed", paths: [path] });
    return this.validation;
  }

  deleteFile(path: string) {
    delete this.files[path];
    this.runValidation();
    this.emit({ type: "files_changed", paths: [path] });
  }

  revertEdit(chatId: string, seq: number) {
    const recs = this.chats.get(chatId);
    const record = recs?.find((r) => r.seq === seq && r.type === "file_edit");
    if (!record || record.type !== "file_edit") throw new Error("记录不存在");
    const current = this.files[record.path] ?? "";
    const reversed = reverseUnifiedDiff(record.diff);
    const next = applyUnifiedDiff(current, reversed);
    if (next === null) {
      const err = new Error("内容已漂移") as Error & { code: string };
      err.code = "DRIFT";
      throw err;
    }
    this.files[record.path] = next;
    recs!.push({
      seq: recs!.length,
      ts: now(),
      type: "system",
      kind: "revert",
      text: `已撤销 seq=${seq} 的编辑`,
    });
    this.runValidation();
    this.emit({ type: "files_changed", paths: [record.path] });
  }

  listHistory() {
    return [...this.history].sort((a, b) => b.created_at.localeCompare(a.created_at));
  }

  createManualSnapshot(note?: string) {
    const snap: HistorySnapshot = {
      id: `${formatId()}-manual`,
      created_at: new Date().toISOString(),
      kind: "manual",
      reason: note || "手动存档",
      note,
    };
    this.history.unshift(snap);
    return snap;
  }

  getHistoryDiff(snapId: string): HistoryDiffEntry[] {
    void snapId;
    return Object.keys(this.files)
      .filter((p) => !p.startsWith("chats/"))
      .slice(0, 3)
      .map((path) => ({
        path,
        status: "modified" as const,
        additions: 2,
        deletions: 1,
        diff: `--- a/${path}\n+++ b/${path}\n@@ -1,1 +1,2 @@\n 行1\n+行2\n`,
      }));
  }

  async duplicate(newId: string, newTitle: string) {
    await legacyApi.createScenario({ id: newId, title: newTitle });
    const target = getStore(newId);
    target.files = { ...this.files };
    target.title = newTitle;
    target.readonly = false;
    return newId;
  }
}

function getStore(scenarioId: string) {
  let s = stores.get(scenarioId);
  if (!s) {
    s = new MockScenarioStore(scenarioId);
    stores.set(scenarioId, s);
  }
  return s;
}

function buildTree(paths: string[]): FileNode[] {
  const root: FileNode[] = [];
  for (const path of paths) {
    const parts = path.split("/");
    let level = root;
    for (let i = 0; i < parts.length; i++) {
      const name = parts[i];
      const isFile = i === parts.length - 1;
      const fullPath = parts.slice(0, i + 1).join("/");
      let node = level.find((n) => n.name === name);
      if (!node) {
        node = {
          name,
          path: fullPath,
          kind: isFile ? "file" : "dir",
          children: isFile ? undefined : [],
        };
        level.push(node);
      }
      if (!isFile && node.children) level = node.children;
    }
  }
  const sortNodes = (nodes: FileNode[]) => {
    nodes.sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    for (const n of nodes) if (n.children) sortNodes(n.children);
  };
  sortNodes(root);
  return root;
}

function now() {
  return new Date().toISOString();
}

function formatId() {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function rand4() {
  return Math.random().toString(16).slice(2, 6);
}

function delay(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

export const designerApi = {
  getDesign: async (scenarioId: string) => {
    const s = getStore(scenarioId);
    await s.ensureLoaded();
    return { title: s.title, readonly: s.readonly, ...s.getState(), fileTree: s.fileTree() };
  },
  subscribeEvents: (scenarioId: string, fn: EventListener) => getStore(scenarioId).subscribe(fn),
  getChat: async (scenarioId: string, chatId: string) => {
    await getStore(scenarioId).ensureLoaded();
    return getStore(scenarioId).getChatRecords(chatId);
  },
  createChat: async (scenarioId: string, title?: string) => {
    await getStore(scenarioId).ensureLoaded();
    return getStore(scenarioId).createChat(title);
  },
  patchChat: (scenarioId: string, chatId: string, title: string) =>
    getStore(scenarioId).renameChat(chatId, title),
  deleteChat: (scenarioId: string, chatId: string) => getStore(scenarioId).deleteChat(chatId),
  sendMessage: async (scenarioId: string, chatId: string, text: string, contextFile?: string) => {
    await getStore(scenarioId).sendMessage(chatId, text, contextFile);
    return { task_id: "mock" };
  },
  abort: (scenarioId: string) => getStore(scenarioId).abort(),
  getFile: async (scenarioId: string, path: string) => {
    await getStore(scenarioId).ensureLoaded();
    return { path, content: getStore(scenarioId).getFile(path) };
  },
  putFile: (scenarioId: string, path: string, content: string) =>
    getStore(scenarioId).putFile(path, content),
  deleteFile: (scenarioId: string, path: string) => getStore(scenarioId).deleteFile(path),
  revert: (scenarioId: string, chatId: string, seq: number) =>
    getStore(scenarioId).revertEdit(chatId, seq),
  listHistory: (scenarioId: string) => getStore(scenarioId).listHistory(),
  createSnapshot: (scenarioId: string, note?: string) =>
    getStore(scenarioId).createManualSnapshot(note),
  historyDiff: (scenarioId: string, snapId: string) =>
    getStore(scenarioId).getHistoryDiff(snapId),
  duplicate: (scenarioId: string, newId: string, newTitle: string) =>
    getStore(scenarioId).duplicate(newId, newTitle),
  enrichSummaries: async <T extends { id: string }>(list: T[]) =>
    Promise.all(
      list.map(async (s) => {
        const store = getStore(s.id);
        await store.ensureLoaded();
        const chats = store.chatMetaList();
        return { ...s, chat_count: chats.length, last_chat_at: chats[0]?.updated_at ?? null };
      })
    ),
};
