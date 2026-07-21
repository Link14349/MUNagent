/** 与 design/designer/01-data-chats.md、03-agent-interaction.md 对齐 */

export type DesignerMode = "edit" | "chat";

export type ChatRecordType =
  | "meta"
  | "user_message"
  | "agent_text"
  | "tool_call"
  | "file_edit"
  | "system"
  | "usage"
  | "todo";

export interface ChatMeta {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turns: number;
}

export interface ChatRecordBase {
  seq: number;
  turn?: number;
  ts: string;
  type: ChatRecordType;
}

export interface ChatMetaRecord {
  type: "meta";
  v: number;
  id: string;
  title: string;
  created_at: string;
}

export interface UserMessageRecord extends ChatRecordBase {
  type: "user_message";
  text: string;
}

export interface AgentTextRecord extends ChatRecordBase {
  type: "agent_text";
  text: string;
}

export interface ToolCallRecord extends ChatRecordBase {
  type: "tool_call";
  tool: string;
  args_summary: string;
  status: "ok" | "error" | "running";
  result_summary?: string;
}

export interface FileEditRecord extends ChatRecordBase {
  type: "file_edit";
  path: string;
  op: "create" | "modify" | "delete";
  diff: string;
}

export interface SystemRecord extends ChatRecordBase {
  type: "system";
  kind: "aborted" | "error" | "revert";
  text: string;
}

export interface UsageRecord extends ChatRecordBase {
  type: "usage";
  model: string;
  input_tokens: number;
  output_tokens: number;
  tool_calls: number;
}

export interface TodoRecord extends ChatRecordBase {
  type: "todo";
  text: string;
}

export type ChatRecord =
  | ChatMetaRecord
  | UserMessageRecord
  | AgentTextRecord
  | ToolCallRecord
  | FileEditRecord
  | SystemRecord
  | UsageRecord
  | TodoRecord;

export interface ValidationIssue {
  level: "error" | "warning";
  message: string;
  path?: string;
}

export interface ActiveTask {
  task_id: string;
  chat_id: string;
  turn: number;
}

export interface DesignerState {
  active_task: ActiveTask | null;
  chats: ChatMeta[];
  validation: ValidationIssue[];
}

export interface FileNode {
  name: string;
  path: string;
  kind: "file" | "dir";
  children?: FileNode[];
}

export type HistoryKind = "auto" | "manual" | "restore_backup";

export interface HistorySnapshot {
  id: string;
  created_at: string;
  kind: HistoryKind;
  reason: string;
  note?: string;
  chat_id?: string;
  turn?: number;
}

export interface HistoryDiffEntry {
  path: string;
  status: "added" | "modified" | "deleted";
  additions: number;
  deletions: number;
  diff?: string;
}

export interface RevertConflict {
  detail: string;
  path: string;
  current_content: string;
  expected_content: string;
  original_content: string;
}

export type DesignerEvent =
  | { seq: number; type: "task_started"; chat_id: string; task_id: string; turn: number }
  | { seq: number; type: "think_delta"; chat_id: string; delta: string }
  | { seq: number; type: "text_delta"; chat_id: string; delta: string }
  | { seq: number; type: "record_appended"; chat_id: string; record: ChatRecord }
  | {
      seq: number;
      type: "task_finished";
      chat_id: string;
      result: "done" | "aborted" | "failed";
      error: string | null;
    }
  | { seq: number; type: "files_changed"; paths: string[] }
  | { seq: number; type: "chat_renamed"; chat_id: string; title: string };
