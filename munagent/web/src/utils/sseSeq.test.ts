import { describe, expect, it } from "vitest";
import { eventsAfterSeq, maxSeq } from "./sseSeq";

describe("eventsAfterSeq", () => {
  it("过滤已处理 seq", () => {
    const events = [{ seq: 1 }, { seq: 2 }, { seq: 3 }];
    expect(eventsAfterSeq(events, null)).toEqual(events);
    expect(eventsAfterSeq(events, 2)).toEqual([{ seq: 3 }]);
    expect(eventsAfterSeq(events, 3)).toEqual([]);
  });
});

describe("maxSeq", () => {
  it("取最大 seq", () => {
    expect(maxSeq([{ seq: 1 }, { seq: 5 }, { seq: 3 }])).toBe(5);
    expect(maxSeq([])).toBeNull();
  });
});
