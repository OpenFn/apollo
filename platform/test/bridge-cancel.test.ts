import { describe, expect, it } from "bun:test";

import { run } from "../src/bridge";
import { ApolloThrowable } from "../src/util/errors";

const PORT = 9871;

// The spawned command is `poetry run python ...`, so matching the process list
// alone hits the poetry wrapper seconds before the interpreter exists. The probe
// announces itself once python is really inside the service.
const started = () => {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });

  return {
    promise,
    onEvent: (type: string) => {
      if (type === "probe_started") {
        resolve();
      }
    },
  };
};

// No `pgrep -c`: BSD pgrep has no count flag, and its usage error goes to
// stderr, so asking for one reads as "no processes".
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
    if ((await probeProcessCount()) === 0) {
      return true;
    }
    await Bun.sleep(200);
  }
  return false;
};

describe("cancelling a service run", () => {
  it("kills the running python child when the caller aborts", async () => {
    const abort = new AbortController();
    const probe = started();

    const pending = run(
      "_cancel_probe",
      PORT,
      { sleep_for: 120 },
      undefined,
      probe.onEvent,
      abort.signal
    );

    await probe.promise;
    expect(await probeProcessCount()).toBeGreaterThan(0);

    abort.abort();

    const error = (await pending.catch((e) => e)) as ApolloThrowable;
    expect(error).toBeInstanceOf(ApolloThrowable);
    expect(error.type).toBe("SUBPROCESS_CANCELLED");
    expect(error.code).toBe(499);

    expect(await waitForProbesToClear()).toBe(true);
  }, 90_000);

  it("does not leave a child running when the signal is already aborted", async () => {
    const abort = new AbortController();
    abort.abort();

    const error = (await run(
      "_cancel_probe",
      PORT,
      { sleep_for: 120 },
      undefined,
      undefined,
      abort.signal
    ).catch((e) => e)) as ApolloThrowable;

    expect(error.type).toBe("SUBPROCESS_CANCELLED");
    expect(await waitForProbesToClear()).toBe(true);
  }, 90_000);
});
