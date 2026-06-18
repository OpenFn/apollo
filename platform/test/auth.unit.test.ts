// Unit tests for the instance-auth gate, DB lookup, and env resolution. These
// construct their own auth instances (no shared globals, no server, no Python),
// so they're fast and run anywhere. The echo-routed tests in server.test.ts
// cover the end-to-end wiring.
import { afterEach, describe, expect, it } from "bun:test";
import {
  createDbLookup,
  createInstanceAuth,
  hashToken,
  resolveAuthConfigFromEnv,
  type AuthContext,
  type Client,
} from "../src/middleware/auth";

// Pinned hash shared with services/_instance_auth/tests/unit/test_hash_token.py.
// If TS and Python ever disagree, clients silently fail to authenticate.
const KNOWN_TOKEN = "openfn-apollo-test-token";
const KNOWN_HASH = "58bf5a6b4e6fb8c6236c07cecad297478b484a7213d2b6e3ff92b309f9d41273";

const ALPHA = "alpha-token";
const GAMMA = "gamma-token"; // known client, no stored key
const clients: Record<string, Client> = {
  [hashToken(ALPHA)]: { name: "alpha", anthropicKey: "sk-ant-alpha" },
  [hashToken(GAMMA)]: { name: "gamma", anthropicKey: null },
};
const lookup = (hash: string) => clients[hash] ?? null;

const ctx = (headers: Record<string, string> = {}): AuthContext => {
  const lower = new Map(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
  return {
    request: { headers: { get: (k: string) => lower.get(k.toLowerCase()) ?? null } } as any,
    set: {},
  };
};

describe("hashToken", () => {
  it("matches the pinned cross-language hash (must equal hash_token.py)", () => {
    expect(hashToken(KNOWN_TOKEN)).toBe(KNOWN_HASH);
  });
});

describe("gate", () => {
  it("is a no-op when auth is disabled", async () => {
    const auth = createInstanceAuth({ enabled: false, internalSecret: "", lookup });
    const c = ctx();
    expect(await auth.gate(c)).toBeUndefined();
    expect(c.set.status).toBeUndefined();
    expect(auth.isExternalClient(c)).toBe(false);
  });

  describe("when enabled", () => {
    const auth = createInstanceAuth({ enabled: true, internalSecret: "", lookup });

    it("accepts a valid token and injects the resolved key", async () => {
      const c = ctx({ authorization: `Bearer ${ALPHA}` });
      expect(await auth.gate(c)).toBeUndefined();
      expect(auth.isExternalClient(c)).toBe(true);
      expect(auth.apiKeyOverride(c)).toEqual({ api_key: "sk-ant-alpha" });
    });

    it("injects no key for a known client with no stored key", async () => {
      const c = ctx({ authorization: `Bearer ${GAMMA}` });
      await auth.gate(c);
      expect(auth.isExternalClient(c)).toBe(true);
      expect(auth.apiKeyOverride(c)).toEqual({});
    });

    it("rejects a missing token with 401 UNAUTHORIZED", async () => {
      const c = ctx();
      expect(await auth.gate(c)).toMatchObject({ code: 401, type: "UNAUTHORIZED" });
      expect(c.set.status).toBe(401);
    });

    it("rejects an unknown token with 401", async () => {
      expect(await auth.gate(ctx({ authorization: "Bearer nope" }))).toMatchObject({ code: 401 });
    });
  });

  describe("internal service-to-service", () => {
    const SECRET = "internal-s3cret";
    const auth = createInstanceAuth({ enabled: true, internalSecret: SECRET, lookup });

    it("passes through on a matching secret without a bearer token", async () => {
      const c = ctx({ "x-apollo-internal": SECRET });
      expect(await auth.gate(c)).toBeUndefined();
      expect(c.internalCall).toBe(true);
      expect(auth.isExternalClient(c)).toBe(false); // not external → payload untouched
    });

    it("rejects a wrong secret (and no bearer) with 401", async () => {
      expect(await auth.gate(ctx({ "x-apollo-internal": "wrong" }))).toMatchObject({ code: 401 });
    });
  });
});

describe("createDbLookup", () => {
  // Fake Bun.SQL tagged-template that returns a fixed row set and counts calls.
  const rows = [
    { name: "alpha", auth_token_hash: hashToken(ALPHA), anthropic_api_key: "sk-ant-alpha" },
  ];
  const makeSql = (impl: () => Promise<any[]>) => {
    let calls = 0;
    const sql = (..._args: any[]) => {
      calls += 1;
      return impl();
    };
    return { sql, calls: () => calls };
  };

  it("resolves a known hash and caches (one query across two lookups)", async () => {
    const { sql, calls } = makeSql(() => Promise.resolve(rows));
    const find = createDbLookup(sql);
    expect((await find(hashToken(ALPHA)))?.anthropicKey).toBe("sk-ant-alpha");
    expect(await find(hashToken(ALPHA))).not.toBeNull();
    expect(calls()).toBe(1); // second lookup served from cache
  });

  it("returns null for an unknown hash", async () => {
    const { sql } = makeSql(() => Promise.resolve(rows));
    expect(await createDbLookup(sql)("no-such-hash")).toBeNull();
  });

  it("fails closed (null) when the first load throws and there's no cache", async () => {
    const { sql } = makeSql(() => Promise.reject(new Error("db down")));
    expect(await createDbLookup(sql)(hashToken(ALPHA))).toBeNull();
  });
});

describe("resolveAuthConfigFromEnv", () => {
  const KEYS = ["INSTANCE_AUTH", "POSTGRES_URL", "APOLLO_INTERNAL_SECRET"] as const;
  const saved: Record<string, string | undefined> = {};
  for (const k of KEYS) saved[k] = process.env[k];

  afterEach(() => {
    for (const k of KEYS) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  });

  it("is disabled when INSTANCE_AUTH is unset", async () => {
    delete process.env.INSTANCE_AUTH;
    const config = await resolveAuthConfigFromEnv();
    expect(config.enabled).toBe(false);
    expect(await config.lookup("anything")).toBeNull();
  });

  it("fails closed (enabled, deny-all) when on but POSTGRES_URL is missing", async () => {
    process.env.INSTANCE_AUTH = "true";
    delete process.env.POSTGRES_URL;
    const config = await resolveAuthConfigFromEnv();
    expect(config.enabled).toBe(true);
    expect(await config.lookup(hashToken(ALPHA))).toBeNull(); // deny-all
  });
});
