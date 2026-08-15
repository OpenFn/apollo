import { describe, expect, it } from "bun:test";

import {
  HEARTBEAT_FRAME,
  HEARTBEAT_INTERVAL_MS,
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
