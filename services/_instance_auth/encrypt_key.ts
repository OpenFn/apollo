// Encrypt an Anthropic API key for the lightning_clients.anthropic_api_key
// column, so the key is not stored in the clear. Run from the repo root:
//
//   APOLLO_ENC_KEY=<base64-32-bytes> \
//     bun services/_instance_auth/encrypt_key.ts <sk-ant-...>
//
// Prints the "enc:v1:…" value to store plus a ready-to-edit INSERT. Apollo
// decrypts it on cache load using the same APOLLO_ENC_KEY (see
// platform/src/middleware/auth.ts). Generate a key with: openssl rand -base64 32
import { encryptKey, parseEncKey } from "../../platform/src/util/instance-key-crypto";

const plaintext = process.argv[2];
if (!plaintext) {
  console.error(
    "Usage: APOLLO_ENC_KEY=<base64-32-bytes> bun services/_instance_auth/encrypt_key.ts <anthropic-api-key>"
  );
  process.exit(1);
}

const key = parseEncKey(process.env.APOLLO_ENC_KEY);
if (!key) {
  console.error(
    "APOLLO_ENC_KEY must be set to base64 of exactly 32 bytes.\n" +
      "Generate one with:  openssl rand -base64 32"
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
