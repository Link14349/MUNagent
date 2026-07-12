import { describe, expect, it } from "vitest";
import { parseTodoText, todoProgress } from "./todo";

describe("parseTodoText", () => {
  it("解析完成与未完成项", () => {
    const items = parseTodoText("[ ] 第一项\n[x] 第二项\n");
    expect(items).toEqual([
      { done: false, text: "第一项" },
      { done: true, text: "第二项" },
    ]);
    expect(todoProgress(items)).toEqual({ done: 1, total: 2 });
  });
});
