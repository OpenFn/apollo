import type { ApolloError } from "../util/errors";
import {
  clientMisconfigured,
  serviceUnavailable,
  unauthorized,
} from "../util/errors";
import {
  ENC_PREFIX,
  decryptKey,
  parseEncKey,
} from "../util/instance-key-crypto";
import { clientsDbUrl, getDb } from "../db";
import { hashToken } from "./hash";
import { checkInternalHeader } from "./internal-token";
import { captureException } from "../util/sentry";

export type Client = { name: string; anthropicKey: string | null };

type Lookup = (hash: string) => Promise<Client | null> | Client | null;

// Absent = never checked; "miss" = checked, confirmed unknown, so a verified
// miss isn't mistaken for a cold slot.
type CacheEntry =
  | { kind: "hit"; client: Client; checkedAt: number }
  | { kind: "miss"; checkedAt: number };

// Outcome of resolving one token hash. "unavailable" (DB never came up, or
// the read threw) is kept distinct from "absent" (lookup completed, no such
// client) so the auth hook can answer with a retryable 503 instead of a
// misleading 401.
type LookupResult =
  | { kind: "found"; client: Client }
  | { kind: "absent" }
  | { kind: "unavailable" };

/** Resolution of which key the outgoing payload carries. The names are
 *  load-bearing: services.ts dispatches them in a named switch so the
 *  inbound-credential-never-forwarded invariant is structural, not
 *  positional. */
export type KeyResolution =
  // known client: swap in its stored Anthropic key
  | { kind: "useKey"; key: string }
  // drop field -> global key: a request with no api_key at all
  | { kind: "useGlobal" }
  // internal apollo() hop: leave body exactly as received
  | { kind: "passthrough" };

const CACHE_TTL_MS = 60_000;
// Longest a stale entry survives a broken DB before eviction. Scales with
// the TTL.
const MAX_STALENESS_MS = CACHE_TTL_MS * 3;

// Returned when an encrypted key can't be decrypted: that client is omitted
// (fail closed) rather than falling back to the global key, which would
// mis-bill its usage.
const DECRYPT_FAILED = Symbol("decrypt-failed");

interface AuthCtx {
  body?: { api_key?: unknown };
  query?: { api_key?: unknown };
  request?: { url?: unknown };
  set?: { status?: number };
  internalCall?: boolean;
  lightningClient?: Client;
}

export interface InstanceAuthOptions {
  // Master key for decrypting stored anthropic_api_key values. When omitted,
  // read from APOLLO_ENC_KEY at init(); pass explicitly in tests to skip the
  // env.
  encKey?: Buffer | null;
  // Test injection: a synchronous client resolver that bypasses the cache/DB
  // path entirely. Production leaves this unset.
  lookup?: Lookup | null;
  // Test injection: a per-hash DB read that drives the real
  // cache/single-flight/staleness logic in place of Postgres. Setting it
  // implies the DB is ready.
  dbLookup?: Lookup | null;
  // Whether a global ANTHROPIC_API_KEY is configured to serve keyless
  // requests. A boolean is snapshotted; a thunk is read live. When omitted,
  // defaults to reading process.env.ANTHROPIC_API_KEY through a thunk so
  // env/test changes stay live.
  hasGlobalKey?: boolean | (() => boolean);
}

// WS-upgrade fallback: Elysia may not have populated ctx.query before
// beforeHandle runs.
function queryParam(ctx: AuthCtx, name: string): string {
  const url = ctx?.request?.url;
  if (typeof url !== "string") return "";
  try {
    return new URL(url).searchParams.get(name)?.trim() ?? "";
  } catch {
    return "";
  }
}

function toLookupResult(client: Client | null): LookupResult {
  return client ? { kind: "found", client } : { kind: "absent" };
}

/**
 * The instance-auth surface, owning all per-process state: the per-client
 * cache, single-flight handles, dbReady flag, and the encryption key. One
 * instance per process is created in server.ts; tests construct their own
 * with injected lookups, so there are no test-seam exports and no module
 * globals.
 */
export class InstanceAuth {
  // False until the lightning_clients lookup is usable. A down DB means no
  // client can be resolved, so a caller with an api_key gets a retryable 503
  // (we can't verify).
  private dbReady = false;
  private readonly clientCache = new Map<string, CacheEntry>();
  // Single-flight handles per hash: concurrent lookups for the same token
  // share one promise, so a burst can never trigger more than one DB read for
  // that hash.
  private readonly lookupInFlight = new Map<string, Promise<Client | null>>();
  private encKey: Buffer | null;
  private readonly lookupOverride: Lookup | null;
  private readonly dbLookupOverride: Lookup | null;
  private readonly hasGlobalKey?: boolean | (() => boolean);

