import {
  afterAll,
  beforeAll,
  describe,
  expect,
  it,
} from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/*
  Unit tests for the bridge.ts long-lived-worker manager, driven by a FAKE worker
  (platform/test/fixtures/fake-worker.ts) — no real Python worker, no LLM calls.

  ISOLATION: server.test.ts boots a REAL worker through the canonical bridge
  module singleton, and Bun shares module state across files in one process. To
  avoid colliding with it, we import a FRESH, cache-busted bridge instance (same
  trick auth.startup.test.ts uses) with its OWN socket server + singleton state,
  pointed at a temp socket path. The fake worker is spawned by bridge's real
  `spawn("poetry", ...)` via a PATH shim that runs `bun fixtures/fake-worker.ts`.

  Env (APOLLO_JOB_TIMEOUT_MS etc.) is read by bridge at import time, so we set it
  BEFORE the dynamic import and restore it after, keeping the canonical module
  (whenever it loads for server.test.ts) on its defaults.
*/

type Bridge = typeof import("../src/bridge");

const FIXTURE = path.resolve(import.meta.dir, "fixtures/fake-worker.ts");

// A fresh bridge instance with its own singleton state, its own temp socket, and
// a PATH-shimmed `poetry` that launches the fake worker. Returns a teardown fn.
async function makeBridge(opts: {
  jobTimeoutMs?: number;
  readyTimeoutMs?: number;
  maxQueue?: number;
  crashOnBoot?: boolean;
} = {}): Promise<{ bridge: Bridge; teardown: () => Promise<void> }> {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "apollo-worker-test-"));
  const shimDir = path.join(tmpRoot, "bin");
  fs.mkdirSync(shimDir, { recursive: true });
  const socket = path.join(tmpRoot, "apollo.sock");

  // A `poetry` shim: bridge runs `spawn("poetry", ["run","python",...])`; the
  // shim ignores those args and launches the fake worker under this Bun binary.
  const shim = path.join(shimDir, "poetry");
  fs.writeFileSync(shim, `#!/bin/sh\nexec "${process.execPath}" "${FIXTURE}"\n`);
  fs.chmodSync(shim, 0o755);

  const saved: Record<string, string | undefined> = {
    PATH: process.env.PATH,
    APOLLO_SOCKET_PATH: process.env.APOLLO_SOCKET_PATH,
    APOLLO_JOB_TIMEOUT_MS: process.env.APOLLO_JOB_TIMEOUT_MS,
    APOLLO_READY_TIMEOUT_MS: process.env.APOLLO_READY_TIMEOUT_MS,
    APOLLO_MAX_QUEUE: process.env.APOLLO_MAX_QUEUE,
    FAKE_CRASH_ON_BOOT: process.env.FAKE_CRASH_ON_BOOT,
  };

  process.env.PATH = `${shimDir}:${process.env.PATH}`;
  process.env.APOLLO_SOCKET_PATH = socket;
  process.env.APOLLO_JOB_TIMEOUT_MS = String(opts.jobTimeoutMs ?? 1500);
  process.env.APOLLO_READY_TIMEOUT_MS = String(opts.readyTimeoutMs ?? 4000);
  process.env.APOLLO_MAX_QUEUE = String(opts.maxQueue ?? 100);
  if (opts.crashOnBoot) process.env.FAKE_CRASH_ON_BOOT = "1";
  else delete process.env.FAKE_CRASH_ON_BOOT;

  // Fresh, isolated bridge module (own singleton state).
  const bridge: Bridge = await import(
    `../src/bridge?bust=${Date.now()}_${Math.random()}`
  );
  await bridge.startWorker();

  const teardown = async () => {
    try {
      await bridge.stopWorker();
    } catch {}
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
    try {
      fs.rmSync(tmpRoot, { recursive: true, force: true });
    } catch {}
  };

  return { bridge, teardown };
}

