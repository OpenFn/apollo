import { describe, expect, it } from "bun:test";
import { hashToken } from "../src/auth/hash";
import vectors from "./fixtures/auth/hash-token-vectors.json";

// Pins the credential-hash trim contract: every whitespace-padded variant of the
// clean token must hash to the same digest. expected_hex is a hand-computed
// constant in the fixture (sha256 of the clean token's UTF-8 bytes), never derived
// from hashToken — so a regression in the function breaks CI rather than the test
// rubber-stamping it.
describe("hashToken trim contract", () => {
  for (const { label, input, expected_hex } of vectors.vectors) {
    it(`hashes "${label}" to the canonical digest`, () => {
      expect(hashToken(input)).toBe(expected_hex);
    });
  }

  it("treats every padded variant as the clean token (no whitespace drift)", () => {
    const clean = hashToken(vectors.clean_token);
    for (const { input } of vectors.vectors) {
      expect(hashToken(input)).toBe(clean);
    }
  });
});
