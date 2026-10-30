// `bridge.fork.ts` reads APOLLO_FORK_SERVER into a top-level `const` at
// import time, so it can only be toggled by an env var set in the shell
// *before* bun starts - not from inside a test. That also means this file
// can't share a `bun test` process with bridge-queue.test.ts or
// bridge-cancel.test.ts: whichever file bun imports "../src/bridge" from
// first freezes USE_FORK_SERVER for every file in that run. Run this one on
// its own:
//
//   OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES APOLLO_FORK_SERVER=true \
//     bun test platform/test/bridge-queue-fork.test.ts
//
// (the OBJC_DISABLE_... var is macOS-only; see .env.example)
//
// No pgrep-based process counting here, unlike bridge-queue.test.ts: a
// forked child never execs, so `ps`/`pgrep -f` only ever sees the master's
// original "entry.fork.py" command line, not the service name - there is no
// OS-level signal that distinguishes "a request is running" from "the master
// is idle". activeCount()/queueDepth() are the only reliable signal here.

import { afterEach, describe, expect, it } from "bun:test";

import { run } from "../src/bridge";
import { USE_FORK_SERVER } from "../src/bridge.fork";
import { ApolloThrowable } from "../src/util/errors";
import { activeCount, queueDepth } from "../src/util/python-queue";

const PORT = 9873;

const started = () => {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return {
    promise,
    onEvent: (type: string) => {
      if (type === "probe_started") resolve();
    },
  };
};

afterEach(() => {
  delete process.env.APOLLO_CONCURRENCY;
});

// Skips cleanly (not a failure) when run as part of the default `bun test
// platform/test` sweep, where APOLLO_FORK_SERVER is unset - see the file
// header for why this suite needs its own process to run for real.
describe.skipIf(!USE_FORK_SERVER)("queueing python runs (fork path)", () => {
  it("holds a second forked run queued until the first (over the cap) finishes", async () => {
    process.env.APOLLO_CONCURRENCY = "1";

    const firstProbe = started();
    const first = run(
      "_cancel_probe",
      PORT,
      { sleep_for: 1 },
      undefined,
      firstProbe.onEvent
    );
    await firstProbe.promise; // the fork really did start and is doing work
    expect(activeCount()).toBe(1);

    const second = run("_cancel_probe", PORT, { sleep_for: 0 });
    await Bun.sleep(200);
    // Still held by `first` - `second` is in line, not a second fork.
    expect(activeCount()).toBe(1);
    expect(queueDepth()).toBe(1);

    await first;
    await second; // released straight to `second`, per releaseSlot()'s contract

    expect(activeCount()).toBe(0);
    expect(queueDepth()).toBe(0);
  }, 30_000);

  it("rejects a queued forked run on abort without ever forking it", async () => {
    process.env.APOLLO_CONCURRENCY = "1";

    const holderProbe = started();
    const holder = run(
      "_cancel_probe",
      PORT,
      { sleep_for: 2 },
      undefined,
      holderProbe.onEvent
    );
    await holderProbe.promise;
    expect(activeCount()).toBe(1);

    const abort = new AbortController();
    const queued = run(
      "_cancel_probe",
      PORT,
      { sleep_for: 0 },
      undefined,
      undefined,
      abort.signal
    );
    // run() awaits writing its tmp files before it ever reaches
    // acquireSlot() - give that a tick before checking it actually queued.
    await Bun.sleep(50);
    expect(queueDepth()).toBe(1);

    abort.abort();
    const error = (await queued.catch((e) => e)) as ApolloThrowable;
    expect(error).toBeInstanceOf(ApolloThrowable);
    expect(error.type).toBe("SUBPROCESS_CANCELLED");

    // The cancelled wait never became a fork - the slot is still only
    // `holder`'s.
    expect(queueDepth()).toBe(0);
    expect(activeCount()).toBe(1);

    await holder;
    expect(activeCount()).toBe(0);
  }, 30_000);
});
