import { afterAll, describe, expect, it } from "bun:test";

import setup from "../../src/server";
import { InstanceAuth } from "../../src/auth/instance-auth";

// The bridge tests hand run() an AbortSignal directly, which proves the kill
// but not the wiring: nothing between the socket and the signal is exercised.
// That gap hid a real bug - Elysia rebuilds its ws wrapper for every callback,
// so a run keyed on the wrapper in message() was unreachable from close() and
// no websocket run was ever cancelled. This suite drives a real socket.
const port = 9874;

const auth = new InstanceAuth({ lookup: () => null, hasGlobalKey: true });
await setup(port, auth);

// No `pgrep -c`: BSD pgrep has no count flag, and its usage error goes to
// stderr, so asking for one reads as "no processes".
const childCount = async () => {
  const proc = Bun.spawn(["pgrep", "-f", "entry.py test_slow"], {
    stdout: "pipe",
    stderr: "pipe",
  });
  const out = await new Response(proc.stdout).text();
  return out.trim().split("\n").filter(Boolean).length;
};

const waitForChildrenToClear = async (limitMs = 20_000) => {
  const deadline = Date.now() + limitMs;
  while (Date.now() < deadline) {
    if ((await childCount()) === 0) {
      return true;
    }
    await Bun.sleep(250);
  }
  return false;
};

// A failed run must not leave a two-minute child holding up the suite.
afterAll(() => {
  Bun.spawnSync(["pkill", "-f", "entry.py test_slow"]);
});

describe("cancelling over a real websocket", () => {
  it("kills the python child when the socket closes", async () => {
    const socket = new WebSocket(`ws://localhost:${port}/services/test_slow`);

    // The service announces itself on stdout once the interpreter is truly
    // inside main(); matching the process list any earlier hits the poetry
    // wrapper and proves nothing.
    const started = new Promise<void>((resolve) => {
      socket.addEventListener("message", ({ data }) => {
        const evt = JSON.parse(String(data));
        if (evt.event === "event" && evt.type === "probe_started") {
          resolve();
        }
      });
    });

    socket.addEventListener("open", () => {
      socket.send(
        JSON.stringify({ event: "start", data: { sleep_for: 120 } })
      );
    });

    await started;
    expect(await childCount()).toBeGreaterThan(0);

    socket.close();

    expect(await waitForChildrenToClear()).toBe(true);
  }, 90_000);
});