  constructor(opts: InstanceAuthOptions = {}) {
    this.encKey = opts.encKey ?? null;
    this.lookupOverride = opts.lookup ?? null;
    this.dbLookupOverride = opts.dbLookup ?? null;
    // A dbLookup override implies a reachable DB.
    if (this.dbLookupOverride) this.dbReady = true;
    this.hasGlobalKey = opts.hasGlobalKey;
  }

  globalKeyConfigured(): boolean {
    if (typeof this.hasGlobalKey === "function") return this.hasGlobalKey();
    if (this.hasGlobalKey !== undefined) return this.hasGlobalKey;
    return Boolean(process.env.ANTHROPIC_API_KEY);
  }

  // Reads APOLLO_ENC_KEY and probes the lightning_clients DB. If unreachable,
  // dbReady stays false and api_key callers get a 503.
  async init(): Promise<void> {
    this.encKey = parseEncKey(process.env.APOLLO_ENC_KEY);
    if (process.env.APOLLO_ENC_KEY && !this.encKey) {
      console.error(
        "Apollo instance auth: APOLLO_ENC_KEY is set but is not valid base64 of 32 bytes; encrypted client keys cannot be decrypted"
      );
    }

    if (!clientsDbUrl()) {
      this.dbReady = false;
      console.warn(
        "Apollo instance auth: neither APOLLO_CLIENTS_DB_URL nor POSTGRES_URL is set"
      );
      return;
    }

    // Migrations already ran in server.ts; this only probes reachability.
    try {
      await getDb()`SELECT 1`;
      this.dbReady = true;
      this.clientCache.clear();
      console.log("Apollo instance auth: lightning_clients lookup ready");
    } catch (err) {
      this.dbReady = false;
      console.error(
        "Apollo instance auth: the database could not be reached",
        err
      );
    }
  }

  // null => global env key; "enc:v1:…" => AES-256-GCM decrypt
  // (DECRYPT_FAILED on error); anything else => plaintext key, used as-is.
  private decryptStoredKey(
    stored: string | null,
    clientName: string
  ): string | null | typeof DECRYPT_FAILED {
    if (stored === null) return null;
    if (!stored.startsWith(ENC_PREFIX)) return stored;
    if (!this.encKey) {
      console.error(
        `Apollo instance auth: client "${clientName}" has an encrypted anthropic_api_key but APOLLO_ENC_KEY is unset/invalid`
      );
      captureException(
        new Error(
          "Apollo instance auth: encrypted client key but APOLLO_ENC_KEY unset/invalid"
        ),
        { reason: "missing-enc-key", client: clientName }
      );
      return DECRYPT_FAILED;
    }
    try {
      return decryptKey(stored, this.encKey);
    } catch (err) {
      console.error(
        `Apollo instance auth: could not decrypt anthropic_api_key for client "${clientName}";`,
        err
      );
      captureException(err, { reason: "decrypt-error", client: clientName });
      return DECRYPT_FAILED;
    }
  }

  rowToClient(row: {
    name: string;
    anthropic_api_key: string | null;
  }): Client | null {
    const key = this.decryptStoredKey(row.anthropic_api_key, row.name);
    if (key === DECRYPT_FAILED) return null;
    return { name: row.name, anthropicKey: key };
  }

  // One targeted query per hash: an unknown token costs one round-trip on
  // first sight, then a cached miss.
  private async queryClient(hash: string): Promise<Client | null> {
    const rows = (await getDb()`
      SELECT name, anthropic_api_key
      FROM lightning_clients WHERE auth_token_hash = ${hash} LIMIT 1
    `) as Array<{
      name: string;
      anthropic_api_key: string | null;
    }>;
    const row = rows[0];
    return row ? this.rowToClient(row) : null;
  }

  // Set the in-flight handle synchronously before the await yields, so a
  // burst after eviction still produces one query.
  private loadClient(hash: string): Promise<Client | null> {
    const inFlight = this.lookupInFlight.get(hash);
    if (inFlight) return inFlight;
    const read = this.dbLookupOverride ?? ((h: string) => this.queryClient(h));
    const promise = Promise.resolve(read(hash)).finally(() => {
      this.lookupInFlight.delete(hash);
    });
    this.lookupInFlight.set(hash, promise);
    return promise;
  }

  private cacheResult(hash: string, client: Client | null): void {
    this.clientCache.set(
      hash,
      client
        ? { kind: "hit", client, checkedAt: Date.now() }
        : { kind: "miss", checkedAt: Date.now() }
    );
  }

