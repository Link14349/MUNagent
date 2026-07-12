/**
 * 设计器 API — 文件/历史/chats 走真实后端; Agent/SSE 待接入.
 */

import type {
  ChatMeta,
  ChatRecord,
  DesignerEvent,
  DesignerState,
  FileNode,
  HistoryDiffEntry,
  HistorySnapshot,
  ValidationIssue,
} from "../types/designer";
import type { ScenarioSummary } from "../api";

type EventListener = (ev: DesignerEvent) => void;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json() as Promise<T>;
  return undefined as T;
}

function enc(path: string) {
  return path
    .split("/")
    .map((p) => encodeURIComponent(p))
    .join("/");
}

function normalizeRecords(rows: ChatRecord[]): ChatRecord[] {
  return rows.map((r, i) => ({ ...r, seq: "seq" in r && r.seq != null ? r.seq : i }));
}

export const designerApi = {
  getDesign: async (scenarioId: string) => {
    const state = await request<
      DesignerState & { file_tree: FileNode[]; readonly: boolean; title: string }
    >(`/api/scenarios/${scenarioId}/design`);
    return {
      title: state.title,
      readonly: state.readonly,
      active_task: state.active_task,
      chats: state.chats,
      validation: state.validation,
      fileTree: state.file_tree,
    };
  },

  subscribeEvents: (_scenarioId: string, _fn: EventListener) => {
    return () => {};
  },

  getChat: async (scenarioId: string, chatId: string) => {
    const rows = await request<ChatRecord[]>(`/api/scenarios/${scenarioId}/chats/${chatId}`);
    return normalizeRecords(rows);
  },

  createChat: (scenarioId: string, title?: string) =>
    request<ChatMeta>(`/api/scenarios/${scenarioId}/chats`, {
      method: "POST",
      body: JSON.stringify({ title: title || "新对话" }),
    }),

  patchChat: (scenarioId: string, chatId: string, title: string) =>
    request<ChatMeta>(`/api/scenarios/${scenarioId}/chats/${chatId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  deleteChat: (scenarioId: string, chatId: string) =>
    request<{ status: string }>(`/api/scenarios/${scenarioId}/chats/${chatId}`, {
      method: "DELETE",
    }),

  sendMessage: async (_scenarioId: string, _chatId: string, _text: string, _contextFile?: string) => {
    throw new Error("设计 Agent 尚未接入");
  },

  abort: (_scenarioId: string) => {},

  getFile: (scenarioId: string, path: string) =>
    request<{ path: string; content: string }>(
      `/api/scenarios/${scenarioId}/files/${enc(path)}`
    ),

  putFile: async (scenarioId: string, path: string, content: string) => {
    const res = await request<{ validation: ValidationIssue[] }>(
      `/api/scenarios/${scenarioId}/files/${enc(path)}`,
      { method: "PUT", body: JSON.stringify({ content }) }
    );
    return res.validation;
  },

  deleteFile: (scenarioId: string, path: string) =>
    request<{ validation: ValidationIssue[] }>(
      `/api/scenarios/${scenarioId}/files/${enc(path)}`,
      { method: "DELETE" }
    ),

  renameFile: (scenarioId: string, path: string, newPath: string) =>
    request<{ validation: ValidationIssue[] }>(
      `/api/scenarios/${scenarioId}/files/${enc(path)}/rename`,
      { method: "POST", body: JSON.stringify({ new_path: newPath }) }
    ),

  revert: async () => {
    throw new Error("撤销依赖设计 Agent, 尚未接入");
  },

  listHistory: (scenarioId: string) =>
    request<HistorySnapshot[]>(`/api/scenarios/${scenarioId}/history`),

  createSnapshot: (scenarioId: string, note?: string) =>
    request<HistorySnapshot>(`/api/scenarios/${scenarioId}/history`, {
      method: "POST",
      body: JSON.stringify({ note: note || null }),
    }),

  historyDiff: (scenarioId: string, snapId: string) =>
    request<HistoryDiffEntry[]>(`/api/scenarios/${scenarioId}/history/${snapId}/diff`),

  restoreHistory: (scenarioId: string, snapId: string) =>
    request<{ validation: ValidationIssue[] }>(
      `/api/scenarios/${scenarioId}/history/${snapId}/restore`,
      { method: "POST" }
    ),

  deleteSnapshot: (scenarioId: string, snapId: string) =>
    request<{ status: string }>(`/api/scenarios/${scenarioId}/history/${snapId}`, {
      method: "DELETE",
    }),

  duplicate: (scenarioId: string, newId: string, newTitle: string) =>
    request<{ id: string }>(`/api/scenarios/${scenarioId}/duplicate`, {
      method: "POST",
      body: JSON.stringify({ new_id: newId, new_title: newTitle }),
    }).then((r) => r.id),

  exportZip: async (scenarioId: string, includeRaw = false) => {
    const res = await fetch(
      `/api/scenarios/${scenarioId}/export?include_raw=${includeRaw ? "true" : "false"}`,
      { method: "POST" }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${scenarioId}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  },

  enrichSummaries: async (list: ScenarioSummary[]) => {
    try {
      const enriched = await request<
        Array<ScenarioSummary & { chat_count: number; last_chat_at: string | null }>
      >("/api/scenarios-enriched");
      const map = new Map(enriched.map((s) => [s.id, s]));
      return list.map((s) => {
        const e = map.get(s.id);
        return {
          ...s,
          chat_count: e?.chat_count ?? 0,
          last_chat_at: e?.last_chat_at ?? null,
        };
      });
    } catch {
      return list.map((s) => ({ ...s, chat_count: 0, last_chat_at: null }));
    }
  },
};
