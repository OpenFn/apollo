// AES-256-GCM helpers for the per-client anthropic_api_key stored in
// lightning_clients. Used by the auth middleware (to decrypt on cache load) and
// by services/_instance_auth/encrypt_key.ts (to produce values to INSERT). Kept
// in one module so the byte format can never drift between the two sides.
//
// Stored format: "enc:v1:<base64(iv(12) || tag(16) || ciphertext)>". The master
// key is APOLLO_ENC_KEY (base64 of 32 bytes). Anything NOT prefixed with the
// tag is treated as legacy plaintext elsewhere, so encryption is opt-in and
// backward compatible.
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

export const ENC_PREFIX = "enc:v1:";
const IV_BYTES = 12; // GCM standard nonce length
const TAG_BYTES = 16; // GCM auth tag length

/**
 * Decode APOLLO_ENC_KEY (base64 of exactly 32 bytes) into a key Buffer, or null
 * if it is absent or malformed. Callers treat null as "no key configured".
 */
export function parseEncKey(raw: string | undefined | null): Buffer | null {
  if (!raw) return null;
  let buf: Buffer;
  try {
    buf = Buffer.from(raw.trim(), "base64");
  } catch {
    return null;
  }
  return buf.length === 32 ? buf : null;
}

/** Encrypt plaintext into an "enc:v1:…" value using AES-256-GCM. */
export function encryptKey(plaintext: string, key: Buffer): string {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const ciphertext = Buffer.concat([
    cipher.update(plaintext, "utf8"),
    cipher.final(),
  ]);
  const tag = cipher.getAuthTag();
  return ENC_PREFIX + Buffer.concat([iv, tag, ciphertext]).toString("base64");
}

/**
 * Decrypt an "enc:v1:…" value. Throws if the key is wrong, the value is
 * corrupt, or the auth tag fails — callers decide how to handle the failure
 * (the auth middleware omits the client and fails closed).
 */
export function decryptKey(stored: string, key: Buffer): string {
  const blob = Buffer.from(stored.slice(ENC_PREFIX.length), "base64");
  const iv = blob.subarray(0, IV_BYTES);
  const tag = blob.subarray(IV_BYTES, IV_BYTES + TAG_BYTES);
  const ciphertext = blob.subarray(IV_BYTES + TAG_BYTES);
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString(
    "utf8"
  );
}
