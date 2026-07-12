/** SSE seq 续传纯逻辑 — design/designer/03 §3 */

export function eventsAfterSeq<T extends { seq: number }>(
  events: T[],
  lastEventId: number | null
): T[] {
  if (lastEventId === null) return events;
  return events.filter((e) => e.seq > lastEventId);
}

export function maxSeq<T extends { seq: number }>(events: T[]): number | null {
  if (!events.length) return null;
  return Math.max(...events.map((e) => e.seq));
}
