import type { ChatRecord, ToolCallRecord } from "../types/designer";

function toolCallKey(r: ToolCallRecord): string {
  return `${r.tool}\0${r.args_summary}`;
}

/** 将 running + ok/error 折叠为一条; 去重 JSONL 与 SSE 重放导致的重复终态. */
export function mergeToolCallsForDisplay(records: ChatRecord[]): ChatRecord[] {
  const out: ChatRecord[] = [];
  const slotByKey = new Map<string, number>();

  for (const r of records) {
    if (r.type !== "tool_call") {
      out.push(r);
      continue;
    }

    const key = toolCallKey(r);
    const slot = slotByKey.get(key);

    if (r.status === "running") {
      if (slot === undefined) {
        slotByKey.set(key, out.length);
        out.push(r);
      } else {
        const prev = out[slot];
        if (prev.type === "tool_call" && prev.status === "running") {
          continue;
        }
        // 已有终态(如 JSONL 落盘) — 忽略 SSE 重放的 running
      }
      continue;
    }

    if (slot !== undefined) {
      out[slot] = r;
    } else {
      slotByKey.set(key, out.length);
      out.push(r);
    }
  }

  return out;
}

export function recordStableKey(rec: ChatRecord, idx: number): string {
  if (rec.type === "tool_call") return `tool:${toolCallKey(rec)}`;
  if ("seq" in rec && rec.seq != null) return `seq:${rec.seq}`;
  return `i:${idx}`;
}
