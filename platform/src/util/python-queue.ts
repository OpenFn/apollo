// FIFO queue capping how many service calls bridge.ts runs at once.
// Calls past the cap wait here instead of running immediately.

import { captureMessage } from "./sentry";

const DEFAULT_CONCURRENCY = 10;

export const maxConcurrency = (): number =>
  Number(process.env.APOLLO_CONCURRENCY) || DEFAULT_CONCURRENCY;

const DEFAULT_QUEUE_TIMEOUT_MS = 5 * 60 * 1000;

export const queueTimeoutMs = (): number =>
  Number(process.env.APOLLO_QUEUE_TIMEOUT_MS) || DEFAULT_QUEUE_TIMEOUT_MS;

let active = 0;
const pending: Array<() => void> = [];

export const activeCount = (): number => active;
export const queueDepth = (): number => pending.length;

// Distinct from cancel()'s rejection, so a caller can tell "the server gave
// up" apart from "the client went away".
export class QueueTimeoutError extends Error {
  constructor() {
    super("timed out waiting in the queue");
    this.name = "QueueTimeoutError";
  }
}

export type Enqueued<T> = {
  promise: Promise<T>;
  cancel: () => void;
};

// cancel() drops a still-queued task without ever running it; calling it
// once the task has started is a no-op.
export const enqueue = <T>(
  scriptName: string,
  task: () => Promise<T>
): Enqueued<T> => {
  let removeFromQueue: ((reason: Error) => void) | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const promise = new Promise<T>((resolve, reject) => {
    const run = () => {
      if (timer) clearTimeout(timer);
      active++;
      task().then(
        (value) => {
          active--;
          pending.shift()?.();
          resolve(value);
        },
        (error) => {
          active--;
          pending.shift()?.();
          reject(error);
        }
      );
    };

    if (active < maxConcurrency()) {
      run();
      return;
    }

    console.log(
      `queueing ${scriptName}: ${active}/${maxConcurrency()} running, ${
        pending.length + 1
      } waiting`
    );
    captureMessage(`service call queued: ${scriptName}`, {
      scriptName,
      active,
      queueDepth: pending.length + 1,
    });

    pending.push(run);
    timer = setTimeout(
      () => removeFromQueue?.(new QueueTimeoutError()),
      queueTimeoutMs()
    );
    timer.unref?.();

    removeFromQueue = (reason: Error) => {
      const i = pending.indexOf(run);
      if (i === -1) return; // already started - too late to cancel
      pending.splice(i, 1);
      if (timer) clearTimeout(timer);
      reject(reason);
    };
  });

  return {
    promise,
    cancel: () => removeFromQueue?.(new Error("queue wait cancelled")),
  };
};
