import { describe, expect, it, spyOn } from "bun:test";

import {
  activeCount,
  enqueue,
  maxConcurrency,
  queueDepth,
  queueTimeoutMs,
  QueueTimeoutError,
} from "../../src/util/python-queue";
import * as sentry from "../../src/util/sentry";

// A task that stays running until `release()` is called, so a test can hold
// a slot open for as long as it likes.
const holdable = () => {
  let release!: () => void;
  const task = () =>
    new Promise<void>((resolve) => {
      release = resolve;
    });
  return { task, release: () => release() };
};

// Each test drives the module-level counters up and lets everything it
// enqueues finish (or cancels it), so the singleton returns to baseline and
// tests don't leak into each other - including bridge.ts's own use of the
// same module elsewhere in the suite.
describe("python-queue", () => {
  it("runs a task immediately while under the cap", async () => {
    process.env.APOLLO_CONCURRENCY = "2";
    try {
      const before = activeCount();
      const holder = holdable();
      const { promise } = enqueue("test", holder.task);
      // Granted synchronously - active bumps before anything is awaited.
      expect(activeCount()).toBe(before + 1);
      holder.release();
      await promise;
      expect(activeCount()).toBe(before);
    } finally {
      delete process.env.APOLLO_CONCURRENCY;
    }
  });

  it("queues past the cap and runs in FIFO order", async () => {
    process.env.APOLLO_CONCURRENCY = "1";
    try {
      const first = holdable();
      enqueue("first", first.task);
      expect(activeCount()).toBe(1);

      const order: string[] = [];
      const second = enqueue("second", async () => {
        order.push("second");
      });
      const third = enqueue("third", async () => {
        order.push("third");
      });

      // Neither can have run yet - the only slot is held by "first".
      await Bun.sleep(10);
      expect(order).toEqual([]);
      expect(queueDepth()).toBe(2);

      first.release(); // frees "first"'s slot - "second" then "third" cascade
      // through on the same slot, since neither holds it open.
      await third.promise;
      expect(order).toEqual(["second", "third"]);
      expect(queueDepth()).toBe(0);

      expect(activeCount()).toBe(0);
    } finally {
      delete process.env.APOLLO_CONCURRENCY;
    }
  });

  it("cancels a queued task without ever running it, and without consuming a slot", async () => {
    process.env.APOLLO_CONCURRENCY = "1";
    try {
      const holder = holdable();
      enqueue("holder", holder.task);
      expect(activeCount()).toBe(1);

      let ran = false;
      const { promise, cancel } = enqueue("waiter", async () => {
        ran = true;
      });
      expect(queueDepth()).toBe(1);

      cancel();
      await expect(promise).rejects.toBeTruthy();

      // The cancel dropped it from the line - it must not sit there forever
      // waiting for a slot that will now never come looking for it.
      expect(queueDepth()).toBe(0);
      // Still 1: the held slot was never touched by the cancelled waiter.
      expect(activeCount()).toBe(1);
      expect(ran).toBe(false);

      holder.release();
      await Bun.sleep(5);
      expect(activeCount()).toBe(0);
    } finally {
      delete process.env.APOLLO_CONCURRENCY;
    }
  });

  it("treats cancelling an already-started task as a no-op", async () => {
    process.env.APOLLO_CONCURRENCY = "1";
    try {
      const { promise, cancel } = enqueue("immediate", async () => "done");
      cancel(); // already running - nothing left to cancel
      await expect(promise).resolves.toBe("done");
      expect(activeCount()).toBe(0);
    } finally {
      delete process.env.APOLLO_CONCURRENCY;
    }
  });

  it("drops a cancelled middle waiter without disturbing the others", async () => {
    process.env.APOLLO_CONCURRENCY = "1";
    try {
      const holder = holdable();
      enqueue("holder", holder.task);

      const order: string[] = [];
      const first = enqueue("first", async () => {
        order.push("first");
      });
      const middle = enqueue("middle", async () => {
        order.push("middle");
      });
      const last = enqueue("last", async () => {
        order.push("last");
      });
      expect(queueDepth()).toBe(3);

      middle.cancel();
      await expect(middle.promise).rejects.toBeTruthy();
      expect(queueDepth()).toBe(2); // only the cancelled one left the line

      holder.release(); // "holder" done - "first" is still at the front
      await first.promise;
      await last.promise; // "middle" is gone, so "last" is next

      expect(order).toEqual(["first", "last"]);
      expect(activeCount()).toBe(0);
    } finally {
      delete process.env.APOLLO_CONCURRENCY;
    }
  });

  it("never exceeds the cap under concurrent load, and admits everyone eventually", async () => {
    process.env.APOLLO_CONCURRENCY = "2";
    try {
      let observedPeak = 0;
      let completed = 0;
      const total = 6;

      const runs = Array.from({ length: total }, (_, i) =>
        enqueue(`req-${i}`, async () => {
          observedPeak = Math.max(observedPeak, activeCount());
          await Bun.sleep(5); // hold the slot briefly so others really do queue
          completed++;
        })
      );

      await Promise.all(runs.map((r) => r.promise));

      expect(completed).toBe(total);
      expect(observedPeak).toBeLessThanOrEqual(2);
      expect(observedPeak).toBeGreaterThan(0);
      expect(activeCount()).toBe(0);
      expect(queueDepth()).toBe(0);
    } finally {
      delete process.env.APOLLO_CONCURRENCY;
    }
  });

  it("rejects a queued task with QueueTimeoutError once it waits past the timeout, without ever running it or consuming a slot", async () => {
    process.env.APOLLO_CONCURRENCY = "1";
    process.env.APOLLO_QUEUE_TIMEOUT_MS = "20";
    try {
      const holder = holdable();
      enqueue("holder", holder.task);

      let ran = false;
      const { promise } = enqueue("waiter", async () => {
        ran = true;
      });

      await expect(promise).rejects.toBeInstanceOf(QueueTimeoutError);
      expect(queueDepth()).toBe(0);
      expect(activeCount()).toBe(1); // holder's slot is untouched
      expect(ran).toBe(false);

      holder.release();
      await Bun.sleep(5);
      expect(activeCount()).toBe(0);
    } finally {
      delete process.env.APOLLO_CONCURRENCY;
      delete process.env.APOLLO_QUEUE_TIMEOUT_MS;
    }
  }, 10_000);

  it("reports a Sentry message when a task is queued", async () => {
    process.env.APOLLO_CONCURRENCY = "1";
    const capture = spyOn(sentry, "captureMessage").mockImplementation(
      () => {}
    );
    try {
      const holder = holdable();
      enqueue("holder", holder.task);

      const { promise } = enqueue("waiter", async () => {});
      expect(capture).toHaveBeenCalledTimes(1);
      expect(String(capture.mock.calls[0]?.[0])).toContain("waiter");

      holder.release();
      await promise;
    } finally {
      capture.mockRestore();
      delete process.env.APOLLO_CONCURRENCY;
    }
  });

  describe("maxConcurrency", () => {
    it("falls back to the default when unset, empty, non-numeric, or zero", () => {
      for (const value of [undefined, "", "not-a-number", "0"]) {
        if (value === undefined) delete process.env.APOLLO_CONCURRENCY;
        else process.env.APOLLO_CONCURRENCY = value;

        expect(maxConcurrency()).toBe(10);
      }
      delete process.env.APOLLO_CONCURRENCY;
    });

    it("uses a configured positive integer", () => {
      process.env.APOLLO_CONCURRENCY = "3";
      try {
        expect(maxConcurrency()).toBe(3);
      } finally {
        delete process.env.APOLLO_CONCURRENCY;
      }
    });
  });

  describe("queueTimeoutMs", () => {
    it("falls back to the default when unset, empty, non-numeric, or zero", () => {
      for (const value of [undefined, "", "not-a-number", "0"]) {
        if (value === undefined) delete process.env.APOLLO_QUEUE_TIMEOUT_MS;
        else process.env.APOLLO_QUEUE_TIMEOUT_MS = value;

        expect(queueTimeoutMs()).toBe(5 * 60 * 1000);
      }
      delete process.env.APOLLO_QUEUE_TIMEOUT_MS;
    });

    it("uses a configured value", () => {
      process.env.APOLLO_QUEUE_TIMEOUT_MS = "1234";
      try {
        expect(queueTimeoutMs()).toBe(1234);
      } finally {
        delete process.env.APOLLO_QUEUE_TIMEOUT_MS;
      }
    });
  });
});
