import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import { randomBytes } from "node:crypto";
import { closeDb, getDb } from "../../../src/db";
import { runMigrations } from "../../../src/db/migrate";
import { hashToken } from "../../../src/auth/hash";
import { encryptKey } from "../../../src/util/instance-key-crypto";
import {
  getClientByName,
  insertClient,
  mintApiKey,
  updateClientKey,
} from "../../../src/auth/client/store";

// Live-DB tier. Skipped when POSTGRES_URL is unset (as in db.test.ts) so `bun test`
// stays usable offline; runs against the postgres:16 service in CI.
const hasDb = !!process.env.POSTGRES_URL;
const describeDb = hasDb ? describe : describe.skip;

if (!hasDb) {
  console.log("store.test.ts: POSTGRES_URL unset — skipping live-DB tests (run in CI).");
}

describeDb("client/store (live DB)", () => {
  beforeAll(async () => {
    await runMigrations();
  });

  afterAll(async () => {
    await getDb()`DELETE FROM lightning_clients WHERE name LIKE 'client-test-%'`;
    await closeDb();
  });

  const testName = () => `client-test-${randomBytes(6).toString("hex")}`;

  it("insertClient writes a row that getClientByName reads back", async () => {
    const name = testName();
    const hash = hashToken(mintApiKey());
    const enc = encryptKey("sk-ant-stored", randomBytes(32));
    await insertClient(getDb(), name, hash, enc);

    const row = await getClientByName(getDb(), name);
    expect(row).not.toBeNull();
    expect(row?.auth_token_hash).toBe(hash);
    expect(row?.anthropic_api_key).toBe(enc);
  });

  it("a second insert of the same name throws the unique violation (23505)", async () => {
    const name = testName();
    await insertClient(getDb(), name, hashToken(mintApiKey()), encryptKey("sk-ant-a", randomBytes(32)));

    let errno: string | undefined;
    try {
      await insertClient(getDb(), name, hashToken(mintApiKey()), encryptKey("sk-ant-b", randomBytes(32)));
    } catch (err: any) {
      errno = err?.errno;
    }
    expect(errno).toBe("23505");
  });

  it("updateClientKey changes anthropic_api_key but leaves auth_token_hash untouched", async () => {
    const name = testName();
    const hash = hashToken(mintApiKey());
    const oldEnc = encryptKey("sk-ant-old", randomBytes(32));
    await insertClient(getDb(), name, hash, oldEnc);

    const newEnc = encryptKey("sk-ant-new", randomBytes(32));
    const updated = await updateClientKey(getDb(), name, newEnc);
    expect(updated).toBe(1);

    const row = await getClientByName(getDb(), name);
    expect(row?.anthropic_api_key).toBe(newEnc);
    expect(row?.auth_token_hash).toBe(hash); // the whole point of rotate
  });

  it("updateClientKey returns 0 for an unknown client", async () => {
    const updated = await updateClientKey(getDb(), testName(), encryptKey("sk-ant-x", randomBytes(32)));
    expect(updated).toBe(0);
  });
});
