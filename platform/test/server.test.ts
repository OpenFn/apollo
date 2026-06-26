import { afterEach, beforeEach, describe, expect, it, setSystemTime, spyOn } from "bun:test";
import { randomBytes } from "node:crypto";
import { Elysia } from "elysia";
import setup from "../src/server";
import { captureException } from "../src/util/sentry";
import * as sentry from "../src/util/sentry";
import { InstanceAuth, type Client } from "../src/auth/instance-auth";
import { hashToken } from "../src/auth/hash";
import { internalAuthHeader } from "../src/auth/internal-token";
import { encryptKey } from "../src/util/instance-key-crypto";
import pkg from "../../package.json";

const port = 9865;

const baseUrl = `http://localhost:${port}`;

// extras of the first captureException call whose `reason` matches, or undefined.
// Lets the auth tests assert a capture fired with the expected reason without
// repeating the mock-calls scan and the extras cast at every site.
const capturedExtras = (
  spy: { mock: { calls: any[] } },
  reason: string
): Record<string, unknown> | undefined =>
  spy.mock.calls.find(([, extras]) => extras?.reason === reason)?.[1];

// The shared listening app gets a synchronous lookup driven by a test-controlled
// map. Setting `knownClients` per test is how a fresh configuration is applied
// without any module-global poke seam; an empty/absent map routes everyone by the
// shape rule, exactly as a down DB would.
let knownClients: Record<string, Client> | null = null;
const sharedAuth = new InstanceAuth({
  lookup: (hash) => knownClients?.[hash] ?? null,
});

