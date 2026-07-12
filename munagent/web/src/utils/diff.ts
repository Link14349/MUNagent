/** unified diff 解析与行级着色 — design/designer/03 §6 */

export interface DiffLine {
  kind: "add" | "del" | "ctx" | "hunk";
  text: string;
}

export function parseUnifiedDiff(diff: string): DiffLine[] {
  const lines: DiffLine[] = [];
  for (const raw of diff.split("\n")) {
    if (raw.startsWith("@@")) {
      lines.push({ kind: "hunk", text: raw });
    } else if (raw.startsWith("+") && !raw.startsWith("+++")) {
      lines.push({ kind: "add", text: raw.slice(1) });
    } else if (raw.startsWith("-") && !raw.startsWith("---")) {
      lines.push({ kind: "del", text: raw.slice(1) });
    } else if (raw.startsWith(" ") || raw === "") {
      lines.push({ kind: "ctx", text: raw.startsWith(" ") ? raw.slice(1) : raw });
    } else {
      lines.push({ kind: "ctx", text: raw });
    }
  }
  return lines;
}

export function diffLineStats(diff: string): { additions: number; deletions: number } {
  let additions = 0;
  let deletions = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+") && !line.startsWith("+++")) additions++;
    if (line.startsWith("-") && !line.startsWith("---")) deletions++;
  }
  return { additions, deletions };
}

/** 撤销可行性: 对当前内容应用反向 diff 须成功 */
export function canRevertEdit(currentContent: string, diff: string): boolean {
  const reversed = reverseUnifiedDiff(diff);
  return applyUnifiedDiff(currentContent, reversed) !== null;
}

export function applyUnifiedDiff(base: string, diff: string): string | null {
  const baseLines = base.split("\n");
  const out: string[] = [];
  let i = 0;
  for (const raw of diff.split("\n")) {
    if (raw.startsWith("@@") || raw.startsWith("---") || raw.startsWith("+++")) continue;
    if (raw.startsWith("-")) {
      if (i >= baseLines.length || baseLines[i] !== raw.slice(1)) return null;
      i++;
    } else if (raw.startsWith("+")) {
      out.push(raw.slice(1));
    } else if (raw.startsWith(" ")) {
      if (i >= baseLines.length || baseLines[i] !== raw.slice(1)) return null;
      out.push(baseLines[i]);
      i++;
    }
  }
  while (i < baseLines.length) {
    out.push(baseLines[i++]);
  }
  return out.join("\n");
}

export function reverseUnifiedDiff(diff: string): string {
  return diff
    .split("\n")
    .map((line) => {
      if (line.startsWith("+++")) return line.replace("+++", "---");
      if (line.startsWith("---")) return line.replace("---", "+++");
      if (line.startsWith("+") && !line.startsWith("+++")) return `-${line.slice(1)}`;
      if (line.startsWith("-") && !line.startsWith("---")) return `+${line.slice(1)}`;
      return line;
    })
    .join("\n");
}
