import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { randomBytes } from "node:crypto";
import setup from "../src/server";
import {
  __expireCacheForTest,
  __setAuthForTest,
  __setEncKeyForTest,
  __setLoaderForTest,
  authGate,
  buildClientMap,
  hashToken,
  internalAuthHeader,
} from "../src/middleware/auth";
import { encryptKey } from "../src/util/instance-key-crypto";

const port = 9865;

const baseUrl = `http://localhost:${port}`;

const app = await setup(port);

// setup() runs initAuth(), which would enable auth if the dev's .env sets
// INSTANCE_AUTH. Force it off so the suite is deterministic; the auth block below
// opts back in via the test seam.
__setAuthForTest(null);

const get = (path: string) => {
  return new Request(`${baseUrl}/${path}`);
};

const post = (path: string, data: any) => {
  return new Request(`${baseUrl}/${path}`, {
    method: "POST",
    body: typeof data === "string" ? data : JSON.stringify(data),
    headers: {
      "Content-Type": `application/${
        typeof data === "string" ? "text" : "json"
      }`,
    },
  });
};

// I am not sure how appropriate unit tests are going to be here - but we'll add a few!
describe("Main server", () => {
  it("return 200 at root", async () => {
    const response = await app.handle(get(""));

    const status = response.status;

    expect(status).toBe(200);
  });

  // send messages through a web socket
});

// It won't be appropriate at all to unit test many of these
// but we can use the test echo service at least
describe("Python Services", () => {
  describe("Python echo", () => {
    it("returns a 200", async () => {
      const json = { x: 1 };
      const response = await app.handle(post("services/echo", json));

      expect(response.status).toBe(200);
    });

    it("echoes back an object with a session id", async () => {
      const json = { x: 1 };
      const response = await app.handle(post("services/echo", json));

      const text = await response.json();
      expect(text).toEqual({
        ...json,
        session_id: expect.any(String),
      });
      expect(text.session_id.length).toBeGreaterThan(0);
    });

    // echo through web socket with result and log
    it("returns through a websocket", async () => {
      return new Promise<void>((done) => {
        const payload = { a: 22 };

        // TODO maybe create a helper to manage client ocnnections
        const socket = new WebSocket(`ws://localhost:${port}/services/echo`);

        socket.addEventListener("message", ({ type, data }) => {
          const evt = JSON.parse(data);

          if (evt.event === "complete") {
            expect(evt.data).toEqual(payload);
            done();
          }
        });

        socket.addEventListener("open", (event) => {
          socket.send(
            JSON.stringify({
              event: "start",
              data: payload,
            })
          );
        });
      });
    });
  });

  describe("Error handling", () => {
    it("returns correct error structure for rate limits", async () => {
      const response = await app.handle(
        post("services/test_errors", { trigger: "RATE_LIMIT" })
      );

      expect(response.status).toBe(429);
      
      const body = await response.json();
      expect(body).toEqual({
        code: 429,
        type: "RATE_LIMIT",
        message: "Rate limit exceeded, please try again later",
        details: { retry_after: 60 }
      });
    });

    it("returns 500 for unexpected errors", async () => {
      const response = await app.handle(
        post("services/test_errors", { trigger: "UNEXPECTED" })
      );

      expect(response.status).toBe(500);
      
      const body = await response.json();
      expect(body.code).toBe(500);
      expect(body.type).toBe("INTERNAL_ERROR");
      expect(body.message).toBeDefined();
    });

    it("returns 200 for successful responses", async () => {
      const response = await app.handle(
        post("services/test_errors", { trigger: "SUCCESS" })
      );

      expect(response.status).toBe(200);

      const body = await response.json();
      expect(body).toEqual({ success: true });
    });
  });
});

