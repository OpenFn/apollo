import readline from "node:readline";
import net from "node:net";
import path from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { chmod, rm } from "node:fs/promises";
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

// A line a service logged on purpose, as opposed to whatever else lands on a
// stream. Only these are forwarded to the caller.
const LOG_LINE = /^(INFO|DEBUG|ERROR|WARNING):/;

const USE_FORK_SERVER = ["1", "true", "yes"].includes(
  (process.env.APOLLO_FORK_SERVER ?? "").toLowerCase()
);

interface ForkMaster {
  proc: ChildProcess;
  socketPath: string;
}
let forkMaster: Promise<ForkMaster> | null = null;
let forkMasterProc: ChildProcess | null = null;

function startForkMaster(): Promise<ForkMaster> {
  const socketPath = path.resolve(`tmp/fork_server-${process.pid}.sock`);
  const proc = spawn(
    "poetry",
    ["run", "python", "services/fork_server.py", "--socket", socketPath],
    {
      env: {
        ...process.env,
        APOLLO_INTERNAL_TOKEN: getInternalToken(),
        APOLLO_VERSION: pkg.version,
        OBJC_DISABLE_INITIALIZE_FORK_SAFETY: "YES",
      },
    }
  );
  forkMasterProc = proc;

  return new Promise<ForkMaster>((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(subprocessSpawnFailed("fork_server", new Error("not READY in time"))),
      60_000
    );
    readline.createInterface({ input: proc.stdout!, crlfDelay: Infinity }).on("line", (line) => {
      console.log(`fork-server: ${line}`);
      if (line.startsWith("READY")) {
        clearTimeout(timeout);
        resolve({ proc, socketPath });
      }
    });
    readline
      .createInterface({ input: proc.stderr!, crlfDelay: Infinity })
      .on("line", (line) => console.error(`fork-server: ${line}`));

    proc.on("error", (err) => {
      clearTimeout(timeout);
      reject(subprocessSpawnFailed("fork_server", err));
    });
    proc.on("exit", (code, sig) => {
      clearTimeout(timeout);
      console.error(`fork-server exited (code=${code} signal=${sig})`);
      forkMaster = null; // next request starts a fresh master
      forkMasterProc = null;
      rm(socketPath).catch(() => {});
    });
  });
}

function getForkMaster(): Promise<ForkMaster> {
  if (!forkMaster) {
    forkMaster = startForkMaster().catch((err) => {
      forkMaster = null;
      throw err;
    });
  }
  return forkMaster;
}

process.once("exit", () => forkMasterProc?.kill("SIGTERM"));

