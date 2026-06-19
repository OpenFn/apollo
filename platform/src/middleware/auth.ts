import { SQL } from "bun";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import type { ApolloError } from "../util/errors";
import { ENC_PREFIX, decryptKey, parseEncKey } from "../util/instance-key-crypto";

type Client = { name: string; anthropicKey: string | null };
type Lookup = (hash: string) => Promise<Client | null> | Client | null;

// Opt-in via INSTANCE_AUTH (see initAuth); when off, /services/* is open as before.
let enabled = false;

// False until the lightning_clients lookup is usable. Auth-on but unusable DB =>
// the gate fails CLOSED (rejects every external caller) rather than opening up.
let dbReady = false;

let lookupOverride: Lookup | null = null;
let sql: SQL | null = null;

// In-memory client cache (keyed by token hash), refreshed on a TTL so DB changes
// are picked up within CACHE_TTL_MS.
const CACHE_TTL_MS = 60_000;
let clientCache: Map<string, Client> | null = null;
let cacheTs = 0;

// Single-flight handle: concurrent refreshes share this one promise, so a refresh
// can never trigger more than one DB read no matter the concurrency.
let refreshInFlight: Promise<Map<string, Client>> | null = null;

// Master key for decrypting stored anthropic_api_key values (APOLLO_ENC_KEY). Null
// when unset — plaintext rows still work, but "enc:v1:" rows can't be decrypted.
let encKey: Buffer | null = null;

let loaderOverride: (() => Promise<Map<string, Client>>) | null = null;

// Per-process secret identifying genuine Apollo-to-Apollo calls. The bridge spawns
// Python children that inherit this env, so services/util.py apollo() echoes it back
// via the internal header; authGate exempts requests carrying it without trusting
// network position. Honour an operator-provided value, else mint a random one.
//
// MULTI-PROCESS: when unset, each process mints its OWN token. apollo() self-calls
// hit 127.0.0.1:{port} and normally land on the same process, but if processes
// share a port (SO_REUSEPORT / clustering) a self-call can hit a sibling and 401.
// Set APOLLO_INTERNAL_TOKEN to the SAME value across processes in that case.
export const INTERNAL_HEADER = "x-apollo-internal";
const INTERNAL_TOKEN =
  process.env.APOLLO_INTERNAL_TOKEN ?? randomBytes(32).toString("hex");
process.env.APOLLO_INTERNAL_TOKEN = INTERNAL_TOKEN;

/** Constant-time string compare, length-guarded. */
function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  return ab.length === bb.length && timingSafeEqual(ab, bb);
}

export function internalAuthHeader(): Record<string, string> {
  return { [INTERNAL_HEADER]: INTERNAL_TOKEN };
}

/** SHA-256 hex of a client credential. Must match services/_instance_auth/hash_token.py. */
export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

// Returned when an encrypted key can't be decrypted: that client is omitted from
// the cache (fail closed) rather than falling back to the global key, which would
// mis-bill its usage.
const DECRYPT_FAILED = Symbol("decrypt-failed");

// null => global env key; "enc:v1:…" => AES-256-GCM decrypt (DECRYPT_FAILED on
// error); anything else => legacy plaintext.
function decryptStoredKey(
  stored: string | null,
  clientName: string
): string | null | typeof DECRYPT_FAILED {
  if (stored === null) return null;
  if (!stored.startsWith(ENC_PREFIX)) return stored;
  if (!encKey) {
    console.error(
      `Apollo instance auth: client "${clientName}" has an encrypted anthropic_api_key but APOLLO_ENC_KEY is unset/invalid — omitting this client (fail closed).`
    );
    return DECRYPT_FAILED;
  }
  try {
    return decryptKey(stored, encKey);
  } catch (err) {
    console.error(
      `Apollo instance auth: could not decrypt anthropic_api_key for client "${clientName}" — omitting this client (fail closed).`,
      err
    );
    return DECRYPT_FAILED;
  }
}

/** Build the hash→client map, dropping any client whose encrypted key can't be
 *  decrypted (fail closed). Exported for tests. */
export function buildClientMap(
  rows: Array<{
    name: string;
    auth_token_hash: string;
    anthropic_api_key: string | null;
  }>
): Map<string, Client> {
  const map = new Map<string, Client>();
  for (const row of rows) {
    const key = decryptStoredKey(row.anthropic_api_key, row.name);
    if (key === DECRYPT_FAILED) continue;
    map.set(row.auth_token_hash, { name: row.name, anthropicKey: key });
  }
  return map;
}

async function loadClients(): Promise<Map<string, Client>> {
  const rows = (await sql!`
    SELECT name, auth_token_hash, anthropic_api_key FROM lightning_clients
  `) as Array<{
    name: string;
    auth_token_hash: string;
    anthropic_api_key: string | null;
  }>;
  return buildClientMap(rows);
}

// Single-flight refresh; the in-flight handle is cleared in finally so a failed
// refresh never wedges the cache (the next caller retries).
function refreshClients(): Promise<Map<string, Client>> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (loaderOverride ?? loadClients)()
    .then((map) => {
      clientCache = map;
      cacheTs = Date.now();
      return map;
    })
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
}

