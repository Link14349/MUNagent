import type { ToolCallRecord } from "../types/designer";

const DISPLAY_MAX = 120;

/** 新后端格式: seats/foo.yaml (1234 字符) */
const COMPACT_WRITE_RE = /^(\S+)\s*\((\d+)\s*字符\)$/;

function extractPathFromWriteArgs(raw: string): string | null {
  const fromKv = raw.match(/(?:^|,\s*)path=(['"])([^'"]*)\1/);
  if (fromKv) return fromKv[2];
  const fromJson = raw.match(/"path"\s*:\s*"((?:[^"\\]|\\.)*)"/);
  if (fromJson) return fromJson[1].replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  return null;
}

/** write_file 参数摘要 — 旧记录可能把 content 全文塞进 args_summary. */
export function summarizeWriteFileArgs(raw: string): string {
  const trimmed = raw.trim();
  if (COMPACT_WRITE_RE.test(trimmed)) return trimmed;

  if (trimmed.startsWith("{")) {
    try {
      const j = JSON.parse(trimmed) as { path?: string; content?: string };
      const path = j.path ?? "?";
      const n = typeof j.content === "string" ? j.content.length : 0;
      return n > 0 ? `${path} (${n} 字符)` : path;
    } catch {
      const path = extractPathFromWriteArgs(trimmed) ?? "?";
      const n = Math.max(0, trimmed.length - 40);
      return `${path} (${n} 字符)`;
    }
  }

  const path = extractPathFromWriteArgs(trimmed);

  if (trimmed.startsWith("content=") || /,\s*content=/.test(trimmed)) {
    const pathVal = path ?? "?";
    const pathTail = trimmed.match(/,\s*path=(['"])([^'"]*)\1\s*$/);
    let contentLen = trimmed.length;
    if (trimmed.startsWith("content=")) {
      const tailStart = pathTail?.index ?? trimmed.length;
      contentLen = Math.max(0, tailStart - 10);
    } else if (pathTail?.index != null) {
      contentLen = Math.max(0, pathTail.index - 20);
    }
    return `${pathVal} (${contentLen} 字符)`;
  }

  if (path) return path;
  if (trimmed.length > DISPLAY_MAX) return `write_file (${trimmed.length} 字符参数)`;
  return trimmed;
}

function summarizeEditTodoArgs(raw: string): string {
  if (raw.includes("todo=") && raw.length > DISPLAY_MAX) {
    const total = raw.match(/\[[ x]\]/g)?.length ?? 0;
    const done = raw.match(/\[x\]/g)?.length ?? 0;
    return total > 0 ? `计划 ${done}/${total} 项` : "计划清单";
  }
  return raw;
}

/** 工具卡 args 展示. */
export function formatToolArgs(record: ToolCallRecord): string {
  let s = record.args_summary;
  if (record.tool === "write_file") {
    s = summarizeWriteFileArgs(s);
  } else if (record.tool === "edit_todo") {
    s = summarizeEditTodoArgs(s);
  }
  if (s.length <= DISPLAY_MAX) return s;
  return `${s.slice(0, DISPLAY_MAX - 1)}…`;
}
