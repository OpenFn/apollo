import type { ApolloError } from "../util/errors";
import { serviceUnavailable, unauthorized } from "../util/errors";
import { ENC_PREFIX, decryptKey, parseEncKey } from "../util/instance-key-crypto";
import { clientsDbUrl, getDb } from "../db";
import { hashToken } from "./hash";
import { checkInternalHeader } from "./internal-token";
import { captureException } from "../util/sentry";

export type Client = { name: string; anthropicKey: string | null };

// Resolve a client by token hash. Used both for the injected pre-cache bypass
// (lookup) and the injected per-hash DB read driving the cache (dbLookup).
type Lookup = (hash: string) => Promise<Client | null> | Client | null;

// Per-hash cache entry. An absent key means "never checked"; a "miss" means
// "checked, confirmed unknown". The two are distinguishable so a verified miss
// can be cached without being mistaken for a cold slot.
type CacheEntry =
  | { kind: "hit"; client: Client; checkedAt: number }
  | { kind: "miss"; checkedAt: number };

// Outcome of resolving one token hash. "unavailable" (DB never came up, or the read
// threw) is kept distinct from "absent" (lookup completed, no such client) so the auth
// hook can answer a non-sk-ant- caller with a retryable 503 instead of a misleading 401.
type LookupResult =
  | { kind: "found"; client: Client }
  | { kind: "absent" }
  | { kind: "unavailable" };

/** Resolution of which key the outgoing payload carries. The names are
 *  load-bearing: services.ts dispatches them in a named switch so the
 *  inbound-credential-never-forwarded invariant is structural, not positional. */
export type KeyResolution =
  | { kind: "useKey"; key: string } // known client: swap in its stored Anthropic key
  | { kind: "useGlobal" } // known client, NULL stored key: drop field -> global key
  | { kind: "forward" } // unknown caller past the shape check: leave body as received
  | { kind: "passthrough" }; // internal apollo() hop: leave body exactly as received

// Anthropic keys are prefixed sk-ant-; our client credentials are base64url, so the
// two shapes don't collide. An unknown key without this prefix is treated as a
// (likely Lightning) credential and rejected rather than forwarded to the LLM.
const ANTHROPIC_KEY_PREFIX = "sk-ant-";

const CACHE_TTL_MS = 60_000;
// Tunable ceiling: the longest a stale entry survives a broken DB before eviction.
// Scales with the TTL by design (Stu signed off on the 3x multiple).
const MAX_STALENESS_MS = CACHE_TTL_MS * 3;

// Returned when an encrypted key can't be decrypted: that client is omitted (fail
// closed) rather than falling back to the global key, which would mis-bill its usage.
const DECRYPT_FAILED = Symbol("decrypt-failed");

export interface InstanceAuthOptions {
  // Master key for decrypting stored anthropic_api_key values. When omitted, read
  // from APOLLO_ENC_KEY at init(); pass explicitly in tests to skip the env.
  encKey?: Buffer | null;
  // Test injection: a synchronous client resolver that bypasses the cache/DB path
  // entirely. Production leaves this unset.
  lookup?: Lookup | null;
  // Test injection: a per-hash DB read that drives the real cache/single-flight/
  // staleness logic in place of Postgres. Setting it implies the DB is ready.
  dbLookup?: Lookup | null;
}

// Read a query param straight off the request URL. Fallback for the WS-upgrade hook,
// where Elysia may not have populated ctx.query before beforeHandle runs.
function queryParam(ctx: any, name: string): string {
  const url = ctx?.request?.url;
  if (typeof url !== "string") return "";
  try {
    return new URL(url).searchParams.get(name)?.trim() ?? "";
  } catch {
    return "";
  }
}

// Map a completed lookup (Client | null) to a found/absent LookupResult. "unavailable"
// is never produced here; it arises only where the DB-backed path cannot complete a
// read (db not ready, or the read threw).
function toLookupResult(client: Client | null): LookupResult {
  return client ? { kind: "found", client } : { kind: "absent" };
}

