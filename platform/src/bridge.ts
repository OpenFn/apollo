import readline from "node:readline";
import path from "node:path";
import { spawn } from "node:child_process";
import { rm } from "node:fs/promises";

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
  args: JSON,
  onLog?: (str: string) => void
) => {
  return new Promise<JSON | null>(async (resolve, reject) => {
    const id = crypto.randomUUID();

    const tmpfile = path.resolve(`tmp/data/${id}-{}.json`);

    const inputPath = tmpfile.replace("{}", "input");
    const outputPath = tmpfile.replace("{}", "output");

    console.log("Initing input file at", inputPath);
    await Bun.write(inputPath, JSON.stringify(args));

    console.log("Initing output file at", outputPath);
    await Bun.write(outputPath, "");

    const proc = spawn(
      "poetry",
      [
        "run",
        "python",
        "services/entry.py",
        "--service", scriptName,
        "--input", inputPath,
        "--output", outputPath,
        "--port", `${port}`,
      ],
      {}
    );

    proc.on("error", async (err) => {
      console.log(err);
    });

    proc.on("close", async (code) => {
      if (code) {
        console.error("Python process exited with code", code);
        reject(code);
      }
      const result = Bun.file(outputPath);
      const text = await result.text();

      try {
        await rm(inputPath);
        await rm(outputPath);
      } catch (e) {
        console.error("Error removing temporary files");
        console.error(e);
      }

      if (text) {
        resolve(JSON.parse(text));
      } else {
        console.warn("No data returned from pythonland");
        resolve(null);
      }
    });

    const rl = readline.createInterface({
      input: proc.stdout,
      crlfDelay: Infinity,
    });
    rl.on("line", (line) => {
      // First divert the log line locally
      console.log(line);

      // Then divert any logs from a logger object to the websocket
      if (/^(INFO|DEBUG|ERROR|WARN)\:/.test(line)) {
        // TODO I'd love to break the log line up in to JSON actually
        // { source, level, message }
        onLog?.(line);
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

    return;
  });
};
