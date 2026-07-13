import { describe, expect, it } from "vitest";
import type { ToolCallRecord } from "../types/designer";
import { mergeToolCallsForDisplay } from "./mergeToolCalls";

function tool(partial: Partial<ToolCallRecord> & Pick<ToolCallRecord, "tool" | "args_summary" | "status">): ToolCallRecord {
  return {
    seq: partial.seq ?? 0,
    ts: partial.ts ?? "",
    type: "tool_call",
    ...partial,
  };
}

describe("mergeToolCallsForDisplay", () => {
  it("folds running then ok into one card", () => {
    const running = tool({
      seq: 1,
      tool: "read_file",
      args_summary: "path='a.md'",
      status: "running",
    });
    const ok = tool({
      seq: 2,
      tool: "read_file",
      args_summary: "path='a.md'",
      status: "ok",
      result_summary: "1200 字符",
    });
    const out = mergeToolCallsForDisplay([
      { type: "user_message", seq: 0, ts: "", text: "hi" },
      running,
      ok,
    ]);
    const tools = out.filter((r) => r.type === "tool_call");
    expect(tools).toHaveLength(1);
    expect(tools[0].status).toBe("ok");
  });

  it("dedupes jsonl ok plus sse replay ok", () => {
    const ok1 = tool({
      seq: 1,
      tool: "read_file",
      args_summary: "path='a.md'",
      status: "ok",
      result_summary: "a",
    });
    const running = tool({
      tool: "read_file",
      args_summary: "path='a.md'",
      status: "running",
    });
    const ok2 = tool({
      seq: 1,
      tool: "read_file",
      args_summary: "path='a.md'",
      status: "ok",
      result_summary: "a",
    });
    const out = mergeToolCallsForDisplay([ok1, running, ok2]);
    expect(out.filter((r) => r.type === "tool_call")).toHaveLength(1);
  });

  it("keeps distinct tool calls separate", () => {
    const a = tool({ tool: "read_file", args_summary: "path='a.md'", status: "running" });
    const b = tool({ tool: "read_file", args_summary: "path='b.md'", status: "running" });
    const out = mergeToolCallsForDisplay([a, b]);
    expect(out.filter((r) => r.type === "tool_call")).toHaveLength(2);
  });
});
