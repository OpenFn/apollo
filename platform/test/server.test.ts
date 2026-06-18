import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import setup from "../src/server";
import {
  __setAuthForTest,
  hashToken,
  internalAuthHeader,
} from "../src/middleware/auth";

const port = 9865;

const baseUrl = `http://localhost:${port}`;

const app = await setup(port);

// setup() runs initAuth(), which enables auth if the dev's .env sets
// INSTANCE_AUTH. Force auth off so the suite is deterministic; the auth block
// below opts back in via the test seam.
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
  // The credential is the api_key the client sends in the body. Clients are
  // keyed by the SHA-256 of that credential (no real DB — this is the seam).
  // ALPHA has a stored Anthropic key (Apollo swaps it in); BETA has none (the
  // credential is stripped and Apollo falls back to its global key). Neither
  // credential may ever pass through to the LLM call.
  const ALPHA = "lightning-cred-alpha";
  const BETA = "lightning-cred-beta";
  const clients: Record<string, { name: string; anthropicKey: string | null }> = {
    [hashToken(ALPHA)]: { name: "alpha", anthropicKey: "sk-ant-stored-alpha" },
    [hashToken(BETA)]: { name: "beta", anthropicKey: null },
  };

  const postKey = (path: string, data: any, apiKey?: string) =>
    post(path, { ...data, ...(apiKey ? { api_key: apiKey } : {}) });

  afterEach(() => {
    // Restore the open state the rest of the suite expects.
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
      // The stored key replaces the credential; the credential never passes through.
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
  });
});
