import { computed, reactive, watch, type Ref } from "vue";

export type DesignerMode = "edit" | "chat";
export type PaneSide = "left" | "right";

export const SIDEBAR_DEFAULTS = {
  edit: { left: 220, right: 380 },
  chat: { left: 240, right: 300 },
} as const;

export const SIDEBAR_LIMITS = {
  left: { min: 160, max: 480 },
  right: { min: 240, max: 640 },
} as const;

type Widths = {
  edit: { left: number; right: number };
  chat: { left: number; right: number };
};

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n));
}

function widthKey(scenarioId: string, mode: DesignerMode, side: PaneSide) {
  return `designer-${scenarioId}-${mode}-${side}-w`;
}

function loadWidths(scenarioId: string): Widths {
  const result: Widths = {
    edit: { ...SIDEBAR_DEFAULTS.edit },
    chat: { ...SIDEBAR_DEFAULTS.chat },
  };
  for (const mode of ["edit", "chat"] as const) {
    for (const side of ["left", "right"] as const) {
      const raw = localStorage.getItem(widthKey(scenarioId, mode, side));
      if (!raw) continue;
      const n = Number.parseInt(raw, 10);
      if (Number.isNaN(n)) continue;
      const { min, max } = SIDEBAR_LIMITS[side];
      result[mode][side] = clamp(n, min, max);
    }
  }
  return result;
}

/** 管理 Designer 左右侧栏宽度, 按场景与模式分别持久化到 localStorage. */
export function useSidebarWidths(scenarioId: Ref<string> | string) {
  const id = computed(() => (typeof scenarioId === "string" ? scenarioId : scenarioId.value));
  const widths = reactive(loadWidths(id.value));

  watch(id, (next) => {
    const loaded = loadWidths(next);
    widths.edit.left = loaded.edit.left;
    widths.edit.right = loaded.edit.right;
    widths.chat.left = loaded.chat.left;
    widths.chat.right = loaded.chat.right;
  });

  function setWidth(mode: DesignerMode, side: PaneSide, w: number) {
    const { min, max } = SIDEBAR_LIMITS[side];
    const clamped = clamp(w, min, max);
    widths[mode][side] = clamped;
    localStorage.setItem(widthKey(id.value, mode, side), String(clamped));
  }

  function resetWidth(mode: DesignerMode, side: PaneSide) {
    setWidth(mode, side, SIDEBAR_DEFAULTS[mode][side]);
  }

  return { widths, setWidth, resetWidth };
}