function runForked(
  scriptName: string,
  port: number,
  inputPath: string,
  outputPath: string,
  onLog?: (str: string) => void,
  onEvent?: (type: string, payload: any) => void,
  signal?: AbortSignal
): Promise<JSON | null> {
  return getForkMaster().then(
    (master) =>
      new Promise<JSON | null>((resolve, reject) => {
        let childPid: number | null = null;
        let exitCode: number | null = null;
        let cancelled = false;
        let hardKill: ReturnType<typeof setTimeout> | undefined;

        const cleanupFiles = async () => {
          try {
            await rm(inputPath);
            await rm(outputPath);
          } catch (e) {
            console.error("Error removing temporary files");
            console.error(e);
          }
        };

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

        const conn = net.createConnection({ path: master.socketPath });
        conn.on("connect", () => {
          conn.write(
            JSON.stringify({ service: scriptName, input: inputPath, output: outputPath, port }) + "\n"
          );
        });

        // The child's stream: the service's own stdout, wrapped in PID:/EXIT:.
        const rl = readline.createInterface({ input: conn, crlfDelay: Infinity });
        rl.on("line", (line) => {
          if (line.startsWith("PID:")) {
            childPid = Number(line.slice(4)) || null;
            if (cancelled) killChild();
          } else if (line.startsWith("EXIT:")) {
            exitCode = Number(line.slice(5));
          } else if (LOG_LINE.test(line)) {
            console.log(line);
            onLog?.(line);
          } else if (/^(EVENT)\:/.test(line)) {
            const [_prefix, type, ...payload] = line.split(":");
            let processedPayload: any = payload.join(":");
            try {
              processedPayload = JSON.parse(processedPayload);
            } catch (e) {
              // No json, no problem
            }
            onEvent?.(type, processedPayload);
          }
        });

        if (signal) {
          if (signal.aborted) onAbort();
          else signal.addEventListener("abort", onAbort, { once: true });
        }

        conn.on("error", async (err) => {
          if (hardKill) clearTimeout(hardKill);
          signal?.removeEventListener("abort", onAbort);
          await cleanupFiles();
          reject(subprocessSpawnFailed(scriptName, err));
        });

        conn.on("close", async () => {
          rl.close();
          if (hardKill) clearTimeout(hardKill);
          signal?.removeEventListener("abort", onAbort);

          const text = await Bun.file(outputPath)
            .text()
            .catch(() => "");
          await cleanupFiles();

          if (cancelled) return reject(subprocessCancelled(scriptName, "SIGTERM"));
          if (exitCode && exitCode !== 0) return reject(subprocessFailed(scriptName, exitCode));
          // No EXIT line => the child died mid-flight (crash/OOM/signal).
          if (exitCode === null) return reject(subprocessKilled(scriptName, "UNKNOWN"));
          if (text) {
            try {
              return resolve(JSON.parse(text));
            } catch (e) {
              console.error(`Unreadable output from ${scriptName}`);
              console.error(e);
              return reject(malformedResult(scriptName));
            }
          }
          console.warn("No data returned from pythonland");
          return reject(emptyResult(scriptName));
        });
      }),
    async (err) => {
      await rm(inputPath).catch(() => {});
      await rm(outputPath).catch(() => {});
      throw err;
    }
  );
}

