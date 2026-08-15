import readline from "node:readline";
import path from "node:path";
import { spawn } from "node:child_process";
import { rm } from "node:fs/promises";
import { getInternalToken } from "./auth/internal-token";
import {
  emptyResult,
  subprocessCancelled,
  subprocessFailed,
  subprocessSpawnFailed,
} from "./util/errors";
import pkg from "../../package.json";

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
  return new Promise<JSON | null>(async (resolve, reject) => {
    const id = crypto.randomUUID();

    const tmpfile = path.resolve(`tmp/data/${id}-{}.json`);

    const inputPath = tmpfile.replace("{}", "input");
    const outputPath = tmpfile.replace("{}", "output");

    // console.log("Initing input file at", inputPath);
    await Bun.write(inputPath, JSON.stringify(args));

    // console.log("Initing output file at", outputPath);
    await Bun.write(outputPath, "");

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
      if (/^(INFO|DEBUG|ERROR|WARNING)\:/.test(line)) {
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
      // /Divert all errors to the websocket
      onLog?.(line);
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

      if (text) {
        // Parsed inside the try: this handler is async, so a throw here
        // becomes an unhandled rejection and the run never settles at all.
        // A half-written file is what a crash mid-dump leaves behind.
        try {
          return resolve(JSON.parse(text));
        } catch (e) {
          console.error(`Unreadable output from ${scriptName}`);
          console.error(e);
          return reject(emptyResult(scriptName));
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