/**
 * The instance-auth surface, owning all of what used to be module-level state:
 * the per-client cache, single-flight handles, dbReady flag, and the encryption
 * key. One instance per process is created in server.ts; tests construct their own
 * with injected lookups, so there are no test-seam exports and no module globals.
 */
export class InstanceAuth {
  // False until the lightning_clients lookup is usable. A down DB means no client
  // can be resolved, so every caller degrades to the shape-checked forward path.
  private dbReady = false;
  private readonly clientCache = new Map<string, CacheEntry>();
  // Single-flight handles per hash: concurrent lookups for the same token share one
  // promise, so a burst can never trigger more than one DB read for that hash.
  private readonly lookupInFlight = new Map<string, Promise<Client | null>>();
  private encKey: Buffer | null;
  private readonly lookupOverride: Lookup | null;
  private readonly dbLookupOverride: Lookup | null;

  constructor(opts: InstanceAuthOptions = {}) {
    this.encKey = opts.encKey ?? null;
    this.lookupOverride = opts.lookup ?? null;
    this.dbLookupOverride = opts.dbLookup ?? null;
    // Injecting a per-hash DB read implies a reachable DB; mirror the old test seam.
    if (this.dbLookupOverride) this.dbReady = true;
  }

  // The auth hook is always active. This reads APOLLO_ENC_KEY and probes the
  // lightning_clients lookup so known clients can be resolved; if the DB is
  // unreachable, dbReady stays false and every caller degrades to the shape-checked
  // forward path (it does not blanket-reject).
  async init(): Promise<void> {
    this.encKey = parseEncKey(process.env.APOLLO_ENC_KEY);
    if (process.env.APOLLO_ENC_KEY && !this.encKey) {
      console.error(
        "Apollo instance auth: APOLLO_ENC_KEY is set but is not valid base64 of 32 bytes; encrypted client keys cannot be decrypted and those clients will be REJECTED."
      );
    }

    if (!clientsDbUrl()) {
      this.dbReady = false;
      console.warn(
        "Apollo instance auth: neither APOLLO_CLIENTS_DB_URL nor POSTGRES_URL is set, so known clients cannot be looked up; callers fall to the shape-checked forward path."
      );
      return;
    }

    // Migrations have already run (server.ts), so the table exists if the DB is up.
    // The probe is now just a reachability check that sets dbReady.
    try {
      await getDb()`SELECT 1`;
      this.dbReady = true;
      this.clientCache.clear(); // force a fresh load on the first request
      console.log("Apollo instance auth: lightning_clients lookup ready.");
    } catch (err) {
      this.dbReady = false;
      console.error(
        "Apollo instance auth: the database could not be reached, so known-client swaps will not resolve; callers fall to the shape-checked forward path.",
        err
      );
    }
  }

  // null => global env key; "enc:v1:…" => AES-256-GCM decrypt (DECRYPT_FAILED on
  // error); anything else => legacy plaintext.
  private decryptStoredKey(
    stored: string | null,
    clientName: string
  ): string | null | typeof DECRYPT_FAILED {
    if (stored === null) return null;
    if (!stored.startsWith(ENC_PREFIX)) return stored;
    if (!this.encKey) {
      console.error(
        `Apollo instance auth: client "${clientName}" has an encrypted anthropic_api_key but APOLLO_ENC_KEY is unset/invalid; omitting this client (fail closed).`
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
        `Apollo instance auth: could not decrypt anthropic_api_key for client "${clientName}"; omitting this client (fail closed).`,
        err
      );
      captureException(err, { reason: "decrypt-error", client: clientName });
      return DECRYPT_FAILED;
    }
  }

