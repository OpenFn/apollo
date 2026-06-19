// Provision a Lightning client in one step: mint an api_key credential, hash it
// (auth_token_hash), and encrypt the Anthropic key (enc:v1:…). Prints all three
// plus a ready-to-run INSERT. Run from the repo root so Bun loads .env (APOLLO_ENC_KEY):
//   bun services/_instance_auth/provision_client.ts <client-name> <sk-ant-...>
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

const apiKey = randomBytes(32).toString("base64url");
const authTokenHash = createHash("sha256").update(apiKey).digest("hex");
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
