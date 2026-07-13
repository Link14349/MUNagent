import { ref, watch, type Ref } from "vue";

function storageKey(scenarioId: string) {
  return `designer-${scenarioId}-file-tree-collapsed`;
}

function loadCollapsed(scenarioId: string): Set<string> {
  try {
    const raw = localStorage.getItem(storageKey(scenarioId));
    if (raw) return new Set(JSON.parse(raw) as string[]);
  } catch {
    /* 损坏的缓存忽略 */
  }
  return new Set();
}

function saveCollapsed(scenarioId: string, collapsed: Set<string>) {
  localStorage.setItem(storageKey(scenarioId), JSON.stringify([...collapsed]));
}

export interface FileTreeExpandState {
  collapsed: Ref<Set<string>>;
  toggleDir: (path: string) => void;
  isExpanded: (path: string) => boolean;
  revealPath: (path: string) => void;
}

const cache = new Map<string, FileTreeExpandState>();

function createExpandState(scenarioId: string): FileTreeExpandState {
  const collapsed = ref(loadCollapsed(scenarioId));

  watch(collapsed, (v) => saveCollapsed(scenarioId, v));

  function applyCollapsed(next: Set<string>) {
    collapsed.value = next;
    saveCollapsed(scenarioId, next);
  }

  function toggleDir(path: string) {
    const next = new Set(collapsed.value);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    applyCollapsed(next);
  }

  function isExpanded(path: string) {
    return !collapsed.value.has(path);
  }

  /** 展开选中文件的全部祖先目录, 不影响兄弟目录的折叠状态 */
  function revealPath(path: string) {
    const parts = path.split("/");
    if (parts.length <= 1) return;
    const next = new Set(collapsed.value);
    for (let i = 1; i < parts.length; i++) {
      next.delete(parts.slice(0, i).join("/"));
    }
    if (next.size === collapsed.value.size) return;
    applyCollapsed(next);
  }

  return { collapsed, toggleDir, isExpanded, revealPath };
}

/** 按场景持久化文件树折叠状态, 同一 scenario 的多个 FileTree 实例共享 */
export function useFileTreeExpand(scenarioId: string): FileTreeExpandState {
  let state = cache.get(scenarioId);
  if (!state) {
    state = createExpandState(scenarioId);
    cache.set(scenarioId, state);
  }
  return state;
}