describe("Instance authentication", () => {
  // No real DB — the seam keys clients by SHA-256 of the api_key they send. ALPHA
  // has a stored Anthropic key (swapped in); BETA has none (credential stripped).
  const ALPHA = "lightning-cred-alpha";
  const BETA = "lightning-cred-beta";
  const clients: Record<string, { name: string; anthropicKey: string | null }> = {
    [hashToken(ALPHA)]: { name: "alpha", anthropicKey: "sk-ant-stored-alpha" },
    [hashToken(BETA)]: { name: "beta", anthropicKey: null },
  };

  const postKey = (path: string, data: any, apiKey?: string) =>
    post(path, { ...data, ...(apiKey ? { api_key: apiKey } : {}) });

  afterEach(() => {
    __setAuthForTest(null);
  });

  it("stays open when auth is disabled", async () => {
    __setAuthForTest(null);
    const res = await app.handle(post("services/echo", { x: 1 }));
    expect(res.status).toBe(200);
  });

  describe("when enabled", () => {
    beforeEach(() => {
      __setAuthForTest((hash) => clients[hash] ?? null);
    });

    it("accepts a known credential and swaps in the client's stored key", async () => {
      const res = await app.handle(postKey("services/echo", { x: 1 }, ALPHA));
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.x).toBe(1);
      expect(body.api_key).toBe("sk-ant-stored-alpha");
      expect(body.api_key).not.toBe(ALPHA);
    });

    it("strips the credential when the client has no stored key", async () => {
      const res = await app.handle(postKey("services/echo", { x: 2 }, BETA));
      expect(res.status).toBe(200);
      const body = await res.json();
      // No stored key → api_key dropped entirely (Apollo uses its global key).
      expect(body.api_key).toBeUndefined();
    });

    it("rejects a missing api_key with 401 UNAUTHORIZED", async () => {
      const res = await app.handle(post("services/echo", { x: 1 }));
      expect(res.status).toBe(401);
      const body = await res.json();
      expect(body.code).toBe(401);
      expect(body.type).toBe("UNAUTHORIZED");
    });

    it("rejects an unknown api_key with 401", async () => {
      const res = await app.handle(postKey("services/echo", { x: 1 }, "sk-ant-nope"));
      expect(res.status).toBe(401);
    });

    it("leaves health and root endpoints open", async () => {
      expect((await app.handle(get("livez"))).status).toBe(200);
      expect((await app.handle(get(""))).status).toBe(200);
    });

    it("exempts internal apollo() self-calls carrying the internal token", async () => {
      const req = new Request(`${baseUrl}/services/echo`, {
        method: "POST",
        body: JSON.stringify({ x: 9 }),
        headers: { "Content-Type": "application/json", ...internalAuthHeader() },
      });
      const res = await app.handle(req);
      expect(res.status).toBe(200);
    });

    it("still rejects a request bearing a bogus internal token", async () => {
      const req = new Request(`${baseUrl}/services/echo`, {
        method: "POST",
        body: JSON.stringify({ x: 9 }),
        headers: { "Content-Type": "application/json", "x-apollo-internal": "nope" },
      });
      const res = await app.handle(req);
      expect(res.status).toBe(401);
    });

    it("passes a forwarded api_key through on internal self-calls untouched", async () => {
      // Already authenticated upstream, so a forwarded api_key must survive into
      // the payload rather than being stripped to the global key.
      const req = new Request(`${baseUrl}/services/echo`, {
        method: "POST",
        body: JSON.stringify({ x: 9, api_key: "sk-ant-forwarded" }),
        headers: { "Content-Type": "application/json", ...internalAuthHeader() },
      });
      const res = await app.handle(req);
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.api_key).toBe("sk-ant-forwarded");
    });

    it("rejects an unauthenticated WebSocket upgrade", async () => {
      // The WS upgrade carries no body, so no api_key to validate; the gate must
      // reject it rather than let it bypass auth.
      const req = new Request(`${baseUrl}/services/echo`, {
        method: "GET",
        headers: {
          Connection: "Upgrade",
          Upgrade: "websocket",
          "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
          "Sec-WebSocket-Version": "13",
        },
      });
      const res = await app.handle(req);
      expect(res.status).toBe(401);
    });
  });
});

