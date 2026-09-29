import { afterEach, beforeEach, describe, expect, it, spyOn } from "bun:test";

import setup from "../src/server";
import { InstanceAuth } from "../src/auth/instance-auth";
import { closeDb } from "../src/db";
import * as sentry from "../src/util/sentry";

// internal-token.ts captures the token provenance (env vs minted) once at module
// load, and logInternalTokenProvenance() logs it. To exercise both branches we
// re-import the module in a fresh registry per case with APOLLO_INTERNAL_TOKEN
// pre-set or absent.
const freshInternalToken = async () => {
  const mod = `../src/auth/internal-token?cachebust=${Math.random()}`;
  return import(mod);
};

describe("Internal-token startup provenance", () => {
  const saved = process.env.APOLLO_INTERNAL_TOKEN;
  let log: ReturnType<typeof spyOn>;
  let warn: ReturnType<typeof spyOn>;

  beforeEach(() => {
    log = spyOn(console, "log").mockImplementation(() => {});
    warn = spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    log.mockRestore();
    warn.mockRestore();
    if (saved === undefined) delete process.env.APOLLO_INTERNAL_TOKEN;
    else process.env.APOLLO_INTERNAL_TOKEN = saved;
  });

  const logged = () => log.mock.calls.map(([m]) => String(m)).join("\n");
  const warned = () => warn.mock.calls.map(([m]) => String(m)).join("\n");

  it("logs 'from APOLLO_INTERNAL_TOKEN' and returns the env value when set", async () => {
    process.env.APOLLO_INTERNAL_TOKEN = "shared-token";
    const { logInternalTokenProvenance, getInternalToken } =
      await freshInternalToken();
    logInternalTokenProvenance();
    expect(logged()).toContain("from APOLLO_INTERNAL_TOKEN");
    expect(logged()).not.toContain("minted per-process");
    // Pin the token's actual value, not just the log text: a regression that broke
    // the derivation while leaving the provenance flag right would pass otherwise.
    expect(getInternalToken()).toBe("shared-token");
  });

  it("logs 'minted per-process' and mints a fresh random token when absent", async () => {
    delete process.env.APOLLO_INTERNAL_TOKEN;
    const a = await freshInternalToken();
    a.logInternalTokenProvenance();
    expect(logged()).toContain("minted per-process");
    expect(a.getInternalToken()).toMatch(/^[0-9a-f]{64}$/);
    // A separate process mints its own distinct token.
    const b = await freshInternalToken();
    expect(b.getInternalToken()).not.toBe(a.getInternalToken());
  });

  it("warns about reusePort only when the token was minted AND reusePort is on", async () => {
    delete process.env.APOLLO_INTERNAL_TOKEN;
    const { logInternalTokenProvenance } = await freshInternalToken();
    logInternalTokenProvenance(true);
    expect(warned()).toContain("reusePort");
    expect(warned()).toContain("APOLLO_INTERNAL_TOKEN");
  });

  it("does not warn about reusePort when the token came from the env", async () => {
    process.env.APOLLO_INTERNAL_TOKEN = "shared-token";
    const { logInternalTokenProvenance } = await freshInternalToken();
    logInternalTokenProvenance(true);
    expect(warned()).not.toContain("reusePort");
  });

  it("does not warn about reusePort when reusePort is off (minted token)", async () => {
    delete process.env.APOLLO_INTERNAL_TOKEN;
    const { logInternalTokenProvenance } = await freshInternalToken();
    logInternalTokenProvenance(false);
    expect(warned()).not.toContain("reusePort");
  });
});

// A URL that is syntactically fine and refuses instantly, so both startup paths
// take their failure branch without a database and without a timeout.
const UNREACHABLE_DB = "postgres://apollo:apollo@127.0.0.1:1/nope";

describe("Startup database failures reach Sentry", () => {
  const saved = process.env.APOLLO_CLIENTS_DB_URL;
  let error: ReturnType<typeof spyOn>;
  let capture: ReturnType<typeof spyOn>;
  let quiet: ReturnType<typeof spyOn>[];

  beforeEach(() => {
    process.env.APOLLO_CLIENTS_DB_URL = UNREACHABLE_DB;
    error = spyOn(console, "error").mockImplementation(() => {});
    quiet = [
      spyOn(console, "log").mockImplementation(() => {}),
      spyOn(console, "warn").mockImplementation(() => {}),
    ];
    capture = spyOn(sentry, "captureException");
    capture.mockClear();
  });

  afterEach(async () => {
    error.mockRestore();
    for (const spy of quiet) spy.mockRestore();
    capture.mockRestore();
    // Drop the pool opened against the unreachable URL so a later getDb()
    // reopens against whatever the next test configures.
    await closeDb().catch(() => {});
    if (saved === undefined) delete process.env.APOLLO_CLIENTS_DB_URL;
    else process.env.APOLLO_CLIENTS_DB_URL = saved;
  });

  const logged = () => error.mock.calls.map(([m]) => String(m)).join("\n");
  const capturedReasons = () =>
    capture.mock.calls.map(([, extras]: any) => extras?.reason);

  it("reports a migration run that could not reach the database", async () => {
    // Boots far enough to run migrations against the unreachable URL; the
    // throw is caught and the server still comes up.
    const auth = new InstanceAuth({ lookup: () => null, hasGlobalKey: true });
    await setup(9877, auth);

    expect(logged()).toContain("Apollo migrations failed to run.");
    expect(capturedReasons()).toContain("migrations-failed");
  }, 30000);

  it("reports a startup probe that could not reach the database", async () => {
    const auth = new InstanceAuth();
    await auth.init();

    expect(logged()).toContain("the database could not be reached");
    expect(capturedReasons()).toContain("db-unreachable");
  }, 30000);
});
