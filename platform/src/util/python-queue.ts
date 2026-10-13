const DEFAULT_MAX_CONCURRENT = 10;

export const maxConcurrentPython = (): number => {
  const configured = Number(process.env.APOLLO_MAX_CONCURRENT_PYTHON);
  return Number.isInteger(configured) && configured > 0
    ? configured
    : DEFAULT_MAX_CONCURRENT;
};

let active = 0;
const queue: (() => void)[] = [];

export const activeCount = (): number => active;
export const queueDepth = (): number => queue.length;

/** Resolves once a slot is free, in FIFO order. Rejects without consuming a
 *  slot if `signal` is already aborted, or aborts while still queued. */
export const acquireSlot = (
  scriptName: string,
  signal?: AbortSignal
): Promise<void> => {
  if (active < maxConcurrentPython()) {
    active++;
    return Promise.resolve();
  }
  if (signal?.aborted) {
    return Promise.reject(signal.reason);
  }

  console.log(
    `queueing ${scriptName}: ${active}/${maxConcurrentPython()} python processes running, ${
      queue.length + 1
    } waiting`
  );

  return new Promise<void>((resolve, reject) => {
    const grant = () => {
      active++;
      resolve();
    };
    queue.push(grant);

    signal?.addEventListener(
      "abort",
      () => {
        const i = queue.indexOf(grant);
        if (i === -1) return; // already granted - too late to cancel
        queue.splice(i, 1);
        reject(signal.reason);
      },
      { once: true }
    );
  });
};

/** Frees the slot this call's acquireSlot() granted, handing it straight to
 *  the next waiter. Call exactly once per resolved acquireSlot(). */
export const releaseSlot = (): void => {
  active--;
  queue.shift()?.();
};
