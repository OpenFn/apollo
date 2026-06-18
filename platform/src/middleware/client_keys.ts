import { createHash } from "node:crypto";

// A row from the lightning_clients table: a client name and the API key Apollo
// should use on its behalf (null => fall back to the global ANTHROPIC_API_KEY).
export type Client = { name: string; anthropicKey: string | null };

/** Resolves a token hash to a client, or null if unknown. */
export type ClientLookup = (hash: string) => Promise<Client | null>;

const CACHE_TTL_MS = 60_000;

/** SHA-256 hex of a client token. Must match services/_instance_auth/hash_token.py. */
export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

/**
 * DB-backed client lookup by token hash. Caches the client list for CACHE_TTL_MS
 * (one query per window per process), with single-flight refresh and serve-stale
 * on error.
 */
export function createClientLookup(sql: any): ClientLookup {
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
      .then((m) => {
        cache = m;
        cacheTs = Date.now();
        return m;
      })
      .catch((err) => {
        if (cache) {
          console.error("Apollo client keys: cache refresh failed; serving stale.", err);
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
      console.error("Apollo client keys: lookup failed.", err);
      return null;
    }
  };
}

/**
 * Build the env-configured client lookup. Returns null (feature off, every
 * request passes through unchanged) unless POSTGRES_URL is set, Bun.SQL is
 * available (Bun >= 1.2), and the lightning_clients table exists. The feature is
 * therefore opt-in purely by provisioning the table; existing instances without
 * it behave exactly as before.
 */
export async function resolveClientLookupFromEnv(): Promise<ClientLookup | null> {
  const url = process.env.POSTGRES_URL;
  if (!url) return null;

  const { SQL } = (await import("bun")) as any;
  if (typeof SQL !== "function") {
    console.warn("Apollo client keys: Bun.SQL unavailable (needs Bun >= 1.2); mapping disabled.");
    return null;
  }

  try {
    const sql = new SQL(url);
    const rows = (await sql`
      SELECT to_regclass('public.lightning_clients') AS t
    `) as Array<{ t: string | null }>;
    if (!rows?.[0]?.t) return null; // table not provisioned → feature off
    console.log("Apollo client keys ENABLED (lightning_clients table present).");
    return createClientLookup(sql);
  } catch (err) {
    console.error("Apollo client keys: could not verify lightning_clients table; mapping disabled.", err);
    return null;
  }
}

/**
 * Resolve the api_key Apollo should use for a request, given the key the caller
 * sent. If it's a known client token, returns that client's stored key (or
 * undefined when the client has none, so the service falls back to the global
 * env key). Anything unrecognised is returned unchanged — so a normal client
 * passing its own provider key is untouched, exactly as before.
 */
export function createKeyResolver(lookup: ClientLookup | null) {
  return async (incomingKey: unknown): Promise<string | undefined> => {
    const key =
      typeof incomingKey === "string" && incomingKey.length > 0 ? incomingKey : undefined;
    if (!lookup || key === undefined) return key;
    const client = await lookup(hashToken(key));
    if (!client) return key; // not one of our tokens → a real key, pass through
    return client.anthropicKey ?? undefined; // our token → swap in the server-side key
  };
}
