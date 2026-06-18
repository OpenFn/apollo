import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import type { ApolloError } from "../util/errors";

export type Client = { name: string; anthropicKey: string | null };

/** Resolves a bearer-token hash to a client, or null if unknown. */
export type Lookup = (hash: string) => Promise<Client | null> | Client | null;

/** The slice of the Elysia context the gate reads and writes. */
export interface AuthContext {
  request: Request;
  set: { status?: number | string };
  lightningClient?: Client;
  internalCall?: boolean;
}

export interface AuthConfig {
  enabled: boolean;
  /** Shared secret for internal service-to-service calls; "" disables internal trust. */
  internalSecret: string;
  lookup: Lookup;
}

export interface InstanceAuth {
  gate(ctx: AuthContext): Promise<ApolloError | void>;
  isExternalClient(ctx: AuthContext): boolean;
  apiKeyOverride(ctx: AuthContext): { api_key?: string };
}

const INTERNAL_HEADER = "x-apollo-internal";
const CACHE_TTL_MS = 60_000;
const DENY_ALL: Lookup = () => null;

/** SHA-256 hex of a bearer token. Must match services/_instance_auth/hash_token.py. */
export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

function secretsMatch(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  return ab.length === bb.length && timingSafeEqual(ab, bb);
}

/**
 * DB-backed lookup with a TTL cache, single-flight refresh, and serve-stale on
 * error. The cache decouples request rate from DB rate (one query per TTL window
 * per process); a transient DB blip serves the last good data rather than
 * rejecting valid clients.
 */
export function createDbLookup(sql: any): Lookup {
  let cache: Map<string, Client> | null = null;
  let cacheTs = 0;
  let inflight: Promise<Map<string, Client>> | null = null;

  const load = async (): Promise<Map<string, Client>> => {
    const rows = (await sql`
      SELECT name, auth_token_hash, anthropic_api_key FROM lightning_clients
    `) as Array<{ name: string; auth_token_hash: string; anthropic_api_key: string | null }>;
    return new Map(
      rows.map((r) => [r.auth_token_hash, { name: r.name, anthropicKey: r.anthropic_api_key }])
    );
  };

  const clients = (): Promise<Map<string, Client>> => {
    if (cache && Date.now() - cacheTs <= CACHE_TTL_MS) return Promise.resolve(cache);
    if (inflight) return inflight;
    inflight = load()
      .then((map) => {
        cache = map;
        cacheTs = Date.now();
        return map;
      })
      .catch((err) => {
        if (cache) {
          console.error("Apollo instance auth: cache refresh failed; serving stale.", err);
          return cache;
        }
        throw err;
      })
      .finally(() => {
        inflight = null;
      });
    return inflight;
  };

  return async (hash) => {
    try {
      return (await clients()).get(hash) ?? null;
    } catch (err) {
      // Lookup unavailable and no cache to fall back on: fail closed (reject).
      console.error("Apollo instance auth: client lookup failed; rejecting.", err);
      return null;
    }
  };
}

function authOptIn(): boolean {
  const v = (process.env.INSTANCE_AUTH ?? "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

/**
 * Resolve auth config from the environment at startup. INSTANCE_AUTH is the
 * master switch; when unset, /services/* stays open. When set, tokens are looked
 * up in lightning_clients via POSTGRES_URL — and if the DB, table, or runtime
 * isn't usable, the gate fails CLOSED (deny-all) rather than silently opening.
 * Bun.SQL requires Bun >= 1.2, so it's imported lazily and checked here.
 */
export async function resolveAuthConfigFromEnv(): Promise<AuthConfig> {
  if (!authOptIn()) {
    console.warn("Apollo instance auth DISABLED: INSTANCE_AUTH not set.");
    return { enabled: false, internalSecret: "", lookup: DENY_ALL };
  }

  let internalSecret = (process.env.APOLLO_INTERNAL_SECRET ?? "").trim();
  if (!internalSecret) {
    // Generate one; spawned Python services inherit it via the environment, so
    // internal calls authenticate automatically with no operator config.
    internalSecret = randomBytes(32).toString("hex");
    process.env.APOLLO_INTERNAL_SECRET = internalSecret;
    console.log("Apollo instance auth: generated an ephemeral internal secret.");
  }

  const failClosed = (reason: string): AuthConfig => {
    console.error(
      `Apollo instance auth ENABLED but ${reason} — /services/* will REJECT all external callers.`
    );
    return { enabled: true, internalSecret, lookup: DENY_ALL };
  };

  const url = process.env.POSTGRES_URL;
  if (!url) return failClosed("POSTGRES_URL is not set");

  const { SQL } = (await import("bun")) as any;
  if (typeof SQL !== "function") {
    return failClosed("this Bun runtime lacks Bun.SQL (requires Bun >= 1.2; see .tool-versions)");
  }

  try {
    const sql = new SQL(url);
    const rows = (await sql`
      SELECT to_regclass('public.lightning_clients') AS t
    `) as Array<{ t: string | null }>;
    if (!rows?.[0]?.t) {
      return failClosed("the lightning_clients table is missing (run services/_instance_auth/schema.sql)");
    }
    console.log("Apollo instance auth ENABLED.");
    return { enabled: true, internalSecret, lookup: createDbLookup(sql) };
  } catch (err) {
    console.error("Apollo instance auth ENABLED but the lightning_clients table could not be verified.", err);
    return { enabled: true, internalSecret, lookup: DENY_ALL };
  }
}

/**
 * The /services gate. Internal calls (matching the shared secret, never trusted
 * by network address) pass through untouched, preserving a parent-forwarded
 * api_key. External calls require a valid bearer token; the resolved client is
 * stashed on the context for the payload layer.
 */
export function createInstanceAuth(config: AuthConfig): InstanceAuth {
  const unauthorized = (ctx: AuthContext): ApolloError => {
    ctx.set.status = 401;
    return { code: 401, type: "UNAUTHORIZED", message: "Missing or invalid API token" };
  };

  const isInternal = (ctx: AuthContext): boolean => {
    if (!config.internalSecret) return false;
    const provided = ctx.request.headers.get(INTERNAL_HEADER) ?? "";
    return provided.length > 0 && secretsMatch(provided, config.internalSecret);
  };

  return {
    async gate(ctx) {
      if (!config.enabled) return;
      if (isInternal(ctx)) {
        ctx.internalCall = true;
        return;
      }
      const header = ctx.request.headers.get("authorization") ?? "";
      const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
      if (!token) return unauthorized(ctx);
      const client = await config.lookup(hashToken(token));
      if (!client) return unauthorized(ctx);
      ctx.lightningClient = client;
    },

    isExternalClient(ctx) {
      return !!ctx.lightningClient;
    },

    // The single place provider/model routing will grow later; today a matched
    // client's stored key is used, else the service falls back to the env key.
    apiKeyOverride(ctx) {
      const key = ctx.lightningClient?.anthropicKey;
      return key ? { api_key: key } : {};
    },
  };
}
