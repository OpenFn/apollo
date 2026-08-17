import { describe, expect, it } from "bun:test";

import {
  ApolloThrowable,
  emptyResult,
  isApolloError,
  malformedResult,
  subprocessCancelled,
  subprocessFailed,
  subprocessKilled,
  subprocessSpawnFailed,
} from "../../src/util/errors";

describe("ApolloThrowable", () => {
  // JSON.stringify on an Error is "{}", so without toJSON the synchronous
  // service route answers a failure with the right status and an empty body.
  it("survives JSON.stringify with its envelope intact", () => {
    const parsed = JSON.parse(JSON.stringify(subprocessFailed("job_chat", 3)));

    expect(parsed.code).toBe(500);
    expect(parsed.type).toBe("SUBPROCESS_FAILED");
    expect(parsed.message).toContain("job_chat");
    expect(parsed.details.exitCode).toBe(3);
  });

  it("is recognised by isApolloError, so existing envelope handling applies", () => {
    expect(isApolloError(subprocessFailed("echo", 1))).toBe(true);
    expect(isApolloError(emptyResult("echo"))).toBe(true);
  });

  it("is a real Error, so it can be thrown and caught normally", () => {
    const error = emptyResult("workflow_chat");

    expect(error instanceof Error).toBe(true);
    expect(error instanceof ApolloThrowable).toBe(true);
    expect(error.message.length).toBeGreaterThan(0);
  });
});

describe("subprocess failures", () => {
  it("keeps the exit code", () => {
    expect(subprocessFailed("job_chat", 137).details?.exitCode).toBe(137);
  });

  // A spawn failure means poetry or python is missing, which is an operator
  // problem rather than a service one.
  it("distinguishes never-started from started-and-failed", () => {
    expect(subprocessSpawnFailed("echo", new Error("ENOENT")).type).toBe(
      "SUBPROCESS_SPAWN_FAILED"
    );
    expect(subprocessFailed("echo", 1).type).toBe("SUBPROCESS_FAILED");
  });

  // It ran and exited cleanly; what came back was unusable.
  it("reports an empty result as a bad gateway, not a server error", () => {
    expect(emptyResult("echo").code).toBe(502);
  });

  it("carries the spawn cause as a string, not a nested Error", () => {
    const details = subprocessSpawnFailed("echo", new Error("ENOENT")).details;

    expect(details?.cause).toBe("ENOENT");
  });

  it("keeps a deliberate cancellation out of the 5xx range", () => {
    // We stopped this one ourselves because the caller left. Reporting it as a
    // server error would bury the failures that mean something is broken.
    const cancelled = subprocessCancelled("global_chat", "SIGTERM");

    expect(cancelled.code).toBe(499);
    expect(cancelled.type).toBe("SUBPROCESS_CANCELLED");
    expect(cancelled.details?.signal).toBe("SIGTERM");
  });

  // OOM or a deploy's SIGTERM: the process reports a null exit code, so the
  // signal is the only honest diagnosis.
  it("names the signal when the process was killed", () => {
    const error = subprocessKilled("embed_docsite", "SIGKILL");

    expect(error.type).toBe("SUBPROCESS_KILLED");
    expect(error.details?.signal).toBe("SIGKILL");
  });

  it("reports unparseable output as a bad gateway", () => {
    const error = malformedResult("echo");

    expect(error.type).toBe("MALFORMED_RESULT");
    expect(error.code).toBe(502);
  });
});
