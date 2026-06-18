import { describe, expect, it } from "bun:test";
import setup from "../src/server";
import { createInstanceAuth, hashToken, type Client } from "../src/middleware/auth";

const port = 9865;
const baseUrl = `http://localhost:${port}`;

// Known clients for the enabled-auth apps, keyed by token hash (no real DB).
const ALPHA = "alpha-token";
const BETA = "beta-token";
const GAMMA = "gamma-token"; // known client with no stored key
const INTERNAL_SECRET = "internal-s3cret";
const clients: Record<string, Client> = {
  [hashToken(ALPHA)]: { name: "alpha", anthropicKey: "sk-ant-alpha" },
  [hashToken(BETA)]: { name: "beta", anthropicKey: "sk-ant-beta" },
  [hashToken(GAMMA)]: { name: "gamma", anthropicKey: null },
};
const lookup = (hash: string) => clients[hash] ?? null;

// One app per auth mode, each with an injected config (no shared global state).
const app = await setup(port, createInstanceAuth({ enabled: false, internalSecret: "", lookup }));
const enabledApp = await setup(port + 1, createInstanceAuth({ enabled: true, internalSecret: "", lookup }));
const internalApp = await setup(
  port + 2,
  createInstanceAuth({ enabled: true, internalSecret: INTERNAL_SECRET, lookup })
);

const get = (path: string) => new Request(`${baseUrl}/${path}`);

const post = (path: string, data: any) =>
  new Request(`${baseUrl}/${path}`, {
    method: "POST",
    body: typeof data === "string" ? data : JSON.stringify(data),
    headers: { "Content-Type": `application/${typeof data === "string" ? "text" : "json"}` },
  });

const postWith = (path: string, data: any, opts: { token?: string; headers?: Record<string, string> } = {}) =>
  new Request(`${baseUrl}/${path}`, {
    method: "POST",
    body: JSON.stringify(data),
    headers: {
      "Content-Type": "application/json",
      ...(opts.token ? { Authorization: `Bearer ${opts.token}` } : {}),
      ...(opts.headers ?? {}),
    },
  });

// I am not sure how appropriate unit tests are going to be here - but we'll add a few!
describe("Main server", () => {
  it("return 200 at root", async () => {
    const response = await app.handle(get(""));
    expect(response.status).toBe(200);
  });

  // send messages through a web socket
});

// It won't be appropriate at all to unit test many of these
// but we can use the test echo service at least
describe("Python Services", () => {
  describe("Python echo", () => {
    it("returns a 200", async () => {
      const response = await app.handle(post("services/echo", { x: 1 }));
      expect(response.status).toBe(200);
    });

    it("echoes back an object with a session id", async () => {
      const json = { x: 1 };
      const response = await app.handle(post("services/echo", json));

      const text = await response.json();
      expect(text).toEqual({ ...json, session_id: expect.any(String) });
      expect(text.session_id.length).toBeGreaterThan(0);
    });

    // echo through web socket with result and log
    it("returns through a websocket", async () => {
      return new Promise<void>((done) => {
        const payload = { a: 22 };
        const socket = new WebSocket(`ws://localhost:${port}/services/echo`);

        socket.addEventListener("message", ({ data }) => {
          const evt = JSON.parse(data);
          if (evt.event === "complete") {
            expect(evt.data).toEqual(payload);
            done();
          }
        });

        socket.addEventListener("open", () => {
          socket.send(JSON.stringify({ event: "start", data: payload }));
        });
      });
    });
  });

  describe("Error handling", () => {
    it("returns correct error structure for rate limits", async () => {
      const response = await app.handle(post("services/test_errors", { trigger: "RATE_LIMIT" }));

      expect(response.status).toBe(429);
      const body = await response.json();
      expect(body).toEqual({
        code: 429,
        type: "RATE_LIMIT",
        message: "Rate limit exceeded, please try again later",
        details: { retry_after: 60 },
      });
    });

    it("returns 500 for unexpected errors", async () => {
      const response = await app.handle(post("services/test_errors", { trigger: "UNEXPECTED" }));

      expect(response.status).toBe(500);
      const body = await response.json();
      expect(body.code).toBe(500);
      expect(body.type).toBe("INTERNAL_ERROR");
      expect(body.message).toBeDefined();
    });

    it("returns 200 for successful responses", async () => {
      const response = await app.handle(post("services/test_errors", { trigger: "SUCCESS" }));

      expect(response.status).toBe(200);
      const body = await response.json();
      expect(body).toEqual({ success: true });
    });
  });
});

describe("Instance authentication", () => {
  it("stays open when auth is disabled", async () => {
    const res = await app.handle(post("services/echo", { x: 1 }));
    expect(res.status).toBe(200);
  });

  describe("when enabled", () => {
    it("allows a valid token and injects the client's anthropic key", async () => {
      const res = await enabledApp.handle(postWith("services/echo", { x: 1 }, { token: ALPHA }));
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.x).toBe(1);
      expect(body.api_key).toBe("sk-ant-alpha");
    });

    it("allows a second client's token", async () => {
      const res = await enabledApp.handle(postWith("services/echo", { x: 2 }, { token: BETA }));
      expect(res.status).toBe(200);
      expect((await res.json()).api_key).toBe("sk-ant-beta");
    });

    it("rejects a missing token with 401 UNAUTHORIZED", async () => {
      const res = await enabledApp.handle(post("services/echo", { x: 1 }));
      expect(res.status).toBe(401);
      const body = await res.json();
      expect(body.code).toBe(401);
      expect(body.type).toBe("UNAUTHORIZED");
    });

    it("rejects a wrong token with 401", async () => {
      const res = await enabledApp.handle(postWith("services/echo", { x: 1 }, { token: "nope" }));
      expect(res.status).toBe(401);
    });

    it("strips a caller-supplied api_key and injects the resolved one", async () => {
      const res = await enabledApp.handle(
        postWith("services/echo", { x: 1, api_key: "sk-attacker" }, { token: ALPHA })
      );
      expect(res.status).toBe(200);
      expect((await res.json()).api_key).toBe("sk-ant-alpha");
    });

    it("injects no api_key when the client has none (falls back to global)", async () => {
      const res = await enabledApp.handle(
        postWith("services/echo", { x: 1, api_key: "sk-attacker" }, { token: GAMMA })
      );
      expect(res.status).toBe(200);
      expect((await res.json()).api_key).toBeUndefined();
    });

    it("leaves health and root endpoints open", async () => {
      expect((await enabledApp.handle(get("livez"))).status).toBe(200);
      expect((await enabledApp.handle(get(""))).status).toBe(200);
    });
  });

  describe("internal service-to-service calls", () => {
    it("passes through with a valid internal secret and no bearer token", async () => {
      const res = await internalApp.handle(
        postWith("services/echo", { x: 1 }, { headers: { "x-apollo-internal": INTERNAL_SECRET } })
      );
      expect(res.status).toBe(200);
    });

    it("preserves a parent-forwarded api_key untouched", async () => {
      const res = await internalApp.handle(
        postWith("services/echo", { x: 1, api_key: "sk-ant-forwarded" }, {
          headers: { "x-apollo-internal": INTERNAL_SECRET },
        })
      );
      expect(res.status).toBe(200);
      expect((await res.json()).api_key).toBe("sk-ant-forwarded");
    });

    it("rejects a wrong internal secret with 401 (no bearer token)", async () => {
      const res = await internalApp.handle(
        postWith("services/echo", { x: 1 }, { headers: { "x-apollo-internal": "wrong" } })
      );
      expect(res.status).toBe(401);
    });
  });
});
