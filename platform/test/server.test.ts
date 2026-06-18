import { describe, expect, it } from "bun:test";
import setup from "../src/server";
import { hashToken, type Client } from "../src/middleware/client_keys";

const port = 9865;
const baseUrl = `http://localhost:${port}`;

// Known clients for the mapped app, keyed by token hash (no real DB).
const ALPHA = "alpha-token";
const GAMMA = "gamma-token"; // known client with no stored key
const clients: Record<string, Client> = {
  [hashToken(ALPHA)]: { name: "alpha", anthropicKey: "sk-ant-alpha" },
  [hashToken(GAMMA)]: { name: "gamma", anthropicKey: null },
};
const lookup = async (hash: string) => clients[hash] ?? null;

// Base app: client-key mapping off (null lookup) — behaves exactly as before.
const app = await setup(port, null);
// Mapped app: recognises the known client tokens above.
const mappedApp = await setup(port + 1, lookup);

const get = (path: string) => new Request(`${baseUrl}/${path}`);

const post = (path: string, data: any) =>
  new Request(`${baseUrl}/${path}`, {
    method: "POST",
    body: typeof data === "string" ? data : JSON.stringify(data),
    headers: { "Content-Type": `application/${typeof data === "string" ? "text" : "json"}` },
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

describe("Client key mapping", () => {
  it("passes an unrecognised api_key through unchanged", async () => {
    const res = await mappedApp.handle(post("services/echo", { x: 1, api_key: "sk-a-real-key" }));
    expect(res.status).toBe(200);
    expect((await res.json()).api_key).toBe("sk-a-real-key");
  });

  it("swaps a known client token for the stored key", async () => {
    const res = await mappedApp.handle(post("services/echo", { x: 1, api_key: ALPHA }));
    expect(res.status).toBe(200);
    expect((await res.json()).api_key).toBe("sk-ant-alpha");
  });

  it("drops the key for a known client with none (falls back to env)", async () => {
    const res = await mappedApp.handle(post("services/echo", { x: 1, api_key: GAMMA }));
    expect(res.status).toBe(200);
    expect((await res.json()).api_key).toBeUndefined();
  });

  it("works with no api_key at all", async () => {
    const res = await mappedApp.handle(post("services/echo", { x: 1 }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.x).toBe(1);
    expect(body.api_key).toBeUndefined();
  });

  it("with mapping off, leaves a client token untouched", async () => {
    // The base app has no lookup, so even a "token" string is passed through as-is.
    const res = await app.handle(post("services/echo", { x: 1, api_key: ALPHA }));
    expect(res.status).toBe(200);
    expect((await res.json()).api_key).toBe(ALPHA);
  });
});