describe("Instance auth cache refresh", () => {
  // Drive the real dbLookup with a fake loader so we can count DB reads per burst.
  // authGate is called directly with a minimal ctx (no echo service spawned).
  const ALPHA = "lightning-cred-alpha";
  const mapWith = (anthropicKey: string | null) =>
    new Map([[hashToken(ALPHA), { name: "alpha", anthropicKey }]]);
  const fakeCtx = (apiKey?: string) =>
    ({
      request: { headers: { get: () => null } },
      body: apiKey ? { api_key: apiKey } : {},
      set: { status: 200 },
    }) as any;
  const tick = () => new Promise((r) => setTimeout(r, 10));
  const settle = () => new Promise((r) => setTimeout(r, 40));

  afterEach(() => {
    __setLoaderForTest(null);
    __setAuthForTest(null);
  });

  it("collapses a cold-start burst into a single DB read", async () => {
    let calls = 0;
    __setLoaderForTest(async () => {
      calls++;
      await tick();
      return mapWith("sk-ant-stored-alpha");
    });

    const ctxs = Array.from({ length: 50 }, () => fakeCtx(ALPHA));
    await Promise.all(ctxs.map((c) => authGate(c)));

    expect(calls).toBe(1);
    for (const c of ctxs) {
      expect(c.lightningClient?.anthropicKey).toBe("sk-ant-stored-alpha");
    }
  });

  it("serves the stale list while one background refresh runs", async () => {
    let calls = 0;
    let current = mapWith("sk-ant-v1");
    __setLoaderForTest(async () => {
      calls++;
      await tick();
      return current;
    });

    // Cold start awaits the one load and warms the cache with v1.
    const warm = fakeCtx(ALPHA);
    await authGate(warm);
    expect(calls).toBe(1);
    expect(warm.lightningClient?.anthropicKey).toBe("sk-ant-v1");

    // New data lands in the DB; mark the cache stale.
    current = mapWith("sk-ant-v2");
    __expireCacheForTest();

    // The burst is served immediately from the stale v1 map and triggers
    // exactly one background refresh (not one per request).
    const ctxs = Array.from({ length: 25 }, () => fakeCtx(ALPHA));
    await Promise.all(ctxs.map((c) => authGate(c)));
    expect(calls).toBe(2);
    for (const c of ctxs) {
      expect(c.lightningClient?.anthropicKey).toBe("sk-ant-v1");
    }

    // Once the background refresh settles, the new value is visible — with no
    // further DB reads.
    await settle();
    const after = fakeCtx(ALPHA);
    await authGate(after);
    expect(after.lightningClient?.anthropicKey).toBe("sk-ant-v2");
    expect(calls).toBe(2);
  });

  it("keeps serving stale when the refresh fails, then recovers", async () => {
    let calls = 0;
    let fail = false;
    __setLoaderForTest(async () => {
      calls++;
      if (fail) throw new Error("db down");
      return mapWith("sk-ant-v1");
    });

    const warm = fakeCtx(ALPHA);
    await authGate(warm);
    expect(warm.lightningClient?.anthropicKey).toBe("sk-ant-v1");

    // Refresh now fails; stale callers are still authenticated (no 500/empty).
    fail = true;
    __expireCacheForTest();
    const ctxs = Array.from({ length: 10 }, () => fakeCtx(ALPHA));
    await Promise.all(ctxs.map((c) => authGate(c)));
    for (const c of ctxs) {
      expect(c.lightningClient?.anthropicKey).toBe("sk-ant-v1");
    }

    // Recover once the DB is back.
    fail = false;
    __expireCacheForTest();
    const ok = fakeCtx(ALPHA);
    await authGate(ok);
    expect(ok.lightningClient?.anthropicKey).toBe("sk-ant-v1");
  });
});

describe("Instance auth key encryption", () => {
  afterEach(() => __setEncKeyForTest(null));

  it("round-trips encrypted, plaintext, and null keys through buildClientMap", () => {
    const key = randomBytes(32);
    __setEncKeyForTest(key);
    const enc = encryptKey("sk-ant-secret", key);

    const map = buildClientMap([
      { name: "enc", auth_token_hash: "h-enc", anthropic_api_key: enc },
      { name: "plain", auth_token_hash: "h-plain", anthropic_api_key: "sk-ant-plain" },
      { name: "none", auth_token_hash: "h-none", anthropic_api_key: null },
    ]);

    expect(map.get("h-enc")?.anthropicKey).toBe("sk-ant-secret");
    expect(map.get("h-plain")?.anthropicKey).toBe("sk-ant-plain");
    expect(map.get("h-none")?.anthropicKey).toBeNull();
  });

  it("omits a client whose encrypted key can't be decrypted (wrong key)", () => {
    const enc = encryptKey("sk-ant-secret", randomBytes(32)); // encrypted with key A
    __setEncKeyForTest(randomBytes(32)); // server holds a different key

    const map = buildClientMap([
      { name: "bad", auth_token_hash: "h-bad", anthropic_api_key: enc },
    ]);

    expect(map.has("h-bad")).toBe(false);
  });

  it("omits an encrypted key when APOLLO_ENC_KEY is not configured", () => {
    __setEncKeyForTest(null);
    const enc = encryptKey("sk-ant-secret", randomBytes(32));

    const map = buildClientMap([
      { name: "bad", auth_token_hash: "h-bad", anthropic_api_key: enc },
    ]);

    expect(map.has("h-bad")).toBe(false);
  });
});
