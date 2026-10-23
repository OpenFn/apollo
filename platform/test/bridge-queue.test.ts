import { afterEach, describe, expect, it } from "bun:test";

import { run } from "../src/bridge";
import { ApolloThrowable } from "../src/util/errors";

const PORT = 9872;

// Mirrors bridge-cancel.test.ts's probe helpers: the spawned command is
// `poetry run python ...`, so matching the process list alone hits the
// poetry wrapper seconds before the interpreter exists.
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

const probeProcessCount = async () => {
  const proc = Bun.spawn(["pgrep", "-f", "_cancel_probe"], {
    stdout: "pipe",
    stderr: "pipe",
  });
  const out = await new Response(proc.stdout).text();
  return out.trim().split("\n").filter(Boolean).length;
};

const waitForProbesToClear = async (limitMs = 15_000) => {
  const deadline = Date.now() + limitMs;
  while (Date.now() < deadline) {
    if ((await probeProcessCount()) === 0) return true;
    await Bun.sleep(200);
  }
  return false;
};

afterEach(() => {
  delete process.env.APOLLO_CONCURRENCY;
});

describe("queueing python runs", () => {
  it("holds a second run queued until the first (over the cap) finishes", async () => {
    process.env.APOLLO_CONCURRENCY = "1";

    const firstProbe = started();
    const first = run(
      "_cancel_probe",
      PORT,
      { sleep_for: 2 },
      undefined,
      firstProbe.onEvent
    );
    await firstProbe.promise;

    // The cap is 1 and it's held by `first` - a second run must queue rather
    // than spawn a second interpreter on top of it.
    const second = run("_cancel_probe", PORT, { sleep_for: 0 });
    await Bun.sleep(300);
    expect(await probeProcessCount()).toBe(1);

    await first;
    // Freed now that `first` is done - `second` should get its slot and run.
    await second;

    expect(await waitForProbesToClear()).toBe(true);
  }, 30_000);

  it("rejects a queued run the moment its caller aborts, without ever spawning it", async () => {
    process.env.APOLLO_CONCURRENCY = "1";

    const holderProbe = started();
    const holder = run(
      "_cancel_probe",
      PORT,
      { sleep_for: 3 },
      undefined,
      holderProbe.onEvent
    );
    await holderProbe.promise;
    expect(await probeProcessCount()).toBe(1);

    const abort = new AbortController();
    const queued = run(
      "_cancel_probe",
      PORT,
      { sleep_for: 0 },
      undefined,
      undefined,
      abort.signal
    );

    abort.abort();
    const error = (await queued.catch((e) => e)) as ApolloThrowable;
    expect(error).toBeInstanceOf(ApolloThrowable);
    expect(error.type).toBe("SUBPROCESS_CANCELLED");

    // The cancelled queue entry never became a process - `holder` is still
    // the only one on the machine.
    expect(await probeProcessCount()).toBe(1);

    await holder; // let it finish naturally (sleep_for: 3)
    expect(await waitForProbesToClear()).toBe(true);
  }, 30_000);

  it("runs up to the cap concurrently and queues the rest, with a cap above 1", async () => {
    process.env.APOLLO_CONCURRENCY = "2";

    let startedCount = 0;
    let resolveTwoStarted!: () => void;
    const twoStarted = new Promise<void>((r) => (resolveTwoStarted = r));

    const probes = [started(), started(), started()];
    const runs = probes.map((probe) =>
      run("_cancel_probe", PORT, { sleep_for: 1 }, undefined, (type) => {
        probe.onEvent(type);
        if (type === "probe_started" && ++startedCount === 2) {
          resolveTwoStarted();
        }
      })
    );

    await twoStarted;
    await Bun.sleep(200);
    expect(await probeProcessCount()).toBe(2);

    await Promise.all(runs);
    expect(await waitForProbesToClear()).toBe(true);
  }, 30_000);
});
