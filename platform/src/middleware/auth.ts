import { SQL } from "bun";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import type { ApolloError } from "../util/errors";

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

async function loadClients(): Promise<Map<string, Client>> {
  const rows = (await sql!`
    SELECT name, auth_token_hash, anthropic_api_key FROM lightning_clients
  `) as Array<{
    name: string;
    auth_token_hash: string;
    anthropic_api_key: string | null;
  }>;
  const map = new Map<string, Client>();
  for (const row of rows) {
    map.set(row.auth_token_hash, {
      name: row.name,
      anthropicKey: row.anthropic_api_key,
    });
  }
  return map;
}

async function dbLookup(hash: string): Promise<Client | null> {
  // Auth is on but the lookup never came up — reject (fail closed).
  if (!dbReady || !sql) return null;
  const now = Date.now();
  if (!clientCache || now - cacheTs > CACHE_TTL_MS) {
    clientCache = await loadClients();
    cacheTs = now;
  }
  return clientCache.get(hash) ?? null;
}

/** Whether the INSTANCE_AUTH env var opts this instance into auth. */
function authOptIn(): boolean {
  const v = (process.env.INSTANCE_AUTH ?? "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

/** Whether APOLLO_AUTH_DEBUG opts into per-request logging (read live each call). */
function debugEnabled(): boolean {
  const v = (process.env.APOLLO_AUTH_DEBUG ?? "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

/**
 * Opt-in logging of the shape of every /services/* request, for debugging what
 * callers (e.g. Lightning) actually send. Enable with APOLLO_AUTH_DEBUG=true.
 * Secrets are never printed raw: the inbound api_key (the credential) is shown
 * as its SHA-256 hash — exactly the value lightning_clients.auth_token_hash
 * stores, so you can paste it straight into the table to allow-list a client.
 * The internal token is shown only as present/absent and body values are
 * omitted (just the top-level key names). Wrapped so it can never break a
 * request if something is unexpectedly shaped.
 */
function debugLogRequest(ctx: any): void {
  if (!debugEnabled()) return;
  try {
    const req = ctx.request;
    const ip = ctx.server?.requestIP?.(req)?.address ?? "(no peer address)";
    const headers: Record<string, string> = {};
    req?.headers?.forEach?.((value: string, key: string) => {
      if (key === "authorization") {
        const token = value.startsWith("Bearer ") ? value.slice(7).trim() : "";
        headers[key] = token ? `Bearer <sha256:${hashToken(token)}>` : "<malformed>";
      } else if (key === INTERNAL_HEADER) {
        headers[key] = "<present>";
      } else {
        headers[key] = value;
      }
    });
    const bodyKeys =
      ctx.body && typeof ctx.body === "object" ? Object.keys(ctx.body) : [];
    const rawKey =
      typeof ctx.body?.api_key === "string" ? ctx.body.api_key.trim() : "";
    const apiKeyHash = rawKey ? `sha256:${hashToken(rawKey)}` : "(none)";
    const pathname = req?.url ? new URL(req.url).pathname : "(no url)";
    console.log(
      `[auth-debug] ${req?.method} ${pathname} from ${ip} | auth ${enabled ? "ON" : "OFF"}\n` +
        `[auth-debug]   headers: ${JSON.stringify(headers)}\n` +
        `[auth-debug]   body keys: ${JSON.stringify(bodyKeys)}\n` +
        `[auth-debug]   api_key (credential): ${apiKeyHash}`
    );
  } catch (err) {
    console.log("[auth-debug] failed to log request:", err);
  }
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
  debugLogRequest(ctx);
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
