import { SQL } from "bun";
import { createHash } from "node:crypto";
import type { ApolloError } from "../util/errors";

// A row from the lightning_clients table, as used at runtime.
type Client = { name: string; anthropicKey: string | null };

// A lookup resolves a token hash to a client, or null if unknown.
type Lookup = (hash: string) => Promise<Client | null> | Client | null;

// Instance auth is opt-in via the INSTANCE_AUTH env var (see initAuth). When it
// is unset/falsey, /services/* is open exactly as before. When set, every
// /services/* request requires a valid bearer token.
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

const LOOPBACK = new Set(["127.0.0.1", "::1", "::ffff:127.0.0.1"]);

/** SHA-256 hex of a bearer token. Must match services/_instance_auth/hash_token.py. */
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
  return { code: 401, type: "UNAUTHORIZED", message: "Missing or invalid API token" };
}

/**
 * Elysia onBeforeHandle hook scoped to the /services group. Returning a value
 * short-circuits the request with that value as the response body.
 * On success it stashes the resolved client on the context for apiKeyOverride.
 */
export async function authGate(ctx: any): Promise<ApolloError | void> {
  if (!enabled) return;

  // Exempt loopback callers — internal service-to-service apollo() calls hit
  // 127.0.0.1. Synthetic requests (app.handle) have no peer address, so the
  // gate is enforced for them (which is what the test suite relies on).
  const address = ctx.server?.requestIP?.(ctx.request)?.address;
  if (address && LOOPBACK.has(address)) return;

  const header = ctx.request?.headers?.get?.("authorization") ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return unauthorized(ctx);

  const lookup = lookupOverride ?? dbLookup;
  const client = await lookup(hashToken(token));
  if (!client) return unauthorized(ctx);

  ctx.lightningClient = client;
}

/**
 * Returns an { api_key } override to merge into a service payload so Apollo
 * uses the client's own Anthropic key. Returns {} when auth is off or the
 * client has no stored key, leaving the payload untouched (Python then falls
 * back to the global ANTHROPIC_API_KEY).
 */
export function apiKeyOverride(ctx: any): { api_key?: string } {
  const client = ctx?.lightningClient as Client | undefined;
  return client?.anthropicKey ? { api_key: client.anthropicKey } : {};
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
