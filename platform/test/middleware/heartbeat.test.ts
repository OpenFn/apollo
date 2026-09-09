import { afterEach, describe, expect, it } from "bun:test";

import {
  HEARTBEAT_FRAME,
  HEARTBEAT_INTERVAL_MS,
  heartbeatIntervalMs,
} from "../../src/middleware/services";

describe("SSE heartbeat", () => {
  // Lightning's SSE decoder matches `": " <> comment` and has no catch-all
  // clause, so ":ping" raises FunctionClauseError inside its stream fold.
  it("is a comment frame with a space after the colon", () => {
    expect(HEARTBEAT_FRAME.startsWith(": ")).toBe(true);
  });

  // Without the blank line the comment sits in the decoder's buffer and resets
  // nobody's idle timer.
  it("terminates the frame so it is dispatched rather than buffered", () => {
    expect(HEARTBEAT_FRAME.endsWith("\n\n")).toBe(true);
  });

  // An event frame would reach Lightning's handle_sse_event and need a clause.
  it("carries no event or data field", () => {
    expect(HEARTBEAT_FRAME).not.toContain("event:");
    expect(HEARTBEAT_FRAME).not.toContain("data:");
  });

  it("ticks well inside the shortest silence any hop tolerates", () => {
    expect(HEARTBEAT_INTERVAL_MS).toBeLessThanOrEqual(20_000);
    expect(HEARTBEAT_INTERVAL_MS).toBeGreaterThanOrEqual(5_000);
  });
});

describe("heartbeat interval override", () => {
  const previous = process.env.APOLLO_HEARTBEAT_INTERVAL_MS;

  afterEach(() => {
    if (previous === undefined) {
      delete process.env.APOLLO_HEARTBEAT_INTERVAL_MS;
    } else {
      process.env.APOLLO_HEARTBEAT_INTERVAL_MS = previous;
    }
  });

  const resolves = (value: string) => {
    process.env.APOLLO_HEARTBEAT_INTERVAL_MS = value;
    return heartbeatIntervalMs();
  };

  it("takes a sensible override", () => {
    expect(resolves("5000")).toBe(5000);
  });

  // setInterval treats a delay past 2^31-1 as "every tick", so the value
  // someone picks to mean "effectively never" is the one that would flood
  // every open stream.
  it("falls back rather than overflowing setInterval", () => {
    expect(resolves("3000000000")).toBe(HEARTBEAT_INTERVAL_MS);
  });

  it("falls back on zero, negatives and nonsense", () => {
    expect(resolves("0")).toBe(HEARTBEAT_INTERVAL_MS);
    expect(resolves("-1")).toBe(HEARTBEAT_INTERVAL_MS);
    expect(resolves("soon")).toBe(HEARTBEAT_INTERVAL_MS);
  });
});
