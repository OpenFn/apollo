import { describe, expect, it } from "bun:test";

import setup from "../src/server";
import { InstanceAuth } from "../src/auth/instance-auth";

// Closing a websocket has to stop the run behind it, and the only honest way
// to check that is to look for the child in the process table. A unit test
// cannot see it: Elysia builds a fresh wrapper object per event, so the
// bookkeeping that connects `close` back to the run it should abort is exactly
// the part that broke, silently, with every other test still green.
const port = 9877;

const auth = new InstanceAuth({ lookup: () => null, hasGlobalKey: true });
await setup(port, auth);

const childCount = async () => {
  const proc = Bun.spawn(["pgrep", "-f", "entry.py echo"], {
    stdout: "pipe",
    stderr: "ignore",
  });
  const out = await new Response(proc.stdout).text();
  return out.split("\n").filter(Boolean).length;
};

const settle = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("closing a websocket", () => {
  it("stops the run behind it", async () => {
    const socket = new WebSocket(`ws://localhost:${port}/services/echo`);

    await new Promise<void>((open) =>
      socket.addEventListener("open", () => open())
    );

    socket.send(JSON.stringify({ event: "start", data: { x: 1 } }));

    // Long enough for the child to exist, short enough that it is still
    // running: spawning python through poetry takes the best part of a second.
    await settle(250);
    expect(await childCount()).toBeGreaterThan(0);

    socket.close();

    // Short: echo finishes on its own in about a second, so a longer wait
    // would see zero children whether or not closing the socket did anything.
    await settle(400);
    expect(await childCount()).toBe(0);
  }, 20_000);
});
