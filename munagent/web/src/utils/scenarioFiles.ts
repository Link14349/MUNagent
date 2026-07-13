/** 场景包内不可通过 UI 删除的核心文件(与后端 delete_file 一致). */
const PROTECTED_FILES = new Set(["manifest.yaml", "venues.yaml", "background.md"]);

export function isProtectedFile(path: string): boolean {
  return PROTECTED_FILES.has(path);
}

export function canDeleteFile(path: string, readonly: boolean): boolean {
  return !readonly && !isProtectedFile(path);
}
