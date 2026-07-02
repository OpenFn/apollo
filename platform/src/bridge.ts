import path from "node:path";
import os from "node:os";
import fs from "node:fs";
import { spawn, type ChildProcess } from "node:child_process";
import { timingSafeEqual } from "node:crypto";
import { getInternalToken } from "./auth/internal-token";
import type { ApolloError } from "./util/errors";
import pkg from "../../package.json";

/*
  Long-lived Python worker manager.

  Replaces the per-request `poetry run python entry.py` spawn with a single
  worker process connected to a Bun-owned Unix domain socket. Bun multiplexes
  every job over one newline-delimited-JSON stream, demuxing by job_id. `run()`
  keeps its original signature so the HTTP surface (services.ts) is unchanged;
  both END (success) and ERROR (failure) resolve into an in-band value so
  isApolloError() keeps driving the HTTP status — nothing is rejected.
*/

const JOB_TIMEOUT_MS = Number(process.env.APOLLO_JOB_TIMEOUT_MS ?? 300_000);
const READY_TIMEOUT_MS = Number(process.env.APOLLO_READY_TIMEOUT_MS ?? 10_000);
const MAX_QUEUE = Number(process.env.APOLLO_MAX_QUEUE ?? 100);
const RESTART_BACKOFF_BASE_MS = 1_000;
const RESTART_BACKOFF_CAP_MS = 30_000;
const CIRCUIT_BREAKER_THRESHOLD = 5;
const SHUTDOWN_GRACE_MS = 5_000;

const NEWLINE = 0x0a;

type JobHandler = {
  onLog?: (str: string) => void;
  onEvent?: (type: string, payload: any) => void;
  resolve: (value: any) => void;
  timer: ReturnType<typeof setTimeout>;
};

// Module singleton state — one worker per Bun process.
let socketPath = "";
let server: ReturnType<typeof Bun.listen> | null = null;
let worker: ChildProcess | null = null;
let conn: any = null;
let connBuf = Buffer.alloc(0);
let outBuf = Buffer.alloc(0); // unflushed START bytes (backpressure)
const pendingJobs = new Map<string, JobHandler>();

let workerReady: Promise<void> = Promise.resolve();
let resolveReady: () => void = () => {};
let rejectReady: (e: any) => void = () => {};
let isReady = false;
let waiters = 0;

let restartCount = 0; // consecutive crash-near-startup events
let lastSpawnTime = 0;
let circuitOpen = false;
let shuttingDown = false;

const apolloErrorValue = (
  code: number,
  type: string,
  message: string
): ApolloError => ({ code, type, message });

function resetReady() {
  isReady = false;
  workerReady = new Promise<void>((res, rej) => {
    resolveReady = res;
    rejectReady = rej;
  });
}
resetReady();

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((res, rej) => {
    const t = setTimeout(() => rej(new Error("timeout")), ms);
    p.then(
      (v) => {
        clearTimeout(t);
        res(v);
      },
      (e) => {
        clearTimeout(t);
        rej(e);
      }
    );
  });
}

function resolveSocketPath(): string {
  if (process.env.APOLLO_SOCKET_PATH) return process.env.APOLLO_SOCKET_PATH;
  const xdg = process.env.XDG_RUNTIME_DIR;
  const dir = xdg
    ? path.join(xdg, "apollo")
    : path.join(os.homedir(), ".apollo");
  return path.join(dir, "apollo.sock");
}

function ensureSocketDir(p: string) {
  const dir = path.dirname(p);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  try {
    fs.chmodSync(dir, 0o700);
  } catch {
    // best effort; a pre-existing dir owned by us is the common case
  }
}

// Before binding: if the path exists, probe it. A live answer means another
// instance owns it -> fail loudly. Refused means it's stale -> unlink. The
// 0700 parent dir (owned by us) closes the unlink->bind symlink TOCTOU.
async function clearStaleSocket(p: string): Promise<void> {
  if (!fs.existsSync(p)) return;
  let live = false;
  try {
    const probe = await Bun.connect({
      unix: p,
      socket: { data() {}, open(s) { s.end(); } },
    });
    live = true;
    try {
      probe.end();
    } catch {}
  } catch {
    live = false;
  }
  if (live) {
    throw new Error(
      `Apollo socket ${p} is already in use by another instance; set a distinct APOLLO_SOCKET_PATH`
    );
  }
  fs.unlinkSync(p);
}

