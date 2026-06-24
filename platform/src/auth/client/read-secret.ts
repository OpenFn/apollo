import { createInterface } from "node:readline";
import { Writable } from "node:stream";

// Read a secret (an Anthropic key) from stdin so it never lands in argv, shell
// history, or `ps`. Two paths: piped (non-TTY) reads to EOF; interactive (TTY)
// prompts on stderr and reads one line.

/** Trim surrounding whitespace, matching hashToken's trim so a piped `echo "$KEY"`
 *  (trailing newline) and a typed prompt produce the same key. */
export function trimSecret(raw: string): string {
  return raw.trim();
}

/** Read a piped (non-TTY) stdin to EOF. The stream is injectable so the piped path
 *  is testable without a real terminal. */
export async function readPipedSecret(
  stream: AsyncIterable<Uint8Array | string> = process.stdin
): Promise<string> {
  const chunks: string[] = [];
  for await (const chunk of stream) {
    chunks.push(typeof chunk === "string" ? chunk : Buffer.from(chunk).toString("utf8"));
  }
  return trimSecret(chunks.join(""));
}

/** Prompt on stderr (so piped stdout stays clean) and read one line from a TTY.
 *  The prompt is written directly; readline's echo is routed to a discarding
 *  stream so the typed secret never reaches the terminal. */
function readTtySecret(prompt: string): Promise<string> {
  process.stderr.write(prompt);
  const muted = new Writable({ write: (_chunk, _enc, cb) => cb() });
  const rl = createInterface({ input: process.stdin, output: muted, terminal: true });
  return new Promise((resolve) => {
    rl.question("", (answer) => {
      process.stderr.write("\n");
      rl.close();
      resolve(trimSecret(answer));
    });
  });
}

/** Read a secret from stdin: piped when not a TTY, otherwise an interactive prompt. */
export async function readSecret(prompt = "Anthropic key: "): Promise<string> {
  if (process.stdin.isTTY) return readTtySecret(prompt);
  return readPipedSecret(process.stdin);
}
