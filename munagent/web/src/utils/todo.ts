/** 解析 agent todo 全文(01-data-chats.md §2.4). */

export interface TodoItem {
  done: boolean;
  text: string;
}

export function parseTodoText(text: string): TodoItem[] {
  const items: TodoItem[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith("[x] ")) {
      items.push({ done: true, text: line.slice(4) });
    } else if (line.startsWith("[ ] ")) {
      items.push({ done: false, text: line.slice(4) });
    } else {
      items.push({ done: false, text: line });
    }
  }
  return items;
}

export function todoProgress(items: TodoItem[]): { done: number; total: number } {
  return { done: items.filter((i) => i.done).length, total: items.length };
}
