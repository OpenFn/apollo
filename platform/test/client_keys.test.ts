// Unit tests for per-client API key mapping. These construct their own lookup
// (no server, no Python), so they're fast and run anywhere. The echo-routed
// tests in server.test.ts cover the end-to-end wiring.
import { afterEach, describe, expect, it } from "bun:test";
import {
  createClientLookup,
  createKeyResolver,
  hashToken,
  resolveClientLookupFromEnv,
  type Client,
} from "../src/middleware/client_keys";

// Pinned hash shared with services/_instance_auth/tests/unit/test_hash_token.py.
// If TS and Python ever disagree, client tokens silently stop being recognised.
const KNOWN_TOKEN = "openfn-apollo-test-token";
const KNOWN_HASH = "58bf5a6b4e6fb8c6236c07cecad297478b484a7213d2b6e3ff92b309f9d41273";

const ALPHA = "alpha-token"; // client with a stored key
const GAMMA = "gamma-token"; // client with no stored key
const clients: Record<string, Client> = {
  [hashToken(ALPHA)]: { name: "alpha", anthropicKey: "sk-ant-alpha" },
  [hashToken(GAMMA)]: { name: "gamma", anthropicKey: null },
};
const lookup = async (hash: string) => clients[hash] ?? null;

describe("hashToken", () => {
  it("matches the pinned cross-language hash (must equal hash_token.py)", () => {
    expect(hashToken(KNOWN_TOKEN)).toBe(KNOWN_HASH);
  });
});

describe("createKeyResolver", () => {
  it("swaps a known token for the client's stored key", async () => {
    expect(await createKeyResolver(lookup)(ALPHA)).toBe("sk-ant-alpha");
  });

  it("returns undefined for a known client with no key (falls back to env)", async () => {
    expect(await createKeyResolver(lookup)(GAMMA)).toBeUndefined();
  });

  it("passes an unrecognised key through unchanged", async () => {
    expect(await createKeyResolver(lookup)("sk-a-real-key")).toBe("sk-a-real-key");
  });

  it("passes everything through when there is no lookup (feature off)", async () => {
    const resolve = createKeyResolver(null);
    expect(await resolve("sk-a-real-key")).toBe("sk-a-real-key");
    expect(await resolve(undefined)).toBeUndefined();
  });
});

describe("createClientLookup", () => {
  const rows = [
    { name: "alpha", auth_token_hash: hashToken(ALPHA), anthropic_api_key: "sk-ant-alpha" },
  ];
  const makeSql = (impl: () => Promise<any[]>) => {
    let calls = 0;
    const sql = (..._a: any[]) => {
      calls += 1;
      return impl();
    };
    return { sql, calls: () => calls };
  };

  it("resolves a known hash and caches (one query across two lookups)", async () => {
    const { sql, calls } = makeSql(() => Promise.resolve(rows));
    const find = createClientLookup(sql);
    expect((await find(hashToken(ALPHA)))?.anthropicKey).toBe("sk-ant-alpha");
    expect(await find(hashToken(ALPHA))).not.toBeNull();
    expect(calls()).toBe(1); // second lookup served from cache
  });

  it("returns null for an unknown hash", async () => {
    const { sql } = makeSql(() => Promise.resolve(rows));
    expect(await createClientLookup(sql)("no-such-hash")).toBeNull();
  });

  it("fails safe (null) when the load throws and there's no cache", async () => {
    const { sql } = makeSql(() => Promise.reject(new Error("db down")));
    expect(await createClientLookup(sql)(hashToken(ALPHA))).toBeNull();
  });
});

describe("resolveClientLookupFromEnv", () => {
  const saved = process.env.POSTGRES_URL;
  afterEach(() => {
    if (saved === undefined) delete process.env.POSTGRES_URL;
    else process.env.POSTGRES_URL = saved;
  });

  it("is off (returns null) when POSTGRES_URL is unset", async () => {
    delete process.env.POSTGRES_URL;
    expect(await resolveClientLookupFromEnv()).toBeNull();
  });
});
