import { parseEncKey } from "../util/instance-key-crypto";

// Shared APOLLO_ENC_KEY guard for the client CLI (auth/client/). The auth hook
// calls parseEncKey directly (it must degrade, not exit), so the exiting behaviour
// lives here, sourced from one place so every subcommand emits the same message.

/** Parse APOLLO_ENC_KEY into a 32-byte key, or print an actionable error and exit. */
export function requireEncKey(raw: string | undefined | null): Buffer {
  const key = parseEncKey(raw);
  if (key) return key;
  console.error(
    "APOLLO_ENC_KEY not found (needs to be base64 of exactly 32 bytes; it\n" +
      "encrypts the Anthropic key).\n\n" +
      "Run this from the repo root so Bun picks up .env. If it's still missing,\n" +
      "the key isn't in .env yet. Add one with:\n\n" +
      '  echo "APOLLO_ENC_KEY=$(openssl rand -base64 32)" >> .env\n\n' +
      "then re-run (and restart Apollo so it can decrypt at runtime)."
  );
  process.exit(1);
}
