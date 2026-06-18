import { SQL } from "bun";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import type { ApolloError } from "../util/errors";
import { ENC_PREFIX, decryptKey, parseEncKey } from "../util/instance-key-crypto";

// A row from the lightning_clients table, as used at runtime.
type Client = { name: string; anthropicKey: string | null };

// A lookup resolves a token hash to a client, or null if unknown.
type Lookup = (hash: string) => Promise<Client | null> | Client | null;

// Instance auth is opt-in via the INSTANCE_AUTH env var (see initAuth). When it
// is unset/falsey, /services/* is open exactly as before. When set, every
// /services/* request must carry an api_key (in the body) that matches a known
// client.
let enabled = false;

// True once the lightning_clients lookup is actually usable. When auth is
// enabled but the DB/table can't be reached, this stays false and the gate
// fails CLOSED (rejects every external caller) rather than silently opening up.
let dbReady = false;

// When set (by tests), this replaces the DB-backed lookup so the suite can
// enable auth with a known token set without a real Postgres.
let lookupOverride: Lookup | null = null;

// Bun's native Postgres client (Bun >= 1.2). Created once in initAuth().
let sql: SQL | null = null;

// In-memory cache of all clients keyed by token hash, refreshed on a TTL so
// rows added/revoked directly in the DB are picked up within CACHE_TTL_MS.
const CACHE_TTL_MS = 60_000;
let clientCache: Map<string, Client> | null = null;
let cacheTs = 0;

// Single-flight handle for the cache refresh. Concurrent refreshes (e.g. a burst
// of requests hitting the TTL boundary at once) all share THIS one promise, so a
// refresh can never trigger more than one DB read no matter the concurrency.
let refreshInFlight: Promise<Map<string, Client>> | null = null;

// Master key (32 bytes) for decrypting stored anthropic_api_key values, parsed
// from APOLLO_ENC_KEY in initAuth. Null when unset — plaintext rows still work,
// but any "enc:v1:" row can't be decrypted and its client is omitted.
let encKey: Buffer | null = null;

// When set (by tests), this replaces loadClients in the refresh path so the
// single-flight/stale-while-revalidate behaviour can be exercised without a DB.
let loaderOverride: (() => Promise<Map<string, Client>>) | null = null;

// A per-process secret that identifies genuine Apollo-to-Apollo calls. The
// bridge spawns Python services as child processes that inherit this process's
// env, so exporting the token here lets services/util.py apollo() echo it back
// via the X-Apollo-Internal header. authGate exempts any request carrying it,
// so "Apollo calling itself" skips auth without trusting network position (the
// old loopback exemption trusted any local caller, including Lightning).
// Honour an operator-provided value; otherwise mint a fresh random one.
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

/** Header set marking a request as an internal apollo() self-call (used by tests). */
export function internalAuthHeader(): Record<string, string> {
  return { [INTERNAL_HEADER]: INTERNAL_TOKEN };
}

/** SHA-256 hex of a client credential (the api_key). Must match services/_instance_auth/hash_token.py. */
export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

// Sentinel returned by decryptStoredKey when an encrypted value can't be
// decrypted. Such a client is omitted from the cache (fail closed) rather than
// silently falling back to the global key, which would mis-bill its usage.
const DECRYPT_FAILED = Symbol("decrypt-failed");

/**
 * Resolve the anthropic_api_key column to the plaintext key Apollo should use.
 *  - null            → null (intentional: this client uses the global env key)
 *  - "enc:v1:…"      → AES-256-GCM decrypt with encKey; DECRYPT_FAILED on error
 *  - anything else   → legacy plaintext, used as-is (backward compatible)
 */
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

/** Build the hash→client map from raw rows, decrypting keys and dropping any
 *  client whose encrypted key can't be decrypted. Exported for tests. */
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

/**
 * Refresh the client cache, collapsing concurrent callers onto a single DB read
 * (single-flight). The in-flight promise is cleared in finally so a failed
 * refresh never wedges the cache — the next caller retries.
 */
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
  // Auth is on but the lookup never came up — reject (fail closed).
  if (!dbReady) return null;
  if (!loaderOverride && !sql) return null;

  const fresh = clientCache !== null && Date.now() - cacheTs <= CACHE_TTL_MS;
  if (!fresh) {
    if (clientCache !== null) {
      // Warm but stale: serve the current map now and refresh once in the
      // background. Errors are swallowed so a DB blip keeps serving stale (and
      // retries next request, since cacheTs only advances on success) instead
      // of 500ing every caller. The single-flight handle guarantees one read.
      void refreshClients().catch(() => {});
    } else {
      // Cold start: nothing to serve yet. Every concurrent caller awaits the
      // ONE shared load rather than each firing its own. On failure leave the
      // cache null and reject (fail closed).
      try {
        await refreshClients();
      } catch {
        return null;
      }
    }
  }
  return clientCache?.get(hash) ?? null;
}

