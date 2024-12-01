import { describe, expect, it } from "bun:test";
import { app } from "../src/server";

const port = 9865;

const baseUrl = `http://localhost:${port}`;

app.listen(port);

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

    it("echoes back an object", async () => {
      const json = { x: 1 };
      const response = await app.handle(post("services/echo", json));

      const text = await response.json();
      expect(text).toEqual(json);
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
        errorCode: 429,
        errorType: "RATE_LIMIT",
        errorMessage: "Rate limit exceeded, please try again later",
        errorDetails: { retry_after: 60 }
      });
    });

    it("returns 500 for unexpected errors", async () => {
      const response = await app.handle(
        post("services/test_errors", { trigger: "UNEXPECTED" })
      );

      expect(response.status).toBe(500);
      
      const body = await response.json();
      expect(body.errorCode).toBe(500);
      expect(body.errorType).toBe("INTERNAL_ERROR");
      expect(body.errorMessage).toBeDefined();
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
