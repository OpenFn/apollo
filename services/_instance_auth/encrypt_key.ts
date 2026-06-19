// Encrypt an Anthropic API key for the lightning_clients.anthropic_api_key
// column, so the key is not stored in the clear. Run from the repo root so Bun
// auto-loads .env (that's where APOLLO_ENC_KEY lives); running from anywhere else
// won't pick up .env and the script will say so:
//
//   bun services/_instance_auth/encrypt_key.ts <sk-ant-...>
//
// Prints the "enc:v1:…" value to store plus a ready-to-edit INSERT. Apollo
// decrypts it on cache load using the same APOLLO_ENC_KEY (see
// platform/src/middleware/auth.ts).
import { encryptKey, parseEncKey } from "../../platform/src/util/instance-key-crypto";

const plaintext = process.argv[2];
if (!plaintext) {
  console.error(
    "Usage: bun services/_instance_auth/encrypt_key.ts <anthropic-api-key>\n" +
      "(run from the repo root so APOLLO_ENC_KEY is read from .env)"
  );
  process.exit(1);
}

// Bun auto-loads .env, but only from the directory it's run in. If the key is
// missing it's almost always because this wasn't run from the repo root.
const key = parseEncKey(process.env.APOLLO_ENC_KEY);
if (!key) {
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

const enc = encryptKey(plaintext, key);

console.log(enc);
console.log();
console.log("Example INSERT (set name and the hash from hash_token.py):\n");
console.log(
  "  INSERT INTO lightning_clients (name, auth_token_hash, anthropic_api_key)\n" +
    `  VALUES ('my-instance', '<auth_token_hash>', '${enc}');`
);
