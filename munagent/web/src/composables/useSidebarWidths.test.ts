import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

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

describe("useSidebarWidths", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("默认宽度与常量一致", async () => {
    const { useSidebarWidths, SIDEBAR_DEFAULTS } = await import("./useSidebarWidths");
    const { widths } = useSidebarWidths("s1");
    expect(widths.edit.left).toBe(SIDEBAR_DEFAULTS.edit.left);
    expect(widths.chat.right).toBe(SIDEBAR_DEFAULTS.chat.right);
  });

  it("setWidth 钳制范围并持久化", async () => {
    const { useSidebarWidths, SIDEBAR_LIMITS } = await import("./useSidebarWidths");
    const { widths, setWidth } = useSidebarWidths("s1");

    setWidth("edit", "left", 999);
    expect(widths.edit.left).toBe(SIDEBAR_LIMITS.left.max);
    expect(localStorage.getItem("designer-s1-edit-left-w")).toBe(String(SIDEBAR_LIMITS.left.max));

    setWidth("edit", "right", 100);
    expect(widths.edit.right).toBe(SIDEBAR_LIMITS.right.min);
  });

  it("切换场景时加载对应宽度", async () => {
    const { useSidebarWidths } = await import("./useSidebarWidths");
    localStorage.setItem("designer-s2-edit-left-w", "300");

    const id = ref("s1");
    const { widths } = useSidebarWidths(id);
    expect(widths.edit.left).toBe(220);

    id.value = "s2";
    await nextTick();
    expect(widths.edit.left).toBe(300);
  });

  it("resetWidth 恢复默认值", async () => {
    const { useSidebarWidths, SIDEBAR_DEFAULTS } = await import("./useSidebarWidths");
    const { widths, setWidth, resetWidth } = useSidebarWidths("s1");

    setWidth("chat", "right", 400);
    resetWidth("chat", "right");
    expect(widths.chat.right).toBe(SIDEBAR_DEFAULTS.chat.right);
  });
});
