// The `client` CLI: provision and manage Lightning clients in lightning_clients.
// This is the only file with import.meta.main, so importing store/commands from a
// test never parses args or exits. Run from the repo root so Bun loads .env
// (APOLLO_ENC_KEY, and APOLLO_CLIENTS_DB_URL or POSTGRES_URL):
//
//   echo "$KEY"    | bun run client add acme       # mint + insert, prints the api_key
//   echo "$NEWKEY" | bun run client rotate acme     # replace the Anthropic key in place
//   echo "$KEY"    | bun run client encrypt          # print an enc:v1: blob, no DB write
//                    bun run client verify acme       # decrypt-check the stored key
//
// Keys are read from stdin (pipe or interactive prompt), never from argv. The
// client name is a positional argument (not secret).
import { clientsDbUrl, closeDb, getDb } from "../../db";
import { parseEncKey } from "../../util/instance-key-crypto";
import { requireEncKey } from "../enc-key";
import {
  ClientNotFoundError,
  addClient,
  encryptValue,
  rotateClient,
  verifyClient,
  type VerifyStatus,
} from "./commands";
import { readSecret } from "./read-secret";
import { UNIQUE_VIOLATION } from "./store";

// Pre-flight the DB-backed subcommands before a secret is read from stdin, so a
// missing DB URL surfaces this guidance rather than a generic failure after the
// operator has already piped/typed the key.
function requireDbUrl(): boolean {
  if (clientsDbUrl()) return true;
  console.error(
    "No clients DB URL is set; this reaches the database directly. Set APOLLO_CLIENTS_DB_URL\n" +
      "(or POSTGRES_URL) to the instance you're working against, and run from the repo root so\n" +
      "Bun reads .env."
  );
  return false;
}

function usage(): void {
  console.error(
    "Usage: bun run client <command>\n\n" +
      "  add <name>      mint a credential, encrypt the Anthropic key (stdin), insert the row\n" +
      "  rotate <name>   replace an existing client's Anthropic key (stdin), keeping its credential\n" +
      "  encrypt         print the enc:v1: blob for the key on stdin (no DB write)\n" +
      "  verify <name>   check the stored key decrypts under the current APOLLO_ENC_KEY\n\n" +
      "Keys are read from stdin: `echo \"$KEY\" | bun run client add acme`."
  );
}

async function runAdd(name?: string): Promise<number> {
  if (!name) {
    console.error("Usage: bun run client add <name>  (Anthropic key on stdin)");
    return 1;
  }
  if (!requireDbUrl()) return 1;
  const encKey = requireEncKey(process.env.APOLLO_ENC_KEY);
  const anthropicKey = await readSecret();
  if (!anthropicKey) {
    console.error("No key read from stdin.");
    return 1;
  }
  try {
    const { apiKey } = await addClient(getDb(), encKey, name, anthropicKey);
    console.log(`Provisioned client "${name}". Give this api_key to the Lightning instance:`);
    console.log(apiKey);
    return 0;
  } catch (err: any) {
    if (err?.errno === UNIQUE_VIOLATION) {
      console.error(`A client named "${name}" already exists. Use \`rotate\` to change its key.`);
    } else {
      console.error("add failed:", err?.message ?? err);
    }
    return 1;
  } finally {
    await closeDb();
  }
}

async function runRotate(name?: string): Promise<number> {
  if (!name) {
    console.error("Usage: bun run client rotate <name>  (new Anthropic key on stdin)");
    return 1;
  }
  if (!requireDbUrl()) return 1;
  const encKey = requireEncKey(process.env.APOLLO_ENC_KEY);
  const anthropicKey = await readSecret("New Anthropic key: ");
  if (!anthropicKey) {
    console.error("No key read from stdin.");
    return 1;
  }
  try {
    await rotateClient(getDb(), encKey, name, anthropicKey);
    console.log(`Rotated the Anthropic key for client "${name}". Its api_key is unchanged.`);
    return 0;
  } catch (err: any) {
    if (err instanceof ClientNotFoundError) {
      console.error(`No client named "${name}". Use \`add\` to create one.`);
    } else {
      console.error("rotate failed:", err?.message ?? err);
    }
    return 1;
  } finally {
    await closeDb();
  }
}

async function runEncrypt(): Promise<number> {
  const encKey = requireEncKey(process.env.APOLLO_ENC_KEY);
  const value = await readSecret();
  if (!value) {
    console.error("No value read from stdin.");
    return 1;
  }
  console.log(encryptValue(encKey, value));
  return 0;
}

function reportVerify(name: string, status: VerifyStatus): number {
  switch (status) {
    case "decrypts":
      console.log(`Client "${name}": anthropic_api_key decrypts cleanly (enc:v1:).`);
      return 0;
    case "plaintext":
      console.log(`Client "${name}": anthropic_api_key is stored as plaintext (used as-is).`);
      return 0;
    case "no_key":
      console.error(`Client "${name}": anthropic_api_key is NULL. This is an invalid (keyless) client row; the auth hook will reject every request with 500. Set a key with \`rotate\`.`);
      return 1;
    case "decrypt_failed":
      console.error(`Client "${name}": DECRYPT_FAILED. The stored enc:v1: key cannot be decrypted with the current APOLLO_ENC_KEY.`);
      return 1;
    case "unknown_client":
      console.error(`No client named "${name}".`);
      return 1;
  }
}

async function runVerify(name?: string): Promise<number> {
  if (!name) {
    console.error("Usage: bun run client verify <name>");
    return 1;
  }
  if (!requireDbUrl()) return 1;
  // parseEncKey (not requireEncKey): a missing key is a valid DECRYPT_FAILED
  // diagnosis for an encrypted row, and plaintext/NULL rows verify without one.
  const encKey = parseEncKey(process.env.APOLLO_ENC_KEY);
  try {
    return reportVerify(name, await verifyClient(getDb(), encKey, name));
  } catch (err: any) {
    console.error("verify failed:", err?.message ?? err);
    return 1;
  } finally {
    await closeDb();
  }
}

async function main(): Promise<number> {
  const [, , subcommand, name] = process.argv;
  switch (subcommand) {
    case "add":
      return runAdd(name);
    case "rotate":
      return runRotate(name);
    case "encrypt":
      return runEncrypt();
    case "verify":
      return runVerify(name);
    default:
      usage();
      return 1;
  }
}

if (import.meta.main) process.exit(await main());