  /** Turn one lightning_clients row into a Client, dropping it (fail closed) if its
   *  encrypted key can't be decrypted. */
  rowToClient(row: {
    name: string;
    anthropic_api_key: string | null;
  }): Client | null {
    const key = this.decryptStoredKey(row.anthropic_api_key, row.name);
    if (key === DECRYPT_FAILED) return null;
    return { name: row.name, anthropicKey: key };
  }

  // One targeted query for a single hash. Replaces the unbounded bulk SELECT: an
  // unknown token now costs at most one round-trip on first sight, then a cached miss.
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

  // Single-flight DB read for one hash: a concurrent caller for the same hash joins
  // the in-flight promise (set synchronously before the await yields, so an eviction
  // followed by a burst still produces one query). The handle is cleared in finally
  // so a failed lookup never wedges the slot.
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

  private cacheResult(hash: string, client: Client | null): Client | null {
    this.clientCache.set(
      hash,
      client
        ? { kind: "hit", client, checkedAt: Date.now() }
        : { kind: "miss", checkedAt: Date.now() }
    );
    return client;
  }

  private async lookupClient(hash: string): Promise<LookupResult> {
    if (!this.dbReady) return { kind: "unavailable" }; // lookup never came up -> cannot verify

    const entry = this.clientCache.get(hash);
    if (entry) {
      const age = Date.now() - entry.checkedAt;
      if (age <= CACHE_TTL_MS) {
        return toLookupResult(entry.kind === "hit" ? entry.client : null);
      }
      if (age <= MAX_STALENESS_MS) {
        // Stale but within the ceiling: serve the cached value now and refresh once
        // in the background. A failed refresh leaves the entry to age further; only
        // the single-flight read fires, so a burst at the boundary triggers one call.
        void this.loadClient(hash)
          .then((client) => this.cacheResult(hash, client))
          .catch((err) => {
            // Guard the catch body: a throw inside the log/capture on this voided
            // chain would otherwise surface as an unhandledRejection.
            try {
              console.error(
                "Apollo instance auth: background refresh of a cached client failed; serving the stale entry until it ages out.",
                err
              );
              captureException(err, {
                reason: "stale-refresh-error",
                client: entry.kind === "hit" ? entry.client.name : null,
              });
            } catch {}
          });
        return toLookupResult(entry.kind === "hit" ? entry.client : null);
      }
      // Beyond the ceiling: evict and fall through to a cold, awaited lookup rather
      // than serve a possibly-revoked client.
      this.clientCache.delete(hash);
      console.warn(
        `Apollo instance auth: cache entry for a client token exceeded the max-staleness ceiling (${MAX_STALENESS_MS}ms); evicting and re-checking the database.`
      );
    }

    // Cold (or just-evicted): every concurrent caller awaits the one shared read. On
    // failure cache nothing and fail closed (a former hit now rejects; a former miss
    // simply re-queries next time).
    try {
      const client = await this.loadClient(hash);
      this.cacheResult(hash, client);
      return toLookupResult(client);
    } catch (err) {
      console.error(
        "Apollo instance auth: client lookup failed against the database; rejecting this request (fail closed).",
        err
      );
      return { kind: "unavailable" };
    }
  }