/**
  Run a python script
  Each script will be run in its own thread because
  1) It saves script writers having to worry about long writing process
  2) Removes any risk of stale credentials and ensures a pristine environment
  3) it makes capturing logs a bit easier
*/
export const run = async (
  scriptName: string,
  port: number, // needed for self-calling services in pythonland
  args: any = {},
  onLog?: (str: string) => void,
  onEvent?: (type: string, payload: any /* string or json tbh */) => void,
  // Aborted when the client goes away
  signal?: AbortSignal
) => {
  const id = crypto.randomUUID();

  const tmpfile = path.resolve(`tmp/data/${id}-{}.json`);

  const inputPath = tmpfile.replace("{}", "input");
  const outputPath = tmpfile.replace("{}", "output");

  // Outside the promise, deliberately. The Promise constructor only catches a
  // synchronous throw from its executor, so an await that rejects in there -
  // a full disk, a read-only tmp - leaves the promise pending for ever and
  // the caller's stream open. Out here, run() is async and simply rejects.
  try {
    await Bun.write(inputPath, JSON.stringify(args));

    // The payload can hold values that belong to the deployment rather than
    // the caller, and only the close handler removes this file - so a process
    // that dies first leaves one behind.
    await chmod(inputPath, 0o600);

    await Bun.write(outputPath, "");
  } catch (error) {
    // Removed rather than left behind by a half-finished setup, for the same
    // reason it is 0600 above.
    await rm(inputPath).catch(() => {});
    await rm(outputPath).catch(() => {});
    throw subprocessSpawnFailed(scriptName, error);
  }

  if (USE_FORK_SERVER) {
    return runForked(scriptName, port, inputPath, outputPath, onLog, onEvent, signal);
  }

  return new Promise<JSON | null>((resolve, reject) => {
    const proc = spawn(
      "poetry",
      [
        "run",
        "python",
        "services/entry.py",
        scriptName,
        ...(inputPath ? ["--input", inputPath] : []),
        ...(outputPath ? ["--output", outputPath] : []),
        ...(port ? ["--port", `${port}`] : []),
      ],
      // Hand the internal token to the child explicitly so its apollo() self-calls
      // are recognised by the auth hook. Spawned from here (the honest owner) rather than
      // written back onto this process's env.
      {
        env: {
          ...process.env,
          APOLLO_INTERNAL_TOKEN: getInternalToken(),
          APOLLO_VERSION: pkg.version,
        },
      }
    );

    // Nothing was spawned, so no "close" is coming - without settling here the
    // request stays open until something upstream gives up
    proc.on("error", (err) => {
      console.error("Failed to start python process", err);
      reject(subprocessSpawnFailed(scriptName, err));
    });

    // `poetry run` execs into python rather than forking it, so this pid is the
    // interpreter and a plain signal reaches it. Killing it closes the socket to
    // Anthropic, which stops generation on the streaming calls; a non-streaming
    // call is already submitted and gets billed whatever we do here.
    let cancelled = false;
    let hardKill: ReturnType<typeof setTimeout> | undefined;

    const onAbort = () => {
      cancelled = true;
      console.warn(`cancelling ${scriptName}: client went away`);
      proc.kill("SIGTERM");

      // Python installs no SIGTERM handler, so termination is immediate. This
      // is only for a child wedged somewhere that never sees it.
      hardKill = setTimeout(() => proc.kill("SIGKILL"), 5_000);
      hardKill.unref?.();
    };

    if (signal) {
      if (signal.aborted) {
        onAbort();
      } else {
        signal.addEventListener("abort", onAbort, { once: true });
      }
    }

    const rl = readline.createInterface({
      input: proc.stdout,
      crlfDelay: Infinity,
    });
    rl.on("line", (line) => {
      // Then divert any logs from a logger object to the websocket
      if (LOG_LINE.test(line)) {
        // Divert the log line locally
        console.log(line);
        // TODO I'd love to break the log line up in to JSON actually
        // { source, level, message }
        onLog?.(line);
      } else if (/^(EVENT)\:/.test(line)) {
        // TODO does the event encoding need to be any more complex than this?
        // Nice that it stays human readable
        const [_prefix, type, ...payload] = line.split(":");
        let processedPayload = payload.join(":");
        try {
          processedPayload = JSON.parse(processedPayload);
        } catch (e) {
          // No json, no problem
        }
        onEvent?.(type, processedPayload);
      }
    });

    const rl2 = readline.createInterface({
      input: proc.stderr,
      crlfDelay: Infinity,
    });
    rl2.on("line", (line) => {
      console.error(line);

      // Only forward what a service logged deliberately, the same rule stdout
      // follows. Everything else on stderr is the interpreter talking: raw
      // tracebacks carrying server paths, source lines, and whatever a frame
      // held - which for a service is the payload.
      if (LOG_LINE.test(line)) {
        onLog?.(line);
      }
    });

    proc.on("close", async (code, closeSignal) => {
      // Clean up readline interfaces immediately to prevent race conditions
      rl.close();
      rl2.close();

      if (hardKill) {
        clearTimeout(hardKill);
      }
      signal?.removeEventListener("abort", onAbort);

      // Read before cleaning up, and clean up on every exit path
      const text = await Bun.file(outputPath)
        .text()
        .catch(() => "");

      try {
        await rm(inputPath);
        await rm(outputPath);
      } catch (e) {
        console.error("Error removing temporary files");
        console.error(e);
      }

      // We killed it on purpose, so this is not a service failure
      if (cancelled) {
        return reject(subprocessCancelled(scriptName, closeSignal ?? "SIGTERM"));
      }

      if (code) {
        console.error("Python process exited with code", code);
        return reject(subprocessFailed(scriptName, code));
      }

      // A child killed by a signal reports a null code, so without this the
      // OOM killer - the likeliest way a service dies without exiting - would
      // be reported as an empty result and the signal thrown away.
      if (closeSignal) {
        console.error(`Python process killed by ${closeSignal}`);
        return reject(subprocessKilled(scriptName, closeSignal));
      }

      if (text) {
        // Parsed inside the try: this handler is async, so a throw here
        // becomes an unhandled rejection and the run never settles at all.
        // A half-written file is what a crash mid-dump leaves behind.
        try {
          return resolve(JSON.parse(text));
        } catch (e) {
          console.error(`Unreadable output from ${scriptName}`);
          console.error(e);
          return reject(malformedResult(scriptName));
        }
      }

      // entry.py writes a result on every path it completes, including its own
      // error envelopes, so an empty file means the run died
      console.warn("No data returned from pythonland");
      return reject(emptyResult(scriptName));
    });

    return;
  });
};