const socketHandlers = {
  open(socket: any) {
    if (conn) {
      // Exactly one worker connection is accepted; extras are hung up.
      console.warn("Apollo worker socket: rejecting an extra connection");
      try {
        socket.end();
      } catch {}
      return;
    }
    conn = socket;
    connBuf = Buffer.alloc(0);
    outBuf = Buffer.alloc(0);
  },
  data(socket: any, chunk: Buffer) {
    if (socket !== conn) return;
    connBuf = connBuf.length ? Buffer.concat([connBuf, chunk]) : chunk;
    let idx: number;
    while ((idx = connBuf.indexOf(NEWLINE)) !== -1) {
      const line = connBuf.subarray(0, idx);
      connBuf = connBuf.subarray(idx + 1);
      if (line.length) handleLine(line);
    }
  },
  drain(socket: any) {
    if (socket !== conn || outBuf.length === 0) return;
    const written = socket.write(outBuf);
    outBuf = outBuf.subarray(written);
  },
  close(socket: any) {
    if (socket === conn) conn = null;
  },
  error(_socket: any, err: any) {
    console.error("Apollo worker socket error", err);
  },
};

function handleLine(line: Buffer) {
  let msg: any;
  try {
    msg = JSON.parse(line.toString("utf-8"));
  } catch {
    const preview = line.toString("utf-8").slice(0, 200);
    console.warn("Apollo worker: skipping malformed line:", preview);
    return;
  }
  try {
    dispatchMessage(msg);
  } catch (e) {
    console.warn("Apollo worker: error handling message", e);
  }
}

function validateToken(token: any): boolean {
  if (typeof token !== "string") return false;
  const a = Buffer.from(token);
  const b = Buffer.from(getInternalToken());
  return a.length === b.length && timingSafeEqual(a, b);
}

const formatLog = (msg: any): string =>
  `${msg.level}:${msg.source}:${msg.message}`;

function dispatchMessage(msg: any) {
  // Control channel (job_id null): the ready handshake.
  if (msg.job_id == null) {
    if (msg.type === "STATUS" && msg.data?.ready) {
      if (isReady) return;
      if (!validateToken(msg.token)) {
        console.warn("Apollo worker ready handshake: invalid token, ignoring");
        return;
      }
      isReady = true;
      restartCount = 0; // a clean startup resets the breaker
      resolveReady();
      console.log("Apollo worker ready");
    }
    return;
  }

  const handler = pendingJobs.get(msg.job_id);
  if (!handler) return; // unknown / already completed — drop

  switch (msg.type) {
    case "LOG":
      handler.onLog?.(formatLog(msg));
      break;
    case "EVENT":
      handler.onEvent?.(msg.event, msg.data);
      break;
    case "STATUS":
      handler.onEvent?.("status", msg.data);
      break;
    case "ATTACHMENT":
      handler.onEvent?.("attachment", { name: msg.name, data: msg.data });
      break;
    case "END":
      finishJob(msg.job_id, msg.result);
      break;
    case "ERROR":
      finishJob(msg.job_id, {
        code: msg.code ?? 500,
        type: msg.error_type ?? "INTERNAL_ERROR",
        message: msg.message ?? "Unknown error",
        ...(msg.details ? { details: msg.details } : {}),
      });
      break;
    default:
      break;
  }
}

function finishJob(jobId: string, value: any) {
  const handler = pendingJobs.get(jobId);
  if (!handler) return;
  clearTimeout(handler.timer);
  pendingJobs.delete(jobId);
  handler.resolve(value);
}

function failAllPending(code: number, type: string, message: string) {
  // Resolve (never reject) with a scrubbed error shape; handlers hold no payload,
  // so nothing sensitive is logged here.
  for (const handler of pendingJobs.values()) {
    clearTimeout(handler.timer);
    handler.resolve(apolloErrorValue(code, type, message));
  }
  pendingJobs.clear();
}

// Serialize START writes; buffer whatever the socket can't take now and flush on
// drain. The worker's own single writer thread guarantees inbound framing.
function writeToWorker(line: string): boolean {
  if (!conn) return false;
  const data = Buffer.from(line, "utf-8");
  if (outBuf.length) {
    outBuf = Buffer.concat([outBuf, data]);
    return true;
  }
  try {
    const written = conn.write(data);
    if (written < data.length) outBuf = data.subarray(written);
    return true;
  } catch {
    return false;
  }
}

function spawnWorker() {
  if (shuttingDown || circuitOpen) return;
  lastSpawnTime = Date.now();
  worker = spawn("poetry", ["run", "python", "services/worker.py"], {
    // Same env the per-request spawn injected, so apollo() self-calls keep
    // authenticating; plus the socket path. getInternalToken() is per-process
    // stable, so restarts re-inject the same token (handshake + self-call auth).
    env: {
      ...process.env,
      APOLLO_INTERNAL_TOKEN: getInternalToken(),
      APOLLO_VERSION: pkg.version,
      APOLLO_SOCKET_PATH: socketPath,
    },
    stdio: ["ignore", "inherit", "inherit"],
  });
  worker.on("error", (err) => {
    console.error("Apollo worker spawn error", err);
  });
  worker.on("exit", onWorkerExit);
}

