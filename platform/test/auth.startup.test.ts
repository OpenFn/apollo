import { afterEach, beforeEach, describe, expect, it, spyOn } from "bun:test";

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
