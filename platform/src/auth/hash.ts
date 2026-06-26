import { createHash } from "node:crypto";

/** SHA-256 hex of a client credential, computed over its UTF-8 bytes. This is the
 *  one definition of the hash contract: provisioning writes it, the auth hook looks
 *  it up. Apollo is TS-only on this path, so there is no cross-language duplicate.
 *
 *  Trims leading and trailing whitespace before hashing. The credential is its
 *  trimmed form: a token minted with `randomBytes(32).toString("base64url")` has
 *  no whitespace, so trim is identity for every stored hash, but a copy-paste
 *  newline or stray space at either call site can no longer split the contract. */
export function hashToken(token: string): string {
  return createHash("sha256").update(token.trim()).digest("hex");
}
