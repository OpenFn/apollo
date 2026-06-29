import { createHash } from "node:crypto";

/** SHA-256 hex of a client credential. Trimmed before hashing so a copy-paste
 *  newline or stray space hashes to the same value as the clean credential. */
export function hashToken(token: string): string {
  return createHash("sha256").update(token.trim()).digest("hex");
}
