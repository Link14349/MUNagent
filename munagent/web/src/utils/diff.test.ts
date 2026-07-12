import { describe, expect, it } from "vitest";
import {
  applyUnifiedDiff,
  canRevertEdit,
  diffLineStats,
  parseUnifiedDiff,
  reverseUnifiedDiff,
} from "./diff";

describe("parseUnifiedDiff", () => {
  it("着色行类型", () => {
    const diff = `--- a/x.yaml\n+++ b/x.yaml\n@@ -1,2 +1,3 @@\n line\n+add\n-del`;
    const lines = parseUnifiedDiff(diff);
    expect(lines.some((l) => l.kind === "hunk")).toBe(true);
    expect(lines.filter((l) => l.kind === "add").length).toBe(1);
    expect(lines.filter((l) => l.kind === "del").length).toBe(1);
  });
});

describe("diffLineStats", () => {
  it("统计增删行", () => {
    const s = diffLineStats("@@\n+1\n+2\n-3");
    expect(s).toEqual({ additions: 2, deletions: 1 });
  });
});

describe("applyUnifiedDiff", () => {
  it("应用补丁", () => {
    const base = "a\nb";
    const diff = `@@ -1,2 +1,3 @@\n a\n+b2\n b`;
    expect(applyUnifiedDiff(base, diff)).toBe("a\nb2\nb");
  });
});

describe("canRevertEdit", () => {
  it("内容未漂移时可撤销", () => {
    const before = "a\nb";
    const diff = `@@ -1,2 +1,3 @@\n a\n+c\n b`;
    const after = applyUnifiedDiff(before, diff)!;
    expect(canRevertEdit(after, diff)).toBe(true);
    expect(applyUnifiedDiff(after, reverseUnifiedDiff(diff))).toBe(before);
  });

  it("内容漂移时不可撤销", () => {
    const diff = `@@ -1,1 +1,2 @@\n x\n+y`;
    expect(canRevertEdit("x\nz", diff)).toBe(false);
  });
});
