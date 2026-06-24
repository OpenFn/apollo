import type { SQL } from "bun";
import { randomBytes } from "node:crypto";

// SQL and the small shared bits the client tooling needs. No console, no
// process.exit: callers (commands.ts/cli.ts) own I/O and exit codes. Each query
// takes the db handle as its first param, matching the rest of the app
// (getDb() is passed in rather than reached for here).

// Postgres unique_violation. A duplicate name is the path an operator actually
// hits on `add`; a duplicate hash is effectively impossible (random 32 bytes).
export const UNIQUE_VIOLATION = "23505";

/** Mint a client api_key credential: 32 random bytes, base64url. Same randomBytes
 *  source as internal-token.ts; base64url (not hex) is the established credential
 *  encoding the hash contract in hash.ts is computed over. */
export function mintApiKey(): string {
  return randomBytes(32).toString("base64url");
}

export type ClientRow = {
  name: string;
  auth_token_hash: string;
  anthropic_api_key: string | null;
};

/** Insert one client row. The name is bound as a parameter, so no value it can
 *  hold forms part of the SQL. Throws Postgres errno 23505 on a duplicate name. */
export async function insertClient(
  sql: SQL,
  name: string,
  authTokenHash: string,
  encAnthropicKey: string
): Promise<void> {
  await sql`
    INSERT INTO lightning_clients (name, auth_token_hash, anthropic_api_key)
    VALUES (${name}, ${authTokenHash}, ${encAnthropicKey})
  `;
}

/** Replace an existing client's encrypted Anthropic key in place, leaving
 *  api_key/auth_token_hash untouched so the Lightning side keeps its credential.
 *  Returns the number of rows updated (0 = no client by that name). */
export async function updateClientKey(
  sql: SQL,
  name: string,
  encAnthropicKey: string
): Promise<number> {
  const rows = (await sql`
    UPDATE lightning_clients SET anthropic_api_key = ${encAnthropicKey}
    WHERE name = ${name}
    RETURNING name
  `) as Array<{ name: string }>;
  return rows.length;
}

/** Look up one client row by name, or null if there is no such client. */
export async function getClientByName(
  sql: SQL,
  name: string
): Promise<ClientRow | null> {
  const rows = (await sql`
    SELECT name, auth_token_hash, anthropic_api_key
    FROM lightning_clients WHERE name = ${name} LIMIT 1
  `) as ClientRow[];
  return rows[0] ?? null;
}
