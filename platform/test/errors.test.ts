import { describe, expect, it } from "bun:test";
import { app } from "../src/server";

const port = 9866;
const baseUrl = `http://localhost:${port}`;

app.listen(port);

const post = (path: string, data: any) => {
  return new Request(`${baseUrl}/${path}`, {
    method: "POST",
    body: JSON.stringify(data),
    headers: {
      "Content-Type": "application/json"
    },
  });
};

describe("Error Handling", () => {
  describe("Python error responses", () => {
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