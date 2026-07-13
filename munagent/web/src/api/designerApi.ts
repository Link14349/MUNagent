/**
 * 设计器 API — 文件/历史/chats/Agent 任务走真实后端.
 */

import { createSseClient } from "../composables/useSse";
import type {
  ChatMeta,
  ChatRecord,
  DesignerEvent,
  DesignerState,
  FileNode,
  HistoryDiffEntry,
  HistorySnapshot,
  RevertConflict,
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
    throw new Error(typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail));
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

  subscribeEvents: (scenarioId: string, fn: EventListener) => {
    const client = createSseClient(`/api/scenarios/${scenarioId}/design/events`, fn);
    return () => client.close();
  },

  getChat: async (scenarioId: string, chatId: string) => {
    const body = await request<{ records: ChatRecord[]; todo: string | null }>(
      `/api/scenarios/${scenarioId}/chats/${chatId}`
    );
    return {
      records: normalizeRecords(body.records),
      todo: body.todo ?? null,
    };
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

  sendMessage: async (
    scenarioId: string,
    chatId: string,
    text: string,
    contextFile?: string
  ) => {
    const res = await fetch(`/api/scenarios/${scenarioId}/chats/${chatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        context_file: contextFile ?? null,
      }),
    });
    if (res.status === 409) {
      const err = await res.json().catch(() => ({ detail: "另一对话正在生成" }));
      throw new Error(typeof err.detail === "string" ? err.detail : "另一对话正在生成");
    }
    if (res.status !== 202) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(typeof err.detail === "string" ? err.detail : res.statusText);
    }
    return res.json() as Promise<{ task_id: string }>;
  },

  abort: (scenarioId: string) => {
    void fetch(`/api/scenarios/${scenarioId}/design/abort`, { method: "POST" });
  },

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

  revert: async (scenarioId: string, chatId: string, seq: number) => {
    const res = await fetch(
      `/api/scenarios/${scenarioId}/chats/${chatId}/revert/${seq}`,
      { method: "POST" }
    );
    if (res.status === 409) {
      const body = await res.json().catch(() => ({}));
      const detail = (body.detail ?? {}) as RevertConflict;
      const err = new Error(detail.detail || "内容已漂移") as Error & { conflict?: RevertConflict };
      err.conflict = detail;
      throw err;
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(typeof err.detail === "string" ? err.detail : res.statusText);
    }
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