/** Whether the INSTANCE_AUTH env var opts this instance into auth. */
function authOptIn(): boolean {
  const v = (process.env.INSTANCE_AUTH ?? "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

/**
 * Decide once at startup whether instance auth is active. The INSTANCE_AUTH env
 * var is the master switch: unset/falsey leaves /services/* open as before.
 * When set, auth is enabled and tokens are looked up in the lightning_clients
 * table (via POSTGRES_URL). If that table can't be reached, auth stays enabled
 * but the gate fails CLOSED (rejects every external caller) — an explicit
 * opt-in must never silently fall back to open.
 */
export async function initAuth(): Promise<void> {
  enabled = authOptIn();
  if (!enabled) {
    dbReady = false;
    console.warn(
      "Apollo instance auth DISABLED: INSTANCE_AUTH not set — /services/* is open to all callers."
    );
    return;
  }

  // Parse the at-rest encryption key for stored anthropic_api_key values.
  // Optional: when unset, plaintext rows keep working; only "enc:v1:" rows need
  // it. When set but malformed, warn loudly — encrypted clients will be rejected.
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

/**
 * Elysia onBeforeHandle hook scoped to the /services group. Returning a value
 * short-circuits the request with that value as the response body.
 * On success it stashes the resolved client on the context for apiKeyOverride.
 */
export async function authGate(ctx: any): Promise<ApolloError | void> {
  if (!enabled) return;

  // Apollo calling itself: the bridge's Python children echo back the internal
  // token (see services/util.py apollo()), so such calls skip the api_key
  // check. External callers can't forge this — it's a per-process secret that
  // is never sent to clients.
  const internal = ctx.request?.headers?.get?.(INTERNAL_HEADER) ?? "";
  if (internal && safeEqual(internal, INTERNAL_TOKEN)) return;

  // The credential is the api_key the client (Lightning) already sends in the
  // request body — there is no separate bearer token and no Lightning-side
  // change. Hash it and look for a matching row in lightning_clients; an absent
  // or unknown key is rejected.
  const apiKey =
    typeof ctx.body?.api_key === "string" ? ctx.body.api_key.trim() : "";
  if (!apiKey) return unauthorized(ctx);

  const lookup = lookupOverride ?? dbLookup;
  const client = await lookup(hashToken(apiKey));
  if (!client) return unauthorized(ctx);

  ctx.lightningClient = client;
}

/**
 * Resolve the api_key for the outgoing service payload. Merged LAST over the
 * request body so it always wins.
 *
 * When auth is OFF, returns {} — the payload is left exactly as the caller sent
 * it (backward compatible; the legacy "client supplies its own key" behaviour).
 *
 * When auth is ON, the api_key the client sent is ONLY an auth credential and is
 * NEVER passed through to the LLM. It is always overwritten: with the matched
 * client's stored anthropic_api_key, or — if that client has no stored key —
 * with `undefined`, which drops the field on serialisation so Apollo falls back
 * to its global ANTHROPIC_API_KEY. Either way the inbound credential cannot
 * survive into the payload.
 */
export function apiKeyOverride(ctx: any): { api_key?: string } {
  if (!enabled) return {};
  const client = ctx?.lightningClient as Client | undefined;
  return { api_key: client?.anthropicKey ?? undefined };
}

/** Test seam: pass a fake lookup to enable auth without a DB, or null to disable. */
export function __setAuthForTest(provider: Lookup | null): void {
  if (provider) {
    enabled = true;
    lookupOverride = provider;
  } else {
    enabled = false;
    lookupOverride = null;
  }
}

/**
 * Test seam: drive the real dbLookup (single-flight + stale-while-revalidate)
 * with a fake table loader instead of Postgres. Passing a loader enables auth on
 * the dbLookup path (lookupOverride cleared) and resets cache state; null tears
 * it back down.
 */
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

/** Test seam: mark the cache stale without touching its contents. */
export function __expireCacheForTest(): void {
  cacheTs = 0;
}

/** Test seam: set the at-rest decryption key (or null) without running initAuth. */
export function __setEncKeyForTest(key: Buffer | null): void {
  encKey = key;
}