async function dbLookup(hash: string): Promise<Client | null> {
  if (!dbReady) return null; // auth on but lookup never came up -> fail closed
  if (!loaderOverride && !sql) return null;

  const fresh = clientCache !== null && Date.now() - cacheTs <= CACHE_TTL_MS;
  if (!fresh) {
    if (clientCache !== null) {
      // Warm but stale: serve the current map now and refresh once in the
      // background. Errors are swallowed so a DB blip keeps serving stale (cacheTs
      // only advances on success, so the next request retries).
      void refreshClients().catch(() => {});
    } else {
      // Cold start: every concurrent caller awaits the one shared load. On failure
      // leave the cache null and fail closed.
      try {
        await refreshClients();
      } catch {
        return null;
      }
    }
  }
  return clientCache?.get(hash) ?? null;
}

function authOptIn(): boolean {
  const v = (process.env.INSTANCE_AUTH ?? "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

// Decide once at startup whether auth is active. When INSTANCE_AUTH is set but the
// lightning_clients table can't be reached, auth stays on and the gate fails CLOSED
// — an explicit opt-in must never silently fall back to open.
export async function initAuth(): Promise<void> {
  enabled = authOptIn();
  if (!enabled) {
    dbReady = false;
    console.warn(
      "Apollo instance auth DISABLED: INSTANCE_AUTH not set — /services/* is open to all callers."
    );
    return;
  }

  encKey = parseEncKey(process.env.APOLLO_ENC_KEY);
  if (process.env.APOLLO_ENC_KEY && !encKey) {
    console.error(
      "Apollo instance auth: APOLLO_ENC_KEY is set but is not valid base64 of 32 bytes — encrypted client keys cannot be decrypted and those clients will be REJECTED."
    );
  }

  const url = process.env.POSTGRES_URL;
  if (!url) {
    dbReady = false;
    console.error(
      "Apollo instance auth ENABLED but POSTGRES_URL is not set — clients cannot be looked up. /services/* will REJECT all external callers until this is fixed."
    );
    return;
  }

  try {
    sql = new SQL(url);
    const rows = (await sql`
      SELECT to_regclass('public.lightning_clients') AS t
    `) as Array<{ t: string | null }>;
    if (rows?.[0]?.t) {
      dbReady = true;
      clientCache = null; // force a fresh load on the first request
      console.log(
        "Apollo instance auth ENABLED (INSTANCE_AUTH set; lightning_clients table present)."
      );
    } else {
      dbReady = false;
      console.error(
        "Apollo instance auth ENABLED but the lightning_clients table was not found — /services/* will REJECT all external callers. Run services/_instance_auth/schema.sql to provision it."
      );
    }
  } catch (err) {
    dbReady = false;
    console.error(
      "Apollo instance auth ENABLED but the lightning_clients table could not be verified — /services/* will REJECT all external callers.",
      err
    );
  }
}

function unauthorized(ctx: any): ApolloError {
  ctx.set.status = 401;
  return { code: 401, type: "UNAUTHORIZED", message: "Missing or invalid API key" };
}

// Elysia onBeforeHandle hook for the /services group. Returning a value
// short-circuits the request with that body; on success it stashes the resolved
// client on the context for apiKeyOverride.
export async function authGate(ctx: any): Promise<ApolloError | void> {
  if (!enabled) return;

  // Apollo calling itself: Python children echo back the internal token (see
  // services/util.py apollo()), so such calls skip the api_key check. External
  // callers can't forge it — it's a per-process secret never sent to clients.
  const internal = ctx.request?.headers?.get?.(INTERNAL_HEADER) ?? "";
  if (internal && safeEqual(internal, INTERNAL_TOKEN)) {
    // Flag so apiKeyOverride leaves the forwarded api_key untouched rather than
    // stripping it to the global key — which would mis-bill a per-client key
    // passed down an apollo() hop.
    ctx.internalCall = true;
    return;
  }

  // The credential is the api_key the caller sends in the body; hash it and look
  // for a matching client. Absent or unknown -> 401.
  const apiKey =
    typeof ctx.body?.api_key === "string" ? ctx.body.api_key.trim() : "";
  if (!apiKey) return unauthorized(ctx);

  const lookup = lookupOverride ?? dbLookup;
  const client = await lookup(hashToken(apiKey));
  if (!client) return unauthorized(ctx);

  ctx.lightningClient = client;
}

/**
 * Resolve the api_key for the outgoing payload (merged LAST so it wins). Auth off,
 * or an internal self-call: return {} (passthrough). Otherwise the inbound
 * credential is NEVER forwarded to the LLM — it's replaced with the client's stored
 * key, or undefined (dropped on serialise) so Apollo falls back to its global key.
 */
export function apiKeyOverride(ctx: any): { api_key?: string } {
  if (!enabled || ctx?.internalCall) return {};
  const client = ctx?.lightningClient as Client | undefined;
  return { api_key: client?.anthropicKey ?? undefined };
}

// --- Test seams ---

export function __setAuthForTest(provider: Lookup | null): void {
  if (provider) {
    enabled = true;
    lookupOverride = provider;
  } else {
    enabled = false;
    lookupOverride = null;
  }
}

// Drives the real dbLookup (single-flight + stale-while-revalidate) with a fake
// loader instead of Postgres; null tears it back down.
export function __setLoaderForTest(
  loader: (() => Promise<Map<string, Client>>) | null
): void {
  loaderOverride = loader;
  clientCache = null;
  cacheTs = 0;
  refreshInFlight = null;
  if (loader) {
    enabled = true;
    dbReady = true;
    lookupOverride = null;
  } else {
    dbReady = false;
  }
}

export function __expireCacheForTest(): void {
  cacheTs = 0;
}

export function __setEncKeyForTest(key: Buffer | null): void {
  encKey = key;
}