  /**
   * Client-credential authentication: the /services/* onBeforeHandle hook. Internal-call
   * exemption is checked first and short-circuits; otherwise the inbound api_key is
   * hashed and looked up. The auth hook is always active but only rejects two cases: a
   * forged internal header, and an unknown non-sk-ant- key (a likely Lightning
   * credential we must not forward to the LLM). Returning a value short-circuits the
   * request with that body.
   */
  authenticate = async (ctx: any): Promise<ApolloError | void> => {
    // Internal-call exemption wins precedence: Python children echo back the
    // internal token (services/util.py apollo()), so such calls skip the api_key
    // check. External callers can't forge it; it's a per-process secret never sent
    // to clients.
    const internal = checkInternalHeader(ctx);
    if (internal.kind === "match") {
      // Flag so the key resolves to passthrough: the forwarded api_key is left
      // untouched rather than stripped, which would mis-bill a per-client key
      // passed down an apollo() hop.
      ctx.internalCall = true;
      return;
    }
    if (internal.kind === "mismatch") {
      // A non-empty internal header is a claim to be Apollo itself; a mismatch is
      // either a sibling process without a shared APOLLO_INTERNAL_TOKEN or a forged
      // header. Reject outright, never re-try as an external api_key caller, so a
      // wrong internal header can't ride in on a valid body credential.
      console.warn(
        "Apollo internal token MISMATCH: x-apollo-internal present but does not match; likely a sibling process without a shared APOLLO_INTERNAL_TOKEN, or a forged header. Rejecting with 401."
      );
      captureException(
        new Error("Apollo instance auth: internal token mismatch"),
        { reason: "internal-token-mismatch" }
      );
      return unauthorized(ctx);
    }

    // The credential is the api_key the caller sends. POST puts it in the body; a WS
    // upgrade is a bodyless GET, so it rides as the ?api_key= query param instead
    // (ctx.query, with a URL fallback for hooks where Elysia hasn't parsed it yet).
    // A query-string token shows up in access/proxy logs, which is acceptable here: Apollo
    // is internal and the token is hashed at rest, so a log leak doesn't expose the
    // stored Anthropic key. Don't "fix" this by moving to a header: browsers can't
    // set headers on a WS upgrade. No key at all takes the forward path (-> global
    // key), so only proceed to lookup when one is present.
    const apiKey =
      (typeof ctx.body?.api_key === "string" ? ctx.body.api_key.trim() : "") ||
      (typeof ctx.query?.api_key === "string" ? ctx.query.api_key.trim() : "") ||
      queryParam(ctx, "api_key");
    if (!apiKey) return;

    const hash = hashToken(apiKey);
    const result: LookupResult = this.lookupOverride
      ? toLookupResult(await this.lookupOverride(hash))
      : await this.lookupClient(hash);
    if (result.kind === "found") {
      ctx.lightningClient = result.client;
      return;
    }

    // An sk-ant- key is a bring-your-own Anthropic key: it needs no client lookup and
    // is forwarded unchanged even during a store outage, so it NEVER reaches the 503
    // below. On a WS upgrade it only rode the query string, so record it for the
    // message handler to fold into the outgoing payload.
    if (apiKey.startsWith(ANTHROPIC_KEY_PREFIX)) {
      ctx.forwardApiKey = apiKey;
      return;
    }

    // Non-sk-ant- from here. Split on whose fault the failure is:
    //  - unavailable: we could not complete the lookup (DB never came up, or the read
    //    threw). That is our outage and is retryable, so 503, never a misleading 401,
    //    never a silent forward of a likely Lightning credential.
    //  - absent: the lookup completed and confirmed no such client, so 401 as before.
    if (result.kind === "unavailable") {
      captureException(
        new Error(
          "Apollo instance auth: client store unavailable; returning 503 rather than a misleading 401"
        ),
        { reason: "client-store-unavailable-503", tokenHash: hash }
      );
      return serviceUnavailable(ctx);
    }
    return unauthorized(ctx);
  };

  /**
   * Anthropic-key resolver. The result is dispatched by a named switch in
   * services.ts; the inbound credential is never forwarded to the LLM in the
   * useKey/useGlobal cases. Internal hops pass through untouched; a known client
   * either swaps in its stored key or (NULL) falls back to the global key; every
   * other caller forwards the body as received.
   */
  resolveKey = (ctx: any): KeyResolution => {
    if (ctx?.internalCall) return { kind: "passthrough" };
    const client = ctx?.lightningClient as Client | undefined;
    if (client) {
      return client.anthropicKey
        ? { kind: "useKey", key: client.anthropicKey }
        : { kind: "useGlobal" };
    }
    return { kind: "forward" };
  };
}
