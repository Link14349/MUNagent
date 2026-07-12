/** SSE 连接封装 — 后端就绪后替换 mock subscribe */

import { eventsAfterSeq, maxSeq } from "../utils/sseSeq";
import type { DesignerEvent } from "../types/designer";

export function createSseClient(url: string, onEvent: (ev: DesignerEvent) => void) {
  let lastSeq: number | null = null;
  let es: EventSource | null = null;

  function connect() {
    const u = lastSeq !== null ? `${url}?after=${lastSeq}` : url;
    es = new EventSource(u);
    es.onmessage = (msg) => {
      const ev = JSON.parse(msg.data) as DesignerEvent;
      const pending = eventsAfterSeq([ev], lastSeq);
      for (const e of pending) {
        lastSeq = e.seq;
        onEvent(e);
      }
    };
    es.onerror = () => {
      es?.close();
      setTimeout(connect, 2000);
    };
  }

  connect();
  return {
    close() {
      es?.close();
    },
    get lastSeq() {
      return lastSeq;
    },
    replay(events: DesignerEvent[]) {
      const pending = eventsAfterSeq(events, lastSeq);
      for (const e of pending) {
        lastSeq = maxSeq([e]) ?? e.seq;
        onEvent(e);
      }
    },
  };
}
