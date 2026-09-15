import { afterEach, describe, expect, it } from "bun:test";

import setup from "../../src/server";
import { InstanceAuth } from "../../src/auth/instance-auth";
import { HEARTBEAT_FRAME } from "../../src/middleware/services";

// The frame-shape tests next door pass whether or not anything ever emits one.
// These read the wire.
const port = 9871;

const auth = new InstanceAuth({ lookup: () => null, hasGlobalKey: true });
const app = await setup(port, auth);

const previous = process.env.APOLLO_HEARTBEAT_INTERVAL_MS;

afterEach(() => {
  if (previous === undefined) {
    delete process.env.APOLLO_HEARTBEAT_INTERVAL_MS;
  } else {
    process.env.APOLLO_HEARTBEAT_INTERVAL_MS = previous;
  }
});

const readStream = async (intervalMs: string) => {
  process.env.APOLLO_HEARTBEAT_INTERVAL_MS = intervalMs;

  const response = await app.handle(
    new Request(`http://localhost:${port}/services/echo/stream`, {
      method: "POST",
      body: JSON.stringify({ message: "hello" }),
      headers: { "Content-Type": "application/json" },
    })
  );

  expect(response.status).toBe(200);

  return await response.text();
};

describe("SSE heartbeat on a live stream", () => {
  // Spawning Python takes long enough that a heartbeat this fast must tick
  // before the service produces anything. The interval is deliberately set
  // rather than waited out: the real one is 15s.
  it("emits heartbeats while the service is still starting up", async () => {
    const body = await readStream("20");

    const beats = body.split(HEARTBEAT_FRAME).length - 1;

    expect(beats).toBeGreaterThan(0);
    expect(body).toContain("event: complete");
  }, 30_000);

  // Guards the ordering the whole design rests on: the first thing on the wire
  // is a heartbeat, not the result, so no hop sees an idle socket.
  it("gets a heartbeat onto the wire before the result", async () => {
    const body = await readStream("20");

    const firstBeat = body.indexOf(HEARTBEAT_FRAME);
    const result = body.indexOf("event: complete");

    // Both have to be present before comparing them: indexOf gives -1 for a
    // heartbeat that never arrived, which would sail past a bare <.
    expect(firstBeat).toBeGreaterThanOrEqual(0);
    expect(result).toBeGreaterThanOrEqual(0);
    expect(firstBeat).toBeLessThan(result);
  }, 30_000);

  it("sends none when the interval outlasts the request", async () => {
    const body = await readStream("600000");

    expect(body).not.toContain(HEARTBEAT_FRAME);
    expect(body).toContain("event: complete");
  }, 30_000);
});
