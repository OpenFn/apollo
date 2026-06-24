import { randomBytes, timingSafeEqual } from "node:crypto";

// The internal-call exemption: a per-process secret that identifies genuine
// Apollo-to-Apollo calls. The bridge injects it into each Python child's env, so
// services/util.py apollo() echoes it back via the internal header; the auth hook
// exempts requests carrying it without trusting network position.
//
// MULTI-PROCESS: when APOLLO_INTERNAL_TOKEN is unset, each process mints its OWN
// token. apollo() self-calls hit 127.0.0.1:{port} and normally land on the same
// process, but if processes share a port (SO_REUSEPORT / clustering) a self-call
// can hit a sibling and 401. Set APOLLO_INTERNAL_TOKEN to the SAME value across
// processes in that case.

export const INTERNAL_HEADER = "x-apollo-internal";

// Whether the token came from the environment (shared, topology-safe) or was
// minted per-process. Drives the startup provenance log/warn.
const fromEnv = !!process.env.APOLLO_INTERNAL_TOKEN;
const token = process.env.APOLLO_INTERNAL_TOKEN ?? randomBytes(32).toString("hex");

/** The per-process internal token. bridge.ts injects this into spawned Python
 *  children so their apollo() self-calls are recognised. */
export function getInternalToken(): string {
  return token;
}

export function internalAuthHeader(): Record<string, string> {
  return { [INTERNAL_HEADER]: token };
}

/** Constant-time string compare, length-guarded. */
function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  return ab.length === bb.length && timingSafeEqual(ab, bb);
}

export type InternalCheck =
  | { kind: "absent" } // no internal header; fall through to the credential check
  | { kind: "match" } // genuine Apollo-to-Apollo call, exempt
  | { kind: "mismatch" }; // a claim to be Apollo that doesn't match, reject

/** Inspect the request's internal header against this process's token. */
export function checkInternalHeader(ctx: any): InternalCheck {
  const header = ctx?.request?.headers?.get?.(INTERNAL_HEADER) ?? "";
  if (!header) return { kind: "absent" };
  return safeEqual(header, token) ? { kind: "match" } : { kind: "mismatch" };
}

/** Startup provenance log; warns when a minted token meets reusePort. */
export function logInternalTokenProvenance(reusePort = false): void {
  console.log(
    fromEnv
      ? "Apollo internal token: from APOLLO_INTERNAL_TOKEN (safe for any topology)."
      : "Apollo internal token: minted per-process (safe only for single-process-per-host; set APOLLO_INTERNAL_TOKEN in production)."
  );
  if (reusePort && !fromEnv) {
    console.warn(
      "Apollo internal token: reusePort is ON but the token was minted per-process, so apollo() self-calls may land on a sibling process and 401. Set APOLLO_INTERNAL_TOKEN to the SAME value across all processes."
    );
  }
}
