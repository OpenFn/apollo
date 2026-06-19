// AES-256-GCM helpers for the per-client anthropic_api_key in lightning_clients.
// Shared by the auth middleware (decrypt) and encrypt_key.ts (encrypt) so the byte
// format can't drift. Stored format: "enc:v1:<base64(iv(12) || tag(16) ||
// ciphertext)>"; master key is APOLLO_ENC_KEY (base64 of 32 bytes). Values without
// the prefix are treated as legacy plaintext elsewhere, so encryption is opt-in.
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

export const ENC_PREFIX = "enc:v1:";
const IV_BYTES = 12; // GCM nonce
const TAG_BYTES = 16; // GCM auth tag

/** Decode APOLLO_ENC_KEY (base64 of exactly 32 bytes) into a key Buffer, or null if absent/malformed. */
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

/** Decrypt an "enc:v1:…" value; throws on wrong key, corrupt value, or failed auth tag. */
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