const app = await setup(port, sharedAuth);

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

  it("includes X-Api-Version header on every response", async () => {
    const response = await app.handle(get(""));
    expect(response.headers.get("X-Api-Version")).toBe(pkg.version);
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

describe("Sentry", () => {
  // No SENTRY_DSN is set in the test env, so the helper was never initialised.
  it("captureException is a silent no-op when no DSN is configured", () => {
    expect(() => captureException(new Error("test"))).not.toThrow();
    expect(() => captureException("not even an error", { foo: 1 })).not.toThrow();
  });

  // Mirrors the onError hook server.ts registers: report, return nothing, and
  // let Elysia produce its normal error response untouched.
  it("an onError hook that only reports leaves the error response unchanged", async () => {
    const boom = (app: Elysia) =>
      app.get("/boom", () => {
        throw new Error("kaboom");
      });

    const withHook = boom(new Elysia().onError(({ error }) => captureException(error)));
    const without = boom(new Elysia());

    const a = await withHook.handle(new Request("http://localhost/boom"));
    const b = await without.handle(new Request("http://localhost/boom"));

    expect(a.status).toBe(b.status);
    expect(await a.text()).toBe(await b.text());
  });
});

describe("Instance authentication", () => {
  // No real DB — the seam keys clients by SHA-256 of the api_key they send. ALPHA
  // has a stored Anthropic key (swapped in); BETA has none (credential stripped).
  // Any other key is unknown and routed by the shape check.
  const ALPHA = "lightning-cred-alpha";
  const BETA = "lightning-cred-beta";
  const clients: Record<string, Client> = {
    [hashToken(ALPHA)]: { name: "alpha", anthropicKey: "sk-ant-stored-alpha" },
    [hashToken(BETA)]: { name: "beta", anthropicKey: null },
  };

  const postKey = (path: string, data: any, apiKey?: string) =>
    post(path, { ...data, ...(apiKey ? { api_key: apiKey } : {}) });

  // One mode now: the auth hook is always active. Point the shared instance's injected
  // lookup at the known-client map so rows 1/2 resolve; unknown keys fall to the
  // shape check regardless.
  beforeEach(() => {
    knownClients = clients;
  });

  afterEach(() => {
    knownClients = null;
  });

  // Row 1
  it("accepts a known credential and swaps in the client's stored key", async () => {
    const res = await app.handle(postKey("services/echo", { x: 1 }, ALPHA));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.x).toBe(1);
    expect(body.api_key).toBe("sk-ant-stored-alpha");
    expect(body.api_key).not.toBe(ALPHA);
  });

  // Row 2
  it("strips the credential when the client has no stored key", async () => {
    const res = await app.handle(postKey("services/echo", { x: 2 }, BETA));
    expect(res.status).toBe(200);
    const body = await res.json();
    // No stored key → api_key dropped entirely (Apollo uses its global key).
    expect(body.api_key).toBeUndefined();
  });

  // Row 3 — unknown but sk-ant-shaped: bring-your-own key, forwarded unchanged.
  it("forwards an unknown sk-ant-shaped key unchanged (bring-your-own)", async () => {
    const res = await app.handle(postKey("services/echo", { x: 1 }, "sk-ant-byo"));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.api_key).toBe("sk-ant-byo");
  });

  // Row 3b — unknown and NOT sk-ant-shaped: a likely Lightning credential; reject
  // rather than forward it to the LLM.
  it("rejects an unknown non-sk-ant- key with 401 (never forwarded)", async () => {
    const res = await app.handle(postKey("services/echo", { x: 1 }, "lightning-cred-unknown"));
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body.code).toBe(401);
    expect(body.type).toBe("UNAUTHORIZED");
  });

  // Row 4 — no api_key at all: forwarded without the field (global key fallback).
  it("forwards a request with no api_key (no 401), field absent", async () => {
    const res = await app.handle(post("services/echo", { x: 1 }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.api_key).toBeUndefined();
  });

  // Row 1 and row 3 coexist: known-client swap and bring-your-own forward in one run.
  it("serves the known-client swap and the bring-your-own forward side by side", async () => {
    const swapped = await (await app.handle(postKey("services/echo", { x: 1 }, ALPHA))).json();
    const forwarded = await (await app.handle(postKey("services/echo", { x: 1 }, "sk-ant-byo"))).json();
    expect(swapped.api_key).toBe("sk-ant-stored-alpha");
    expect(forwarded.api_key).toBe("sk-ant-byo");
  });

  it("leaves health and root endpoints open", async () => {
    expect((await app.handle(get("livez"))).status).toBe(200);
    expect((await app.handle(get(""))).status).toBe(200);
  });

  // Row 6 — bodyless README GET is served, no 401.
  it("serves a bodyless README GET without a 401", async () => {
    const res = await app.handle(get("services/echo/README.md"));
    expect(res.status).toBe(200);
  });

  // Row 5
  it("exempts internal apollo() self-calls carrying the internal token", async () => {
    const warn = spyOn(console, "warn").mockImplementation(() => {});
    try {
      const req = new Request(`${baseUrl}/services/echo`, {
        method: "POST",
        body: JSON.stringify({ x: 9 }),
        headers: { "Content-Type": "application/json", ...internalAuthHeader() },
      });
      const res = await app.handle(req);
      expect(res.status).toBe(200);
      // Correct token: the mismatch warn must not fire.
      expect(
        warn.mock.calls.some(([m]) => String(m).includes("internal token MISMATCH"))
      ).toBe(false);
    } finally {
      warn.mockRestore();
    }
  });

  it("rejects a bogus internal token with 401 and a distinct mismatch warn", async () => {
    const warn = spyOn(console, "warn").mockImplementation(() => {});
    try {
      const req = new Request(`${baseUrl}/services/echo`, {
        method: "POST",
        body: JSON.stringify({ x: 9 }),
        headers: { "Content-Type": "application/json", "x-apollo-internal": "nope" },
      });
      const res = await app.handle(req);
      expect(res.status).toBe(401);
      const warned = warn.mock.calls.map(([m]) => String(m)).join("\n");
      expect(warned).toContain("internal token MISMATCH");
      // Names both likely causes.
      expect(warned).toContain("APOLLO_INTERNAL_TOKEN");
      expect(warned.toLowerCase()).toContain("forged");
    } finally {
      warn.mockRestore();
    }
  });

  it("captures the internal-token mismatch and still rejects with 401", async () => {
    const warn = spyOn(console, "warn").mockImplementation(() => {});
    const capture = spyOn(sentry, "captureException");
    try {
      const req = new Request(`${baseUrl}/services/echo`, {
        method: "POST",
        body: JSON.stringify({ x: 9 }),
        headers: { "Content-Type": "application/json", "x-apollo-internal": "nope" },
      });
      const res = await app.handle(req);
      // Behaviour unchanged: a forged internal header still rejects.
      expect(res.status).toBe(401);
      // ...and the mismatch is no longer silent.
      expect(capturedExtras(capture, "internal-token-mismatch")).toBeDefined();
    } finally {
      capture.mockRestore();
      warn.mockRestore();
    }
  });

  it("rejects a wrong internal header even with a valid body api_key (no fall-through)", async () => {
    const warn = spyOn(console, "warn").mockImplementation(() => {});
    try {
      const req = new Request(`${baseUrl}/services/echo`, {
        method: "POST",
        // ALPHA is a known, otherwise-valid credential; the wrong internal
        // header must still reject it rather than authenticate via api_key.
        body: JSON.stringify({ x: 9, api_key: ALPHA }),
        headers: { "Content-Type": "application/json", "x-apollo-internal": "nope" },
      });
      const res = await app.handle(req);
      expect(res.status).toBe(401);
      expect(
        warn.mock.calls.some(([m]) => String(m).includes("internal token MISMATCH"))
      ).toBe(true);
    } finally {
      warn.mockRestore();
    }
  });

  it("does not emit the mismatch warn on the normal external path (no internal header)", async () => {
    const warn = spyOn(console, "warn").mockImplementation(() => {});
    try {
      // An unknown non-sk-ant- key takes the explicit-fail path (no internal header).
      const res = await app.handle(postKey("services/echo", { x: 1 }, "lightning-cred-unknown"));
      expect(res.status).toBe(401);
      expect(
        warn.mock.calls.some(([m]) => String(m).includes("internal token MISMATCH"))
      ).toBe(false);
    } finally {
      warn.mockRestore();
    }
  });

  // Row 5 — a per-client key resolved at the outer boundary must survive the hop.
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

  // WS upgrade auth decision via app.handle(): under the forward model a bare
  // upgrade is no longer rejected. app.handle() never performs a real socket
  // upgrade (Bun upgrades only through the listening server), so this proves the
  // auth hook forwarded rather than 401'd, not that the upgrade itself succeeds. The
  // 101/end-to-end no-regression proof is the live-socket echo test above.
  it("passes an unauthenticated WebSocket upgrade through the auth hook", async () => {
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
    expect(res.status).not.toBe(401);
  });

  // Drive a real upgrade against the listening server, send one start message, and
  // resolve with the first complete payload. Only a live socket exercises the
  // upgrade + message round-trip (and so the ws.data context capture); app.handle()
  // cannot. Extra headers (e.g. the internal token) ride the upgrade GET.
  const wsRoundTrip = (
    query = "",
    headers?: Record<string, string>
  ): Promise<any> =>
    new Promise((resolve, reject) => {
      const socket = new WebSocket(
        `ws://localhost:${port}/services/echo${query}`,
        headers ? { headers } : undefined
      );
      const timer = setTimeout(() => {
        socket.close();
        reject(new Error("ws round-trip timed out"));
      }, 8000);
      socket.addEventListener("error", (e) => {
        clearTimeout(timer);
        reject(e);
      });
      socket.addEventListener("message", ({ data }) => {
        const evt = JSON.parse(data as string);
        if (evt.event === "complete") {
          clearTimeout(timer);
          socket.close();
          resolve(evt.data);
        }
      });
      socket.addEventListener("open", () => {
        socket.send(JSON.stringify({ event: "start", data: { ws: 1 } }));
      });
    });

  // AC2 — a known client's token on the upgrade query string resolves to its stored
  // Anthropic key in the start payload, just like POST. Pins both the query read and
  // that ws.data carries the lightningClient set during beforeHandle.
  it("swaps a known client's stored key on a WS upgrade via ?api_key=", async () => {
    const body = await wsRoundTrip(`?api_key=${encodeURIComponent(ALPHA)}`);
    expect(body.api_key).toBe("sk-ant-stored-alpha");
    expect(body.api_key).not.toBe(ALPHA);
    expect(body.ws).toBe(1);
  });

  // AC3 — an unrecognised sk-ant- token on the upgrade connects and forwards as-is.
  it("forwards an unknown sk-ant- token on a WS upgrade unchanged", async () => {
    const body = await wsRoundTrip(`?api_key=sk-ant-ws-byo`);
    expect(body.api_key).toBe("sk-ant-ws-byo");
  });

  // Internal exemption holds on WS: the upgrade GET carries the internal header, so
  // a forwarded per-client api_key passes through untouched (not stripped/swapped).
  it("honours the internal token on a WS upgrade (passthrough)", async () => {
    const socket = new WebSocket(`ws://localhost:${port}/services/echo`, {
      headers: internalAuthHeader(),
    });
    const body = await new Promise<any>((resolve, reject) => {
      const timer = setTimeout(() => {
        socket.close();
        reject(new Error("ws round-trip timed out"));
      }, 8000);
      socket.addEventListener("error", (e) => {
        clearTimeout(timer);
        reject(e);
      });
      socket.addEventListener("message", ({ data }) => {
        const evt = JSON.parse(data as string);
        if (evt.event === "complete") {
          clearTimeout(timer);
          socket.close();
          resolve(evt.data);
        }
      });
      socket.addEventListener("open", () => {
        socket.send(
          JSON.stringify({
            event: "start",
            data: { api_key: "sk-ant-internal-fwd" },
          })
        );
      });
    });
    expect(body.api_key).toBe("sk-ant-internal-fwd");
  });
});

