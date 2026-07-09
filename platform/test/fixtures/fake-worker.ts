/*
  Fake Apollo worker for the bridge.ts unit tests.

  Spawned by bridge.ts exactly like the real worker (via a PATH-shimmed `poetry`
  in worker-bridge.test.ts), so it exercises the real spawn -> connect -> ready
  handshake -> START/reply machinery WITHOUT a real Python worker or any LLM call.

  It connects to APOLLO_SOCKET_PATH, sends the ready handshake carrying the
  injected APOLLO_INTERNAL_TOKEN, then replies to each START with scripted NDJSON
  frames driven by the START payload's `mode`. Raw-write modes let a test control
  socket chunking to exercise bridge's NDJSON reassembly and malformed-line
  handling.
*/

const socketPath = process.env.APOLLO_SOCKET_PATH ?? "";
const token = process.env.APOLLO_INTERNAL_TOKEN ?? "";

// Crash before the handshake so bridge counts a crash-near-startup (circuit
// breaker test). Nothing connects; bridge sees the child exit non-zero.
if (process.env.FAKE_CRASH_ON_BOOT === "1") {
  process.exit(1);
}

let sock: any = null;

const sendLine = (obj: unknown) => sock.write(JSON.stringify(obj) + "\n");

function handleStart(msg: any) {
  if (msg.type !== "START") return;
  const jobId = msg.job_id;
  const p = msg.payload ?? {};
  switch (p.mode) {
    case "end":
      sendLine({ type: "END", job_id: jobId, result: p.result ?? {} });
      break;

    case "error":
      sendLine({
        type: "ERROR",
        job_id: jobId,
        code: p.code,
        error_type: p.error_type,
        message: p.message,
        ...(p.details ? { details: p.details } : {}),
      });
      break;

    case "log_then_end":
      // Two whole messages in ONE socket write: bridge must split them on the
      // newline (LOG forwarded, then END resolves).
      sock.write(
        JSON.stringify({
          type: "LOG",
          job_id: jobId,
          level: p.level,
          source: p.source,
          message: p.message,
        }) +
          "\n" +
          JSON.stringify({ type: "END", job_id: jobId, result: p.result ?? {} }) +
          "\n"
      );
      break;

    case "event":
      sendLine({ type: "EVENT", job_id: jobId, event: p.event, data: p.data });
      sendLine({ type: "END", job_id: jobId, result: {} });
      break;

    case "status":
      sendLine({ type: "STATUS", job_id: jobId, data: p.data });
      sendLine({ type: "END", job_id: jobId, result: {} });
      break;

    case "attachment":
      sendLine({
        type: "ATTACHMENT",
        job_id: jobId,
        name: p.name,
        data: p.data,
      });
      sendLine({ type: "END", job_id: jobId, result: {} });
      break;

    case "split_end": {
      // ONE END frame split across two socket writes: bridge must buffer the
      // partial line and reassemble it.
      const s =
        JSON.stringify({ type: "END", job_id: jobId, result: p.result ?? {} }) +
        "\n";
      const mid = Math.max(1, Math.floor(s.length / 2));
      sock.write(s.slice(0, mid));
      setTimeout(() => sock.write(s.slice(mid)), 40);
      break;
    }

    case "malformed_then_end":
      // A non-JSON line must be skipped without killing the reader/hanging jobs.
      sock.write("this is not json at all\n");
      sendLine({ type: "END", job_id: jobId, result: p.result ?? {} });
      break;

    case "unknown_then_end":
      // A frame for an unknown/already-completed job_id must be dropped.
      sendLine({ type: "END", job_id: "00000000-0000-0000-0000-000000000000", result: {} });
      sendLine({ type: "END", job_id: jobId, result: p.result ?? {} });
      break;

    case "noreply":
      // Send nothing so the per-job timeout fires.
      break;

    case "crash":
      // Exit while the job is pending so bridge fails it (and all pending) 500.
      process.exit(1);
      break;

    default:
      sendLine({ type: "END", job_id: jobId, result: { echo: p } });
  }
}

let buf = "";
function onData(chunk: Buffer) {
  buf += chunk.toString("utf-8");
  let i: number;
  while ((i = buf.indexOf("\n")) !== -1) {
    const line = buf.slice(0, i);
    buf = buf.slice(i + 1);
    if (line.trim()) {
      try {
        handleStart(JSON.parse(line));
      } catch {
        // ignore anything unparseable from bridge (there shouldn't be any)
      }
    }
  }
}

async function connectWithRetry(): Promise<void> {
  const deadline = Date.now() + 10_000;
  for (;;) {
    try {
      await Bun.connect({
        unix: socketPath,
        socket: {
          open(s) {
            sock = s;
            // Ready handshake: control message (job_id null) carrying the token.
            s.write(
              JSON.stringify({
                type: "STATUS",
                job_id: null,
                data: { ready: true },
                token,
              }) + "\n"
            );
          },
          data(_s, chunk) {
            onData(chunk as Buffer);
          },
          close() {
            // Bun went away (server stopped) -> exit like the real worker does.
            process.exit(0);
          },
          error() {},
        },
      });
      return;
    } catch {
      if (Date.now() > deadline) throw new Error("fake worker: connect timed out");
      await new Promise((r) => setTimeout(r, 50));
    }
  }
}

await connectWithRetry();

// Keep the process alive to service jobs.
setInterval(() => {}, 1 << 30);
