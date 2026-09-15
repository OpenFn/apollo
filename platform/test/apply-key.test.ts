import { describe, expect, it } from "bun:test";

import { applyResolvedKey } from "../src/middleware/services";

// What lands on the payload a service is about to run with.
//
// This used to be covered end to end: echo reflected its input, so a test
// could POST a credential and read the substituted value back off the
// response. Masking that reflection was right, and it took the proof with it —
// with everything coming back "[REDACTED]", a swap that wrote the wrong value,
// or forwarded the caller's own, would look identical to a correct one.
//
// So the assertion moved to the substitution itself. Paired with the
// InstanceAuth tests that pin which resolution a given credential produces,
// the two halves cover the same ground the round trip did, without a service
// having to hand a value back to prove it.
describe("applyResolvedKey", () => {
  const CALLER = "sk-ant-the-caller-sent-this";
  const STORED = "sk-ant-what-the-server-substitutes";

  it("substitutes the stored value for a known client", () => {
    const payload = applyResolvedKey(
      { x: 1, api_key: CALLER },
      { kind: "useKey", key: STORED }
    );

    expect(payload.api_key).toBe(STORED);
    expect(payload.x).toBe(1);
  });

  // The invariant the whole auth layer exists for.
  it("never forwards what the caller sent", () => {
    const payload = applyResolvedKey(
      { api_key: CALLER },
      { kind: "useKey", key: STORED }
    );

    expect(JSON.stringify(payload)).not.toContain(CALLER);
  });

  // Dropped rather than blanked: python falls back to the global key only when
  // the field is absent.
  it("drops the field entirely when the global key should serve", () => {
    const payload = applyResolvedKey(
      { x: 1, api_key: CALLER },
      { kind: "useGlobal" }
    );

    expect("api_key" in payload).toBe(false);
    expect(payload.x).toBe(1);
  });

  it("leaves an internal hop's body exactly as received", () => {
    const forwarded = "sk-ant-forwarded-by-an-internal-call";
    const payload = applyResolvedKey(
      { api_key: forwarded },
      { kind: "passthrough" }
    );

    expect(payload.api_key).toBe(forwarded);
  });

  // The default branch is an exhaustiveness guard: a new resolution kind must
  // fail loudly rather than fall through and forward the inbound credential.
  it("refuses a resolution it does not recognise", () => {
    expect(() =>
      applyResolvedKey({ api_key: CALLER }, { kind: "brand-new" } as never)
    ).toThrow(/unhandled KeyResolution/);
  });
});
