import { describe, expect, it } from "vitest";
import type { ToolCallRecord } from "../types/designer";
import { formatToolArgs, summarizeWriteFileArgs } from "./formatToolArgs";

function tool(args_summary: string, toolName = "write_file"): ToolCallRecord {
  return {
    seq: 1,
    ts: "",
    type: "tool_call",
    tool: toolName,
    args_summary,
    status: "ok",
  };
}

describe("summarizeWriteFileArgs", () => {
  it("passes through compact summary", () => {
    expect(summarizeWriteFileArgs("seats/a.yaml (1200 字符)")).toBe("seats/a.yaml (1200 字符)");
  });

  it("collapses content-first python repr", () => {
    const body = "# Armand Marrast\n" + "x".repeat(400);
    const legacy = `content='${body}', path='seats/marrast.yaml'`;
    const out = summarizeWriteFileArgs(legacy);
    expect(out).toMatch(/^seats\/marrast\.yaml \(\d+ 字符\)$/);
    expect(out.length).toBeLessThan(80);
  });

  it("collapses raw json arguments", () => {
    const legacy = JSON.stringify({
      content: "# Louis\n" + "y".repeat(200),
      path: "seats/garnier.yaml",
    });
    expect(summarizeWriteFileArgs(legacy)).toMatch(/^seats\/garnier\.yaml \(\d+ 字符\)$/);
  });

  it("handles truncated json blob", () => {
    const legacy = '{"content": "# Louis-Antoine Garnier-Pagès\\nid: garnier';
    const out = summarizeWriteFileArgs(legacy);
    expect(out).toMatch(/\(\d+ 字符\)$/);
    expect(out.length).toBeLessThan(60);
  });
});

describe("formatToolArgs", () => {
  it("formats write_file via summarize", () => {
    const legacy = tool(`content='${"a".repeat(300)}', path='seats/x.yaml'`);
    expect(formatToolArgs(legacy)).toMatch(/^seats\/x\.yaml \(300 字符\)$/);
  });
});
