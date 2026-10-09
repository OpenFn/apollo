import readline from "node:readline";
import net from "node:net";
import path from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { rm } from "node:fs/promises";
import { getInternalToken } from "./auth/internal-token";
import {
  emptyResult,
  malformedResult,
  subprocessCancelled,
  subprocessFailed,
  subprocessKilled,
  subprocessSpawnFailed,
} from "./util/errors";
import pkg from "../../package.json";

// Only these lines are forwarded to the caller (mirrors bridge.ts).
const LOG_LINE = /^(INFO|DEBUG|ERROR|WARNING):/;

export const USE_FORK_SERVER =
  (process.env.APOLLO_FORK_SERVER ?? "").toLowerCase() === "true";

const onLines = (stream: NodeJS.ReadableStream, fn: (line: string) => void) =>
  readline.createInterface({ input: stream, crlfDelay: Infinity }).on("line", fn);

// --- the warm master: spawned once, forks a child per request ----------------

type Master = { proc: ChildProcess; socketPath: string };
let master: Promise<Master> | null = null;
let masterProc: ChildProcess | null = null;

// Singleton; a failed start clears the slot so the next request retries.
function forkMaster(): Promise<Master> {
  return (master ??= startMaster().catch((err) => {
    master = null;
    throw err;
  }));
}

function startMaster(): Promise<Master> {
  const socketPath = path.resolve(`tmp/fork_server-${process.pid}.sock`);
  const proc = spawn(
    "poetry",
    ["run", "python", "services/entry.fork.py", "--socket", socketPath],
    {
      env: {
        ...process.env,
        APOLLO_INTERNAL_TOKEN: getInternalToken(),
        APOLLO_VERSION: pkg.version,
      },
    }
  );
  masterProc = proc;
  onLines(proc.stderr!, (line) => console.error(`fork-server: ${line}`));

  return new Promise<Master>((resolve, reject) => {
    const fail = (err: Error) => (clearTimeout(timer), reject(subprocessSpawnFailed("fork_server", err)));
    const timer = setTimeout(() => fail(new Error("not READY in time")), 60_000);

    onLines(proc.stdout!, (line) => {
      console.log(`fork-server: ${line}`);
      if (line.startsWith("READY")) {
        clearTimeout(timer);
        resolve({ proc, socketPath });
      }
    });
    proc.on("error", fail);
    proc.on("exit", (code, sig) => {
      console.error(`fork-server exited (code=${code} signal=${sig})`);
      master = masterProc = null; // next request starts a fresh one
      rm(socketPath).catch(() => {});
      fail(new Error(`fork-server exited before ready (code=${code} signal=${sig})`));
    });
  });
}

// Don't leave an orphaned master when the server process goes.
process.once("exit", () => masterProc?.kill("SIGTERM"));

// --- per-request: ask the master to fork a child, stream it back -------------

export async function runForked(
  scriptName: string,
  port: number,
  inputPath: string,
  outputPath: string,
  onLog?: (str: string) => void,
  onEvent?: (type: string, payload: any) => void,
  signal?: AbortSignal
): Promise<JSON | null> {
  const cleanup = () =>
    Promise.all([rm(inputPath).catch(() => {}), rm(outputPath).catch(() => {})]);

  let active: Master;
  try {
    active = await forkMaster();
  } catch (err) {
    await cleanup();
    throw err;
  }

  return new Promise<JSON | null>((resolve, reject) => {
    const conn = net.createConnection({ path: active.socketPath });
    let childPid: number | null = null;
    let exitCode: number | null = null;
    let cancelled = false;
    let hardKill: ReturnType<typeof setTimeout> | undefined;

    const killChild = () => {
      if (childPid == null) return; // killed once the PID: line arrives
      try {
        process.kill(childPid, "SIGTERM");
      } catch {}
      hardKill = setTimeout(() => {
        try {
          process.kill(childPid!, "SIGKILL");
        } catch {}
      }, 5_000);
      hardKill.unref?.();
    };

    const onAbort = () => {
      cancelled = true;
      console.warn(`cancelling ${scriptName}: client went away`);
      killChild();
      conn.destroy();
    };
    if (signal) {
      if (signal.aborted) onAbort();
      else signal.addEventListener("abort", onAbort, { once: true });
    }

    conn.on("connect", () =>
      conn.write(JSON.stringify({ service: scriptName, input: inputPath, output: outputPath, port }) + "\n")
    );

    // The child's stream: PID:/EXIT: control lines around the service's own stdout.
    onLines(conn, (line) => {
      if (line.startsWith("PID:")) {
        childPid = Number(line.slice(4)) || null;
        if (cancelled) killChild();
      } else if (line.startsWith("EXIT:")) {
        exitCode = Number(line.slice(5));
      } else if (LOG_LINE.test(line)) {
        console.log(line);
        onLog?.(line);
      } else if (line.startsWith("EVENT:")) {
        const [, type, ...rest] = line.split(":");
        let payload: any = rest.join(":");
        try {
          payload = JSON.parse(payload);
        } catch {
          // not json, forward the raw string
        }
        onEvent?.(type, payload);
      }
    });

    const settle = async (finish: () => void) => {
      if (hardKill) clearTimeout(hardKill);
      signal?.removeEventListener("abort", onAbort);
      await cleanup();
      finish();
    };

    conn.on("error", (err) =>
      settle(() => reject(subprocessSpawnFailed(scriptName, err)))
    );

    conn.on("close", async () => {
      const text = await Bun.file(outputPath).text().catch(() => "");
      await settle(() => {
        if (cancelled) return reject(subprocessCancelled(scriptName, "SIGTERM"));
        // No EXIT line => the child died mid-flight (crash/OOM/signal).
        if (exitCode === null) return reject(subprocessKilled(scriptName, "UNKNOWN"));
        if (exitCode !== 0) return reject(subprocessFailed(scriptName, exitCode));
        if (!text) return reject(emptyResult(scriptName));
        try {
          resolve(JSON.parse(text));
        } catch {
          reject(malformedResult(scriptName));
        }
      });
    });
  });
}
