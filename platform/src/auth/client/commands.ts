import type { SQL } from "bun";
import { ENC_PREFIX, decryptKey, encryptKey } from "../../util/instance-key-crypto";
import { hashToken } from "../hash";
import {
  getClientByName,
  insertClient,
  mintApiKey,
  updateClientKey,
} from "./store";

// The four client operations as plain async functions: db handle + master key in,
// result out. No console, no process.exit, no argv; cli.ts owns all of that.
// Crypto and hashing are reused from instance-key-crypto.ts and hash.ts; nothing
// here reimplements them.

/** Thrown by rotateClient when no client carries the given name. cli.ts maps this
 *  to the "use add" message and a non-zero exit. */
export class ClientNotFoundError extends Error {
  constructor(public readonly clientName: string) {
    super(`unknown client "${clientName}"`);
    this.name = "ClientNotFoundError";
  }
}

/** Add a client: mint an api_key, hash it (auth_token_hash), encrypt the Anthropic
 *  key, and insert the row. Returns the minted api_key for the operator to hand to
 *  Lightning. Propagates Postgres errno 23505 on a duplicate name (cli.ts maps it). */
export async function addClient(
  sql: SQL,
  encKey: Buffer,
  name: string,
  anthropicKey: string
): Promise<{ apiKey: string }> {
  const apiKey = mintApiKey();
  const authTokenHash = hashToken(apiKey);
  const encAnthropic = encryptKey(anthropicKey, encKey);
  await insertClient(sql, name, authTokenHash, encAnthropic);
  return { apiKey };
}

/** Rotate a client's Anthropic key in place: encrypt the new key and UPDATE the
 *  row, leaving api_key/auth_token_hash untouched so Lightning keeps its
 *  credential. Throws ClientNotFoundError if the client doesn't exist. */
export async function rotateClient(
  sql: SQL,
  encKey: Buffer,
  name: string,
  anthropicKey: string
): Promise<void> {
  const encAnthropic = encryptKey(anthropicKey, encKey);
  const updated = await updateClientKey(sql, name, encAnthropic);
  if (updated === 0) throw new ClientNotFoundError(name);
}

/** Encrypt a value to its "enc:v1:…" form for manual SQL / row-seeding. No DB. */
export function encryptValue(encKey: Buffer, plaintext: string): string {
  return encryptKey(plaintext, encKey);
}

/** How a stored anthropic_api_key resolves under the current APOLLO_ENC_KEY. */
export type VerifyStatus =
  | "decrypts" // "enc:v1:…" that decrypts cleanly
  | "plaintext" // legacy plaintext, used as-is
  | "global" // NULL -> falls back to the global ANTHROPIC_API_KEY
  | "decrypt_failed" // "enc:v1:…" with no/wrong key or a corrupt blob
  | "unknown_client"; // no row by that name

/** Classify a stored value the same way instance-auth's decryptStoredKey does, but
 *  reporting the outcome instead of dropping the client. Pure; no DB. The branch
 *  order here (NULL -> global, no-prefix -> plaintext, no-key/decrypt-error ->
 *  fail) must track decryptStoredKey in instance-auth.ts: verify exists to predict
 *  the auth hook's behaviour, so the two cannot be allowed to diverge. */
export function classifyStoredKey(
  stored: string | null,
  encKey: Buffer | null
): VerifyStatus {
  if (stored === null) return "global";
  if (!stored.startsWith(ENC_PREFIX)) return "plaintext";
  if (!encKey) return "decrypt_failed";
  try {
    decryptKey(stored, encKey);
    return "decrypts";
  } catch {
    return "decrypt_failed";
  }
}

/** Operator-side decrypt check: look up the client by name and classify how its
 *  stored key resolves under the current APOLLO_ENC_KEY. */
export async function verifyClient(
  sql: SQL,
  encKey: Buffer | null,
  name: string
): Promise<VerifyStatus> {
  const row = await getClientByName(sql, name);
  if (!row) return "unknown_client";
  return classifyStoredKey(row.anthropic_api_key, encKey);
}