describe("bridge worker manager (fake worker)", () => {
  let bridge: Bridge;
  let teardown: () => Promise<void>;

  beforeAll(async () => {
    ({ bridge, teardown } = await makeBridge());
  });

  afterAll(async () => {
    await teardown();
  });

  describe("handshake + terminal resolution", () => {
    it("awaits the ready handshake and resolves END result as-is", async () => {
      // run() gates on the ready handshake; the fake worker sends it on connect.
      const result = await bridge.run("fake", 0, {
        mode: "end",
        result: { hello: "world", n: 42 },
      });
      expect(result).toEqual({ hello: "world", n: 42 });
    });

    it("resolves an ERROR frame as an ApolloError-shaped value with code/type/message/details", async () => {
      // Regression C fixed: details must survive the ERROR -> resolved-value hop.
      const result = await bridge.run("fake", 0, {
        mode: "error",
        code: 429,
        error_type: "RATE_LIMIT",
        message: "slow down",
        details: { retry_after: 60 },
      });
      expect(result).toEqual({
        code: 429,
        type: "RATE_LIMIT",
        message: "slow down",
        details: { retry_after: 60 },
      });
    });

    it("defaults an ERROR with missing fields to 500/INTERNAL_ERROR", async () => {
      const result = await bridge.run("fake", 0, { mode: "error" });
      expect(result.code).toBe(500);
      expect(result.type).toBe("INTERNAL_ERROR");
      expect(typeof result.message).toBe("string");
      expect(result.details).toBeUndefined();
    });
  });

  describe("event routing", () => {
    it("forwards LOG to onLog as the exact level:source:message string", async () => {
      const logs: string[] = [];
      const result = await bridge.run(
        "fake",
        0,
        {
          mode: "log_then_end",
          level: "INFO",
          source: "echo",
          message: "Echoing request",
          result: { done: true },
        },
        (s) => logs.push(s)
      );
      expect(logs).toEqual(["INFO:echo:Echoing request"]);
      expect(result).toEqual({ done: true });
    });

    it("forwards EVENT to onEvent(event, data)", async () => {
      const events: Array<[string, any]> = [];
      await bridge.run(
        "fake",
        0,
        { mode: "event", event: "content_block_delta", data: { index: 1 } },
        undefined,
        (type, payload) => events.push([type, payload])
      );
      expect(events).toContainEqual(["content_block_delta", { index: 1 }]);
    });

    it("forwards STATUS to onEvent('status', data)", async () => {
      const events: Array<[string, any]> = [];
      await bridge.run(
        "fake",
        0,
        { mode: "status", data: { message: "Working on it..." } },
        undefined,
        (type, payload) => events.push([type, payload])
      );
      expect(events).toContainEqual(["status", { message: "Working on it..." }]);
    });

    it("forwards ATTACHMENT to onEvent('attachment', {name, data})", async () => {
      const events: Array<[string, any]> = [];
      await bridge.run(
        "fake",
        0,
        { mode: "attachment", name: "chart.png", data: "base64==" },
        undefined,
        (type, payload) => events.push([type, payload])
      );
      expect(events).toContainEqual([
        "attachment",
        { name: "chart.png", data: "base64==" },
      ]);
    });
  });

  describe("reader / NDJSON framing / demux", () => {
    it("reassembles a message split across two socket chunks", async () => {
      const result = await bridge.run("fake", 0, {
        mode: "split_end",
        result: { split: true },
      });
      expect(result).toEqual({ split: true });
    });

    it("splits two messages delivered in one chunk (LOG + END)", async () => {
      const logs: string[] = [];
      const result = await bridge.run(
        "fake",
        0,
        {
          mode: "log_then_end",
          level: "WARN",
          source: "svc",
          message: "one chunk",
          result: { ok: 1 },
        },
        (s) => logs.push(s)
      );
      expect(logs).toEqual(["WARN:svc:one chunk"]);
      expect(result).toEqual({ ok: 1 });
    });

    it("skips a malformed (non-JSON) line without hanging the job or others", async () => {
      // The malformed job still completes, AND a concurrent normal job is not
      // stalled by the bad line — proving the reader loop survived it.
      const [bad, good] = await Promise.all([
        bridge.run("fake", 0, { mode: "malformed_then_end", result: { id: 1 } }),
        bridge.run("fake", 0, { mode: "end", result: { id: 2 } }),
      ]);
      expect(bad).toEqual({ id: 1 });
      expect(good).toEqual({ id: 2 });
    });

    it("drops a frame for an unknown/already-completed job_id", async () => {
      // The worker emits an END for a bogus job_id before the real one; the
      // bogus is dropped and the real job resolves normally.
      const result = await bridge.run("fake", 0, {
        mode: "unknown_then_end",
        result: { real: true },
      });
      expect(result).toEqual({ real: true });
    });

    it("multiplexes several concurrent jobs to distinct results", async () => {
      const results = await Promise.all(
        Array.from({ length: 8 }, (_, i) =>
          bridge.run("fake", 0, { mode: "end", result: { i } })
        )
      );
      expect(results).toEqual(Array.from({ length: 8 }, (_, i) => ({ i })));
    });
  });

  describe("per-job timeout", () => {
    it("resolves a 504 ApolloError when the worker never replies", async () => {
      // jobTimeoutMs is 1500 for this bridge; the fake sends nothing.
      const result = await bridge.run("fake", 0, { mode: "noreply" });
      expect(result).toEqual({
        code: 504,
        type: "TIMEOUT",
        message: "Job timed out",
      });
    }, 6000);
  });

  describe("crash + restart", () => {
    it("fails in-flight jobs with 500 on worker exit, then restarts and serves new jobs", async () => {
      // Crash while a job is pending -> that job resolves a scrubbed 500.
      const crashed = await bridge.run("fake", 0, { mode: "crash" });
      expect(crashed.code).toBe(500);
      expect(crashed.type).toBe("INTERNAL_ERROR");

      // The worker restarts (backoff) and re-handshakes; a subsequent job awaits
      // readiness (the queue/await path) and then succeeds — proving the pending
      // map was cleared and the restart path re-armed readiness.
      const after = await bridge.run("fake", 0, {
        mode: "end",
        result: { recovered: true },
      });
      expect(after).toEqual({ recovered: true });
    }, 15000);
  });
});

// NOTE — circuit-breaker trip is deliberately NOT driven live here. Tripping it
// requires K=5 consecutive crash-near-startup exits (backoff is a fixed 1s..cap in
// bridge, ~15s wall clock), and at the trip bridge calls
// `rejectReady(new Error("worker circuit open"))` on a workerReady promise it
// created in the SAME synchronous tick — so nothing can ever be awaiting it
// (run() short-circuits on `circuitOpen` instead). That rejection is therefore
// always unattached, and Bun's test runner fails any test that observes an
// unhandled rejection regardless of a process listener. So a live trip test can't
// be made green without a production change. The restart/backoff path up to the
// breaker is covered by the crash+restart test above; the trip itself is verified
// by code-trace + Agent A/C. See agentE-report.md (flagged as a possible minor
// bridge robustness fix: attach a no-op .catch in resetReady()).