function onWorkerExit(code: number | null, signal: NodeJS.Signals | null) {
  if (shuttingDown) return;
  console.error(
    `Apollo worker exited (code=${code}, signal=${signal}); failing ${pendingJobs.size} in-flight job(s)`
  );
  worker = null;
  conn = null;
  connBuf = Buffer.alloc(0);
  outBuf = Buffer.alloc(0);

  failAllPending(500, "INTERNAL_ERROR", "Apollo worker crashed");
  resetReady();

  restartCount++;
  if (restartCount >= CIRCUIT_BREAKER_THRESHOLD) {
    circuitOpen = true;
    console.error(
      `Apollo worker crash loop: circuit breaker tripped after ${restartCount} crashes; serving 503`
    );
    rejectReady(new Error("worker circuit open"));
    return;
  }

  const backoff = Math.min(
    RESTART_BACKOFF_BASE_MS * 2 ** (restartCount - 1),
    RESTART_BACKOFF_CAP_MS
  );
  console.log(
    `Apollo worker restarting in ${backoff}ms (attempt ${restartCount})`
  );
  setTimeout(() => {
    if (!shuttingDown && !circuitOpen) spawnWorker();
  }, backoff);
}

/** Boot the worker: create/own the socket, then spawn the child. Idempotent. */
export async function startWorker(): Promise<void> {
  if (server || worker) return;
  socketPath = resolveSocketPath();
  ensureSocketDir(socketPath);
  await clearStaleSocket(socketPath);

  const prevUmask = process.umask(0o077);
  try {
    server = Bun.listen({ unix: socketPath, socket: socketHandlers });
  } finally {
    process.umask(prevUmask);
  }
  try {
    fs.chmodSync(socketPath, 0o600);
  } catch (e) {
    console.warn("Apollo worker socket: could not chmod 0600", e);
  }

  // Best-effort orphan kill if Bun exits without running the async shutdown.
  process.on("exit", () => {
    if (worker) {
      try {
        worker.kill("SIGKILL");
      } catch {}
    }
  });

  spawnWorker();
}

/** Stop the worker and release the socket (called from the server shutdown). */
export async function stopWorker(): Promise<void> {
  shuttingDown = true;
  const w = worker;
  if (w) {
    w.kill("SIGTERM");
    await new Promise<void>((res) => {
      const t = setTimeout(() => {
        try {
          w.kill("SIGKILL");
        } catch {}
        res();
      }, SHUTDOWN_GRACE_MS);
      w.on("exit", () => {
        clearTimeout(t);
        res();
      });
    });
  }
  try {
    server?.stop();
  } catch {}
  try {
    if (socketPath && fs.existsSync(socketPath)) fs.unlinkSync(socketPath);
  } catch {}
}

/**
  Run a python service on the long-lived worker.

  Signature unchanged from the per-request model. Resolves (never rejects) with
  either the service result (END) or an ApolloError-shaped value (ERROR / timeout
  / worker-down), so services.ts's isApolloError() drives the HTTP status.
*/
export const run = async (
  scriptName: string,
  port: number, // needed for self-calling services in pythonland
  args: any = {},
  onLog?: (str: string) => void,
  onEvent?: (type: string, payload: any /* string or json tbh */) => void
): Promise<any> => {
  if (circuitOpen) {
    return apolloErrorValue(
      503,
      "SERVICE_UNAVAILABLE",
      "Apollo worker is unavailable"
    );
  }

  if (!isReady) {
    if (waiters >= MAX_QUEUE) {
      return apolloErrorValue(
        503,
        "SERVICE_UNAVAILABLE",
        "Apollo worker queue is full"
      );
    }
    waiters++;
    try {
      await withTimeout(workerReady, READY_TIMEOUT_MS);
    } catch {
      return apolloErrorValue(
        503,
        "SERVICE_UNAVAILABLE",
        "Apollo worker is not ready"
      );
    } finally {
      waiters--;
    }
  }

  const jobId = crypto.randomUUID();

  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      pendingJobs.delete(jobId);
      console.warn(`Apollo job ${jobId} timed out after ${JOB_TIMEOUT_MS}ms`);
      resolve(apolloErrorValue(504, "TIMEOUT", "Job timed out"));
    }, JOB_TIMEOUT_MS);

    pendingJobs.set(jobId, { onLog, onEvent, resolve, timer });

    // Never log the START payload: it carries the resolved api_key.
    const start = {
      type: "START",
      job_id: jobId,
      service: scriptName,
      payload: args,
      port,
    };
    const ok = writeToWorker(JSON.stringify(start) + "\n");
    if (!ok) {
      clearTimeout(timer);
      pendingJobs.delete(jobId);
      resolve(
        apolloErrorValue(503, "SERVICE_UNAVAILABLE", "Apollo worker unavailable")
      );
    }
  });
};
