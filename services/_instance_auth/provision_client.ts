// Provision a Lightning client for the lightning_clients allow-list in ONE step.
// Given a client name and an Anthropic API key, this:
//   1. mints a fresh api_key credential for the Lightning instance to send,
//   2. computes its SHA-256 hash (what gets stored as auth_token_hash), and
//   3. encrypts the Anthropic key into an "enc:v1:…" value (AES-256-GCM).
// It then prints all three plus a ready-to-run psql INSERT.
//
// Run from the repo root so Bun auto-loads .env (that's where APOLLO_ENC_KEY
// lives). Running from anywhere else won't pick up .env and the script will say so:
//
//   bun services/_instance_auth/provision_client.ts <client-name> <sk-ant-...>
//
// The minted api_key goes to the Lightning instance (it sends it as `api_key`).
// Everything else goes into the DB. The hash here matches the one Apollo computes
// in platform/src/middleware/auth.ts, and the encryption reuses the same crypto
// module Apollo decrypts with, so the formats can never drift.
import { createHash, randomBytes } from "node:crypto";
import { encryptKey, parseEncKey } from "../../platform/src/util/instance-key-crypto";

const name = process.argv[2];
const anthropicKey = process.argv[3];

if (!name || !anthropicKey) {
  console.error(
    "Usage: APOLLO_ENC_KEY=<base64-32-bytes> \\\n" +
      "  bun services/_instance_auth/provision_client.ts <client-name> <anthropic-api-key>\n\n" +
      "Tip: `set -a; . ./.env; set +a;` first to load APOLLO_ENC_KEY from .env."
  );
  process.exit(1);
}

// Bun auto-loads .env, but only from the directory it's run in. If the key is
// missing it's almost always because this wasn't run from the repo root.
const encKey = parseEncKey(process.env.APOLLO_ENC_KEY);
if (!encKey) {
  console.error(
    "APOLLO_ENC_KEY not found (needs to be base64 of exactly 32 bytes — it\n" +
      "encrypts the Anthropic key).\n\n" +
      "Run this from the repo root so Bun picks up .env. If it's still missing,\n" +
      "the key isn't in .env yet — add one with:\n\n" +
      '  echo "APOLLO_ENC_KEY=$(openssl rand -base64 32)" >> .env\n\n' +
      "then re-run (and restart Apollo so it can decrypt at runtime)."
  );
  process.exit(1);
}

// 1. The credential Lightning sends as `api_key`. URL-safe so it travels cleanly.
const apiKey = randomBytes(32).toString("base64url");
// 2. What we store: the SHA-256 hash (lowercase hex over UTF-8 bytes).
const authTokenHash = createHash("sha256").update(apiKey).digest("hex");
// 3. The Anthropic key, encrypted at rest.
const encAnthropic = encryptKey(anthropicKey, encKey);

const sqlName = name.replace(/'/g, "''");
const insert =
  "INSERT INTO lightning_clients (name, auth_token_hash, anthropic_api_key)\n" +
  `  VALUES ('${sqlName}', '${authTokenHash}', '${encAnthropic}');`;

console.log(`\n✅ Provisioned client "${name}"\n`);
console.log("1. Lightning api_key — give this to the instance (it sends it as `api_key`):");
console.log(`   ${apiKey}\n`);
console.log("2. auth_token_hash — stored in the DB:");
console.log(`   ${authTokenHash}\n`);
console.log("3. anthropic_api_key (encrypted) — stored in the DB:");
console.log(`   ${encAnthropic}\n`);
console.log("Run this to insert the row (from the repo root):\n");
console.log(
  `  set -a; . ./.env; set +a; psql "$POSTGRES_URL" -c "${insert.replace(/\n\s*/g, " ")}"\n`
);
console.log("Or paste the INSERT directly:\n");
console.log(`  ${insert}\n`);
