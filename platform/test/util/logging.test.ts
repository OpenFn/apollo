import { describe, expect, it } from "bun:test";

import {
  attachRequestId,
  buildServiceRequestCompleteLog,
  buildServiceRequestErrorLog,
  buildServiceRequestStartLog,
  summarizePayloadShape,
} from "../../src/util/logging";

describe("summarizePayloadShape", () => {
  it("summarizes object keys with value types only", () => {
    const shape = summarizePayloadShape({
      content: "do not log me",
      count: 2,
      enabled: true,
      meta: null,
    });

    expect(shape).toEqual({
      type: "object",
      key_count: 4,
      keys: ["content", "count", "enabled", "meta"],
      fields: {
        content: "string",
        count: "number",
        enabled: "boolean",
        meta: "null",
      },
    });

    expect(JSON.stringify(shape)).not.toContain("do not log me");
  });

  it("summarizes nested objects and arrays without values", () => {
    const shape = summarizePayloadShape(
      {
        context: {
          adaptor: "@openfn/language-http@6.0.0",
          input: { data: { patient_id: 123 } },
        },
        history: [
          { role: "user", content: "secret question" },
          { role: "assistant", content: "secret answer" },
        ],
      },
      { maxDepth: 3 }
    );

    expect(shape).toEqual({
      type: "object",
      key_count: 2,
      keys: ["context", "history"],
      fields: {
        context: {
          type: "object",
          key_count: 2,
          keys: ["adaptor", "input"],
          fields: {
            adaptor: "string",
            input: {
              type: "object",
              key_count: 1,
              keys: ["data"],
              fields: {
                data: {
                  type: "object",
                  key_count: 1,
                  keys: ["patient_id"],
                  fields: {
                    patient_id: "number",
                  },
                },
              },
            },
          },
        },
        history: {
          type: "array",
          length: 2,
          item_types: ["object"],
          item_shape: {
            type: "object",
            key_count: 2,
            keys: ["role", "content"],
            fields: {
              role: "string",
              content: "string",
            },
          },
        },
      },
    });

    expect(JSON.stringify(shape)).not.toContain("secret question");
    expect(JSON.stringify(shape)).not.toContain("secret answer");
  });

  it("builds structured lifecycle logs with a shared request id", () => {
    const requestId = "req-abc";
    const route = "/services/job_chat";
    const service = "job_chat";
    const payload = {
      content: "super secret",
      stream: false,
    };

    const startLog = buildServiceRequestStartLog({
      requestId,
      route,
      service,
      payload,
      now: new Date("2026-02-28T12:00:00.000Z"),
    });
    const completeLog = buildServiceRequestCompleteLog({
      requestId,
      route,
      service,
      durationMs: 123,
      statusCode: 200,
      outcome: "success",
      now: new Date("2026-02-28T12:00:00.123Z"),
    });
    const errorLog = buildServiceRequestErrorLog({
      requestId,
      route,
      service,
      durationMs: 88,
      errorType: "TypeError",
      now: new Date("2026-02-28T12:00:00.088Z"),
    });

    expect(startLog).toMatchObject({
      event: "service_request_start",
      request_id: requestId,
      route,
      service,
    });
    expect(startLog.payload_shape.fields.content).toBe("string");
    expect(JSON.stringify(startLog)).not.toContain("super secret");

    expect(completeLog).toEqual({
      event: "service_request_complete",
      timestamp: "2026-02-28T12:00:00.123Z",
      request_id: requestId,
      route,
      service,
      duration_ms: 123,
      status_code: 200,
      outcome: "success",
    });

    expect(errorLog).toEqual({
      event: "service_request_error",
      timestamp: "2026-02-28T12:00:00.088Z",
      request_id: requestId,
      route,
      service,
      duration_ms: 88,
      error_type: "TypeError",
    });
  });

  it("injects request id only for object payloads", () => {
    expect(attachRequestId({ x: 1 }, "req-1")).toEqual({
      x: 1,
      _request_id: "req-1",
    });

    expect(attachRequestId("text payload", "req-1")).toBe("text payload");
    expect(attachRequestId(null, "req-1")).toBe(null);
    expect(attachRequestId([1, 2], "req-1")).toEqual([1, 2]);
  });
});