describe("Instance auth — DB-down forward path", () => {
  // No known clients: every caller is "unknown". The shape rule still applies — an
  // sk-ant- key forwards, a non-sk-ant- key fails explicitly.
  beforeEach(() => {
    knownClients = null;
  });

  // Row 7
  it("forwards an unknown sk-ant- key when the DB is down", async () => {
    const res = await app.handle(post("services/echo", { x: 1, api_key: "sk-ant-byo" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.api_key).toBe("sk-ant-byo");
  });

  // Row 8
  it("rejects an unknown non-sk-ant- key when the DB is down (never forwarded)", async () => {
    const res = await app.handle(post("services/echo", { x: 1, api_key: "lightning-cred-unknown" }));
    expect(res.status).toBe(401);
  });
});

describe("Instance auth — lookup never came up (dbReady false)", () => {
  // The shared app injects a `lookup`, so it never reaches lookupClient's dbReady
  // guard. Construct a bare InstanceAuth (no lookup/dbLookup => dbReady stays false)
  // and drive authenticate() directly to exercise the real fail-closed path a production
  // process takes when the DB never connected, distinct from the override-simulated
  // "DB-down" rows above, which converge on the same observable behaviour.
  const fakeCtx = (apiKey: string) =>
    ({
      request: { headers: { get: () => null } },
      body: { api_key: apiKey },
      set: { status: 200 },
    }) as any;

  it("forwards an unknown sk-ant- key via the shape rule (no DB)", async () => {
    const auth = new InstanceAuth();
    const ctx = fakeCtx("sk-ant-byo");
    await auth.authenticate(ctx);
    expect(ctx.forwardApiKey).toBe("sk-ant-byo");
    expect(ctx.set.status).toBe(200);
  });

  it("returns 503 for an unknown non-sk-ant- key when the lookup never came up (no DB)", async () => {
    const auth = new InstanceAuth();
    const ctx = fakeCtx("lightning-cred-unknown");
    await auth.authenticate(ctx);
    // dbReady is false, so we cannot verify the caller — that is our outage, not a bad credential: 503, never a misleading 401, never a forward.
    expect(ctx.set.status).toBe(503);
    expect(ctx.forwardApiKey).toBeUndefined();
  });
});

describe("Instance auth cache refresh", () => {
  // Drive the real lookupClient with a fake per-hash dbLookup so we can count DB
  // reads per burst. A fresh InstanceAuth per test isolates the cache; authenticate() is
  // called directly with a minimal ctx (no echo service). Ageing is simulated by
  // advancing the system clock (setSystemTime) rather than poking cache internals —
  // real setTimeout still fires in real time, so the single-flight sequencing holds.
  const ALPHA = "lightning-cred-alpha";
  const UNKNOWN = "lightning-cred-unknown";
  const clientWith = (anthropicKey: string | null): Client => ({
    name: "alpha",
    anthropicKey,
  });
  const fakeCtx = (apiKey?: string) =>
    ({
      request: { headers: { get: () => null } },
      body: apiKey ? { api_key: apiKey } : {},
      set: { status: 200 },
    }) as any;
  const tick = () => new Promise((r) => setTimeout(r, 10));
  const settle = () => new Promise((r) => setTimeout(r, 40));
  const TTL_MS = 60_000;
  // Just over the TTL (within the ceiling), so the next read serves stale + refreshes.
  const PAST_TTL = TTL_MS + 1;
  // Just over the ceiling, so the next read evicts rather than serves.
  const OVER_CEILING = TTL_MS * 3 + 1;

  // Advance the wall clock by `ms` from now so cached entries read as that much
  // older without touching their internals.
  const advanceClock = (ms: number) => setSystemTime(new Date(Date.now() + ms));

  afterEach(() => {
    setSystemTime(); // restore the real clock
  });

  it("collapses a cold-start burst into a single DB read", async () => {
    let calls = 0;
    const auth = new InstanceAuth({
      dbLookup: async () => {
        calls++;
        await tick();
        return clientWith("sk-ant-stored-alpha");
      },
    });

    const ctxs = Array.from({ length: 50 }, () => fakeCtx(ALPHA));
    await Promise.all(ctxs.map((c) => auth.authenticate(c)));

    expect(calls).toBe(1);
    for (const c of ctxs) {
      expect(c.lightningClient?.anthropicKey).toBe("sk-ant-stored-alpha");
    }
  });

  it("makes no DB call on a second request within the TTL", async () => {
    let calls = 0;
    const auth = new InstanceAuth({
      dbLookup: async () => {
        calls++;
        return clientWith("sk-ant-stored-alpha");
      },
    });

    await auth.authenticate(fakeCtx(ALPHA));
    await auth.authenticate(fakeCtx(ALPHA));
    expect(calls).toBe(1);
  });

  it("caches a negative result and serves it without a second DB call", async () => {
    let calls = 0;
    const auth = new InstanceAuth({
      dbLookup: async () => {
        calls++;
        return null; // verified unknown
      },
    });

    const first = fakeCtx(UNKNOWN);
    await auth.authenticate(first);
    // sk-ant-shaped? no -> unknown non-anthropic key is rejected.
    expect(first.set.status).toBe(401);

    const second = fakeCtx(UNKNOWN);
    await auth.authenticate(second);
    expect(second.set.status).toBe(401);
    expect(calls).toBe(1); // miss cached: no second lookup within the TTL
  });

  it("serves the stale value while one background refresh runs", async () => {
    let calls = 0;
    let current = clientWith("sk-ant-v1");
    const auth = new InstanceAuth({
      dbLookup: async () => {
        calls++;
        await tick();
        return current;
      },
    });

    // Cold start awaits the one load and warms the cache with v1.
    const warm = fakeCtx(ALPHA);
    await auth.authenticate(warm);
    expect(calls).toBe(1);
    expect(warm.lightningClient?.anthropicKey).toBe("sk-ant-v1");

    // New data lands in the DB; age the entry past the TTL but within the ceiling.
    current = clientWith("sk-ant-v2");
    advanceClock(PAST_TTL);

    // The burst is served immediately from the stale v1 value and triggers exactly
    // one background refresh (not one per request).
    const ctxs = Array.from({ length: 25 }, () => fakeCtx(ALPHA));
    await Promise.all(ctxs.map((c) => auth.authenticate(c)));
    expect(calls).toBe(2);
    for (const c of ctxs) {
      expect(c.lightningClient?.anthropicKey).toBe("sk-ant-v1");
    }

    // Once the background refresh settles, the new value is visible — no extra reads.
    await settle();
    const after = fakeCtx(ALPHA);
    await auth.authenticate(after);
    expect(after.lightningClient?.anthropicKey).toBe("sk-ant-v2");
    expect(calls).toBe(2);
  });

  it("keeps serving stale when the refresh fails, then recovers", async () => {
    let calls = 0;
    let fail = false;
    const auth = new InstanceAuth({
      dbLookup: async () => {
        calls++;
        if (fail) throw new Error("db down");
        return clientWith("sk-ant-v1");
      },
    });

    const warm = fakeCtx(ALPHA);
    await auth.authenticate(warm);
    expect(warm.lightningClient?.anthropicKey).toBe("sk-ant-v1");

    // Refresh now fails; stale-within-ceiling callers stay authenticated.
    fail = true;
    advanceClock(PAST_TTL);
    const error = spyOn(console, "error").mockImplementation(() => {});
    try {
      const ctxs = Array.from({ length: 10 }, () => fakeCtx(ALPHA));
      await Promise.all(ctxs.map((c) => auth.authenticate(c)));
      for (const c of ctxs) {
        expect(c.lightningClient?.anthropicKey).toBe("sk-ant-v1");
      }

      // Let the background refresh reject and run its catch under the mute.
      await settle();

      // Recover once the DB is back.
      fail = false;
      advanceClock(PAST_TTL);
      const ok = fakeCtx(ALPHA);
      await auth.authenticate(ok);
      expect(ok.lightningClient?.anthropicKey).toBe("sk-ant-v1");
    } finally {
      error.mockRestore();
    }
  });

  it("captures the swallowed stale-refresh error instead of hiding it, still serving stale", async () => {
    let calls = 0;
    let fail = false;
    const auth = new InstanceAuth({
      dbLookup: async () => {
        calls++;
        if (fail) throw new Error("db down");
        return clientWith("sk-ant-v1");
      },
    });

    const warm = fakeCtx(ALPHA);
    await auth.authenticate(warm);
    expect(warm.lightningClient?.anthropicKey).toBe("sk-ant-v1");

    // Age past the TTL but within the ceiling, then make the background refresh fail.
    fail = true;
    advanceClock(PAST_TTL);
    const capture = spyOn(sentry, "captureException");
    const error = spyOn(console, "error").mockImplementation(() => {});
    try {
      const ctx = fakeCtx(ALPHA);
      await auth.authenticate(ctx);
      // Behaviour unchanged: the stale value is still served within the window.
      expect(ctx.lightningClient?.anthropicKey).toBe("sk-ant-v1");

      // Let the background refresh reject and run its catch.
      await settle();
      expect(calls).toBe(2);
      expect(capturedExtras(capture, "stale-refresh-error")).toBeDefined();
    } finally {
      capture.mockRestore();
      error.mockRestore();
    }
  });

  it("evicts a positive entry past the ceiling and fails closed when the DB is down", async () => {
    let fail = false;
    const auth = new InstanceAuth({
      dbLookup: async () => {
        if (fail) throw new Error("db down");
        return clientWith("sk-ant-v1");
      },
    });

    const warm = fakeCtx(ALPHA);
    await auth.authenticate(warm);
    expect(warm.lightningClient?.anthropicKey).toBe("sk-ant-v1");

    // Push the entry past the ceiling with the DB now down: the read evicts and the
    // awaited cold lookup fails, so the request is rejected rather than served stale.
    fail = true;
    advanceClock(OVER_CEILING);
    const warn = spyOn(console, "warn").mockImplementation(() => {});
    const error = spyOn(console, "error").mockImplementation(() => {});
    try {
      const ctx = fakeCtx(ALPHA);
      await auth.authenticate(ctx);
      expect(ctx.lightningClient).toBeUndefined();
      // ALPHA is not sk-ant-shaped and the evicted-then-failed lookup could not verify it, so we 503 (our outage) rather than a misleading 401.
      expect(ctx.set.status).toBe(503);
      expect(warn.mock.calls.some(([m]) => String(m).includes("max-staleness ceiling"))).toBe(true);
      expect(error.mock.calls.some(([m]) => String(m).includes("client lookup failed"))).toBe(true);
    } finally {
      warn.mockRestore();
      error.mockRestore();
    }
  });

  it("rechecks a negative entry past the ceiling rather than blocking permanently", async () => {
    let result: Client | null = null;
    let calls = 0;
    const auth = new InstanceAuth({
      dbLookup: async () => {
        calls++;
        return result;
      },
    });

    // First sight: not found, miss cached.
    const first = fakeCtx(ALPHA);
    await auth.authenticate(first);
    expect(first.lightningClient).toBeUndefined();
    expect(calls).toBe(1);

    // The client gets provisioned; push the miss past the ceiling.
    result = clientWith("sk-ant-v1");
    const warn = spyOn(console, "warn").mockImplementation(() => {});
    try {
      advanceClock(OVER_CEILING);
      const second = fakeCtx(ALPHA);
      await auth.authenticate(second);
      // The miss was evicted and re-queried, picking up the now-provisioned client.
      expect(second.lightningClient?.anthropicKey).toBe("sk-ant-v1");
      expect(calls).toBe(2);
    } finally {
      warn.mockRestore();
    }
  });

  it("collapses a burst straddling an eviction boundary into one DB read", async () => {
    let calls = 0;
    const auth = new InstanceAuth({
      dbLookup: async () => {
        calls++;
        await tick();
        return clientWith("sk-ant-v1");
      },
    });

    // Warm, then age past the ceiling so the next reads must evict + cold-load.
    await auth.authenticate(fakeCtx(ALPHA));
    expect(calls).toBe(1);
    advanceClock(OVER_CEILING);

    const warn = spyOn(console, "warn").mockImplementation(() => {});
    try {
      const ctxs = Array.from({ length: 50 }, () => fakeCtx(ALPHA));
      await Promise.all(ctxs.map((c) => auth.authenticate(c)));
      // One eviction, one shared cold lookup for the burst.
      expect(calls).toBe(2);
      for (const c of ctxs) {
        expect(c.lightningClient?.anthropicKey).toBe("sk-ant-v1");
      }
    } finally {
      warn.mockRestore();
    }
  });

  it("returns 503 (not 401) when a cold DB read fails for a non-sk-ant- caller, capturing the outage", async () => {
    const auth = new InstanceAuth({
      dbLookup: async () => {
        throw new Error("db down");
      },
    });
    const error = spyOn(console, "error").mockImplementation(() => {});
    const capture = spyOn(sentry, "captureException");
    try {
      const ctx = fakeCtx(ALPHA); // non-sk-ant-shaped credential
      await auth.authenticate(ctx);
      expect(ctx.set.status).toBe(503);
      expect(ctx.lightningClient).toBeUndefined();
      expect(ctx.forwardApiKey).toBeUndefined();

      const extras = capturedExtras(capture, "client-store-unavailable-503");
      expect(extras).toBeDefined();
      expect(extras?.tokenHash).toBeDefined();
      // The capture must never carry the raw credential.
      expect(JSON.stringify(extras)).not.toContain(ALPHA);
    } finally {
      capture.mockRestore();
      error.mockRestore();
    }
  });

  it("still forwards an sk-ant- caller when a cold DB read fails (BYO key needs no lookup)", async () => {
    const auth = new InstanceAuth({
      dbLookup: async () => {
        throw new Error("db down");
      },
    });
    const error = spyOn(console, "error").mockImplementation(() => {});
    try {
      const ctx = fakeCtx("sk-ant-byo");
      await auth.authenticate(ctx);
      expect(ctx.set.status).toBe(200);
      expect(ctx.forwardApiKey).toBe("sk-ant-byo");
    } finally {
      error.mockRestore();
    }
  });
});

describe("Instance auth key encryption", () => {
  it("round-trips encrypted, plaintext, and null keys through rowToClient", () => {
    const key = randomBytes(32);
    const auth = new InstanceAuth({ encKey: key });
    const enc = encryptKey("sk-ant-secret", key);

    expect(
      auth.rowToClient({ name: "enc", anthropic_api_key: enc })?.anthropicKey
    ).toBe("sk-ant-secret");
    expect(
      auth.rowToClient({ name: "plain", anthropic_api_key: "sk-ant-plain" })?.anthropicKey
    ).toBe("sk-ant-plain");
    expect(
      auth.rowToClient({ name: "none", anthropic_api_key: null })?.anthropicKey
    ).toBeNull();
  });

  it("drops a client whose encrypted key can't be decrypted (wrong key)", () => {
    const error = spyOn(console, "error").mockImplementation(() => {});
    try {
      const enc = encryptKey("sk-ant-secret", randomBytes(32)); // encrypted with key A
      const auth = new InstanceAuth({ encKey: randomBytes(32) }); // holds a different key

      expect(auth.rowToClient({ name: "bad", anthropic_api_key: enc })).toBeNull();
    } finally {
      error.mockRestore();
    }
  });

  it("drops an encrypted key when APOLLO_ENC_KEY is not configured", () => {
    const error = spyOn(console, "error").mockImplementation(() => {});
    try {
      const auth = new InstanceAuth({ encKey: null });
      const enc = encryptKey("sk-ant-secret", randomBytes(32));

      expect(auth.rowToClient({ name: "bad", anthropic_api_key: enc })).toBeNull();
    } finally {
      error.mockRestore();
    }
  });

  // The two decrypt-failure branches stay fail-closed (row resolves to a
  // miss) but are no longer silent, and carry distinct reasons so an operator can
  // tell a global env misconfiguration from one corrupt/rotated row.
  it("captures a distinct reason when APOLLO_ENC_KEY is missing, still a miss", () => {
    const capture = spyOn(sentry, "captureException");
    const error = spyOn(console, "error").mockImplementation(() => {});
    try {
      const auth = new InstanceAuth({ encKey: null });
      const enc = encryptKey("sk-ant-secret", randomBytes(32));

      // Behaviour unchanged: the row still drops to a miss.
      expect(auth.rowToClient({ name: "missing", anthropic_api_key: enc })).toBeNull();

      const extras = capturedExtras(capture, "missing-enc-key");
      expect(extras).toBeDefined();
      // Non-secret identifier only — never the key, plaintext, or enc blob.
      expect(extras?.client).toBe("missing");
    } finally {
      capture.mockRestore();
      error.mockRestore();
    }
  });

  it("captures a distinct reason when an encrypted key won't decrypt, still a miss", () => {
    const capture = spyOn(sentry, "captureException");
    const error = spyOn(console, "error").mockImplementation(() => {});
    try {
      const enc = encryptKey("sk-ant-secret", randomBytes(32)); // encrypted with key A
      const auth = new InstanceAuth({ encKey: randomBytes(32) }); // holds a different key

      expect(auth.rowToClient({ name: "corrupt", anthropic_api_key: enc })).toBeNull();

      const extras = capturedExtras(capture, "decrypt-error");
      expect(extras).toBeDefined();
      expect(extras?.client).toBe("corrupt");
    } finally {
      capture.mockRestore();
      error.mockRestore();
    }
  });
});