  private entryResult(entry: CacheEntry): LookupResult {
    return toLookupResult(entry.kind === "hit" ? entry.client : null);
  }

  private refreshInBackground(hash: string, entry: CacheEntry): void {
    void this.loadClient(hash)
      .then((client) => this.cacheResult(hash, client))
      .catch((err) => {
        // A throw in the log/capture on this voided chain would surface
        // as an unhandledRejection.
        try {
          console.error(
            "Apollo instance auth: background refresh of a cached client failed; serving until expiry",
            err
          );
          captureException(err, {
            reason: "stale-refresh-error",
            client: entry.kind === "hit" ? entry.client.name : null,
          });
        } catch {}
      });
  }

  private async lookupClient(hash: string): Promise<LookupResult> {
    // lookup never came up -> cannot verify
    if (!this.dbReady) return { kind: "unavailable" };

    const entry = this.clientCache.get(hash);
    if (entry) {
      const age = Date.now() - entry.checkedAt;
      if (age <= CACHE_TTL_MS) {
        return this.entryResult(entry);
      }
      if (age <= MAX_STALENESS_MS) {
        // Stale but within ceiling: serve cached now, refresh once in
        // background. A failed refresh leaves it to age out.
        this.refreshInBackground(hash, entry);
        return this.entryResult(entry);
      }
      // Beyond ceiling: evict and fall through to a cold awaited lookup
      // rather than serve a possibly-revoked client.
      this.clientCache.delete(hash);
    }

    try {
      const client = await this.loadClient(hash);
      this.cacheResult(hash, client);
      return toLookupResult(client);
    } catch (err) {
      console.error(
        "Apollo instance auth: client lookup failed against the database",
        err
      );
      return { kind: "unavailable" };
    }
  }

  private extractApiKey(ctx: AuthCtx): string {
    // WS upgrade is a bodyless GET, so the credential rides as ?api_key=
    // (query, URL fallback). A query token shows in logs, acceptable: it's
    // hashed at rest. Don't move to a header; browsers can't set them on a
    // WS upgrade.
    return (
      (typeof ctx.body?.api_key === "string" ? ctx.body.api_key.trim() : "") ||
      (typeof ctx.query?.api_key === "string"
        ? ctx.query.api_key.trim()
        : "") ||
      queryParam(ctx, "api_key")
    );
  }

  authenticate = async (ctx: any): Promise<ApolloError | void> => {
    const internal = checkInternalHeader(ctx);
    if (internal.kind === "match") {
      ctx.internalCall = true;
      return;
    }
    if (internal.kind === "mismatch") {
      // A wrong internal header is rejected outright, never retried as an
      // external api_key caller, so it can't ride in on a valid body
      // credential.
      console.warn(
        "Apollo internal token MISMATCH: x-apollo-internal present but does not match; likely a sibling process without a shared APOLLO_INTERNAL_TOKEN, or a forged header. Rejecting with 401"
      );
      return unauthorized(ctx);
    }

    const apiKey = this.extractApiKey(ctx);
    console.log(apiKey);
    if (!apiKey) {
      return this.globalKeyConfigured() ? undefined : unauthorized(ctx);
    }

    const hash = hashToken(apiKey);
    const result: LookupResult = this.lookupOverride
      ? toLookupResult(await this.lookupOverride(hash))
      : await this.lookupClient(hash);
    if (result.kind === "found") {
      // Recognised client with no stored key is a server-side
      // misconfiguration, not a caller error. Mis-billing the global key
      // would hide it, so 500 + report.
      if (!result.client.anthropicKey) {
        captureException(
          new Error(
            "Apollo instance auth: recognised client has no anthropic_api_key configured"
          ),
          { reason: "client-misconfigured-no-key", client: result.client.name }
        );
        return clientMisconfigured(ctx);
      }
      ctx.lightningClient = result.client;
      return;
    }

    // unavailable: lookup couldn't complete (our outage) -> retryable 503.
    // absent: lookup confirmed no such client -> 401.
    if (result.kind === "unavailable") {
      captureException(
        new Error("Apollo instance auth: client store unavailable"),
        { reason: "client-store-unavailable-503", tokenHash: hash }
      );
      return serviceUnavailable(ctx);
    }
    return unauthorized(ctx);
  };

  resolveKey = (ctx: AuthCtx): KeyResolution => {
    if (ctx?.internalCall) return { kind: "passthrough" };
    const client = ctx?.lightningClient as Client | undefined;
    // A null-key client never reaches here: authenticate() rejects it with
    // 500 and never sets ctx.lightningClient, so any client present here has
    // a stored key.
    if (client) return { kind: "useKey", key: client.anthropicKey as string };
    return { kind: "useGlobal" };
  };
}
