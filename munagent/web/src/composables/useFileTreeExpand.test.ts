import { beforeEach, describe, expect, it, vi } from "vitest";

const store: Record<string, string> = {};

vi.stubGlobal("localStorage", {
  getItem: (k: string) => store[k] ?? null,
  setItem: (k: string, v: string) => {
    store[k] = v;
  },
  removeItem: (k: string) => {
    delete store[k];
  },
  clear: () => {
    for (const k of Object.keys(store)) delete store[k];
  },
});

describe("useFileTreeExpand", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("默认全部展开", async () => {
    const { useFileTreeExpand } = await import("./useFileTreeExpand");
    const { isExpanded } = useFileTreeExpand("s1");
    expect(isExpanded("refs")).toBe(true);
  });

  it("toggleDir 切换并持久化", async () => {
    const { useFileTreeExpand } = await import("./useFileTreeExpand");
    const { toggleDir, isExpanded } = useFileTreeExpand("s1");

    toggleDir("refs");
    expect(isExpanded("refs")).toBe(false);

    const raw = localStorage.getItem("designer-s1-file-tree-collapsed");
    expect(JSON.parse(raw!)).toEqual(["refs"]);
  });

  it("同一场景多实例共享状态", async () => {
    const { useFileTreeExpand } = await import("./useFileTreeExpand");
    const a = useFileTreeExpand("s1");
    const b = useFileTreeExpand("s1");

    a.toggleDir("seats");
    expect(b.isExpanded("seats")).toBe(false);
  });

  it("revealPath 只展开祖先目录", async () => {
    const { useFileTreeExpand } = await import("./useFileTreeExpand");
    const { toggleDir, revealPath, isExpanded } = useFileTreeExpand("s1");

    toggleDir("refs");
    toggleDir("refs/raw");
    revealPath("refs/raw/a.pdf");

    expect(isExpanded("refs")).toBe(true);
    expect(isExpanded("refs/raw")).toBe(true);
  });
});
