import { describe, expect, it } from "bun:test";
import { randomBytes } from "node:crypto";
import {
  ENC_PREFIX,
  decryptKey,
  encryptKey,
  parseEncKey,
} from "../../src/util/instance-key-crypto";

// Pure-function coverage for the at-rest key crypto provisioning depends on: the
// encrypt/decrypt round-trip a stored anthropic_api_key survives, and parseEncKey's
// accept/reject contract. No fakes needed.
describe("instance-key-crypto round-trip", () => {
  it("decryptKey(encryptKey(x)) === x for arbitrary inputs", () => {
    const key = randomBytes(32);
    for (const plain of [
      "sk-ant-abc123",
      "",
      "a key with spaces and \n newlines",
      "unicode: key — café 🔑",
      randomBytes(64).toString("base64"),
    ]) {
      expect(decryptKey(encryptKey(plain, key), key)).toBe(plain);
    }
  });

  it("tags ciphertext with the enc:v1: prefix", () => {
    expect(encryptKey("sk-ant-secret", randomBytes(32))).toStartWith(ENC_PREFIX);
  });

  it("produces a different ciphertext each call (random IV) that still decrypts", () => {
    const key = randomBytes(32);
    const a = encryptKey("sk-ant-secret", key);
    const b = encryptKey("sk-ant-secret", key);
    expect(a).not.toBe(b);
    expect(decryptKey(a, key)).toBe("sk-ant-secret");
    expect(decryptKey(b, key)).toBe("sk-ant-secret");
  });

  it("fails to decrypt with the wrong key", () => {
    const enc = encryptKey("sk-ant-secret", randomBytes(32));
    expect(() => decryptKey(enc, randomBytes(32))).toThrow();
  });
});

describe("parseEncKey accept/reject contract", () => {
  it("returns a 32-byte Buffer for base64 of exactly 32 bytes", () => {
    const raw = randomBytes(32).toString("base64");
    const key = parseEncKey(raw);
    expect(key).not.toBeNull();
    expect(key?.length).toBe(32);
  });

  it("returns null for undefined / null / empty", () => {
    expect(parseEncKey(undefined)).toBeNull();
    expect(parseEncKey(null)).toBeNull();
    expect(parseEncKey("")).toBeNull();
  });

  it("returns null for base64 that decodes to the wrong length", () => {
    expect(parseEncKey(randomBytes(16).toString("base64"))).toBeNull();
    expect(parseEncKey(randomBytes(31).toString("base64"))).toBeNull();
    expect(parseEncKey(randomBytes(33).toString("base64"))).toBeNull();
  });

  it("trims surrounding whitespace before decoding", () => {
    const raw = randomBytes(32).toString("base64");
    expect(parseEncKey(`  ${raw}\n`)?.length).toBe(32);
  });
});
