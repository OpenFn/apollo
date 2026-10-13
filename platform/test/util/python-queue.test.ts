import { describe, expect, it } from "bun:test";

import {
  acquireSlot,
  activeCount,
  queueDepth,
  releaseSlot,
} from "../../src/util/python-queue";

// Each test drives the module-level counter up and releases everything it
// acquires, so the singleton returns to baseline and tests don't leak into
// each other - including bridge.ts's own use of the same module elsewhere in
// the suite.
describe("python-queue", () => {
  it("grants a slot immediately while under the cap", async () => {
    process.env.APOLLO_MAX_CONCURRENT_PYTHON = "2";
    try {
      const before = activeCount();
      await acquireSlot("test");
      expect(activeCount()).toBe(before + 1);
      releaseSlot();
      expect(activeCount()).toBe(before);
    } finally {
      delete process.env.APOLLO_MAX_CONCURRENT_PYTHON;
    }
  });

  it("queues past the cap and releases in FIFO order", async () => {
    process.env.APOLLO_MAX_CONCURRENT_PYTHON = "1";
    try {
      await acquireSlot("first");
      expect(activeCount()).toBe(1);

      const order: string[] = [];
      const second = acquireSlot("second").then(() => order.push("second"));
      const third = acquireSlot("third").then(() => order.push("third"));

      // Neither can have been granted yet - the only slot is held by "first".
      await Bun.sleep(10);
      expect(order).toEqual([]);
      expect(queueDepth()).toBe(2);

      releaseSlot(); // frees "first"'s slot for "second"
      await second;
      expect(order).toEqual(["second"]);
      expect(queueDepth()).toBe(1);

      releaseSlot(); // frees "second"'s slot for "third"
      await third;
      expect(order).toEqual(["second", "third"]);
      expect(queueDepth()).toBe(0);

      releaseSlot(); // frees "third"'s slot
      expect(activeCount()).toBe(0);
    } finally {
      delete process.env.APOLLO_MAX_CONCURRENT_PYTHON;
    }
  });

  it("rejects a queued wait on abort, without consuming a slot", async () => {
    process.env.APOLLO_MAX_CONCURRENT_PYTHON = "1";
    try {
      await acquireSlot("holder");
      expect(activeCount()).toBe(1);

      const abort = new AbortController();
      const queued = acquireSlot("waiter", abort.signal);
      expect(queueDepth()).toBe(1);

      abort.abort();
      await expect(queued).rejects.toBeTruthy();

      // The abort removed it from the line - it must not sit there forever
      // waiting for a slot that will now never come looking for it.
      expect(queueDepth()).toBe(0);
      // Still 1: the held slot was never touched by the rejected waiter.
      expect(activeCount()).toBe(1);

      releaseSlot();
      expect(activeCount()).toBe(0);
    } finally {
      delete process.env.APOLLO_MAX_CONCURRENT_PYTHON;
    }
  });

  it("rejects immediately for an already-aborted signal when the cap is full", async () => {
    process.env.APOLLO_MAX_CONCURRENT_PYTHON = "1";
    try {
      await acquireSlot("holder");

      const abort = new AbortController();
      abort.abort();

      await expect(acquireSlot("late", abort.signal)).rejects.toBeTruthy();
      // Never entered the line - there was nothing to remove.
      expect(queueDepth()).toBe(0);

      releaseSlot();
    } finally {
      delete process.env.APOLLO_MAX_CONCURRENT_PYTHON;
    }
  });
});
