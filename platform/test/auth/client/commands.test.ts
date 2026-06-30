import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import { randomBytes } from "node:crypto";
import { closeDb, getDb } from "../../../src/db";
import { runMigrations } from "../../../src/db/migrate";
import { hashToken } from "../../../src/auth/hash";
import { decryptKey, encryptKey } from "../../../src/util/instance-key-crypto";
import { InstanceAuth, type Client } from "../../../src/auth/instance-auth";
import { getClientByName } from "../../../src/auth/client/store";
import {
  ClientNotFoundError,
  addClient,
  classifyStoredKey,
  encryptValue,
  rotateClient,
  verifyClient,
} from "../../../src/auth/client/commands";

// A fake `sql` tagged-template that records each call's text and bound values, so
// add/rotate's mint->hash->encrypt key-prep is testable up to the SQL call with no
// DB. UPDATE ... RETURNING reads back `updateRows`; everything else resolves empty.
function captureSql(updateRows: Array<{ name: string }> = [{ name: "x" }]) {
  const calls: Array<{ text: string; values: unknown[] }> = [];
  const fn = (strings: TemplateStringsArray, ...values: unknown[]) => {
    const text = strings.join(" ? ");
    calls.push({ text, values });
    return Promise.resolve(/RETURNING/.test(text) ? updateRows : undefined);
  };
  return Object.assign(fn, { calls });
}

describe("client/commands key-prep (no DB)", () => {
  it("addClient mints, sha256-hashes the api_key, and encrypts the Anthropic key", async () => {
    const encKey = randomBytes(32);
    const sql = captureSql();
    const { apiKey } = await addClient(sql as any, encKey, "acme", "sk-ant-secret");

    expect(sql.calls).toHaveLength(1);
    const [{ text, values }] = sql.calls;
    expect(text).toContain("INSERT INTO lightning_clients");
    expect(values[0]).toBe("acme");
    expect(values[1]).toBe(hashToken(apiKey)); // auth_token_hash is sha256 of the minted key
    expect((values[2] as string).startsWith("enc:v1:")).toBe(true);
    expect(decryptKey(values[2] as string, encKey)).toBe("sk-ant-secret");
  });

  it("rotateClient updates only anthropic_api_key, never the api_key/auth_token_hash", async () => {
    const encKey = randomBytes(32);
    const sql = captureSql([{ name: "acme" }]);
    await rotateClient(sql as any, encKey, "acme", "sk-ant-new");

    expect(sql.calls).toHaveLength(1);
    const [{ text, values }] = sql.calls;
    expect(text).toContain("UPDATE lightning_clients");
    expect(text).toContain("anthropic_api_key");
    expect(text).not.toContain("auth_token_hash"); // the credential is left in place
    expect(decryptKey(values[0] as string, encKey)).toBe("sk-ant-new");
    expect(values[1]).toBe("acme");
  });

  it("rotateClient throws ClientNotFoundError when no row matches", async () => {
    const sql = captureSql([]); // UPDATE matched nothing
    await expect(
      rotateClient(sql as any, randomBytes(32), "ghost", "sk-ant-x")
    ).rejects.toBeInstanceOf(ClientNotFoundError);
  });

  it("encryptValue round-trips through decryptKey", () => {
    const encKey = randomBytes(32);
    const blob = encryptValue(encKey, "sk-ant-plain");
    expect(blob.startsWith("enc:v1:")).toBe(true);
    expect(decryptKey(blob, encKey)).toBe("sk-ant-plain");
  });
});

describe("client/commands classifyStoredKey (no DB)", () => {
  const encKey = randomBytes(32);

  it("NULL -> no_key", () => {
    expect(classifyStoredKey(null, encKey)).toBe("no_key");
  });
  it("a non-enc value -> plaintext", () => {
    expect(classifyStoredKey("sk-ant-plain", encKey)).toBe("plaintext");
  });
  it("an enc:v1: value the key decrypts -> decrypts", () => {
    expect(classifyStoredKey(encryptKey("x", encKey), encKey)).toBe("decrypts");
  });
  it("an enc:v1: value with the wrong key -> decrypt_failed", () => {
    expect(classifyStoredKey(encryptKey("x", encKey), randomBytes(32))).toBe("decrypt_failed");
  });
  it("an enc:v1: value with no key -> decrypt_failed", () => {
    expect(classifyStoredKey(encryptKey("x", encKey), null)).toBe("decrypt_failed");
  });
  it("a corrupt enc:v1: blob -> decrypt_failed", () => {
    const good = encryptKey("x", encKey);
    expect(classifyStoredKey(good.slice(0, -4) + "AAAA", encKey)).toBe("decrypt_failed");
  });
});

// The security-critical invariant: what add writes is exactly what the auth hook
// looks up. Drive addClient's captured output through the auth hook's real resolution path and
// assert it recovers the plaintext key.
describe("addClient -> auth-hook resolution (no DB)", () => {
  // An InstanceAuth whose lookup knows exactly the one row addClient wrote.
  function gatedFor(encKey: Buffer, authTokenHash: string, storedKey: string) {
    const auth = new InstanceAuth({ encKey });
    const clients: Record<string, Client | null> = {
      [authTokenHash]: auth.rowToClient({ name: "acme", anthropic_api_key: storedKey }),
    };
    return new InstanceAuth({ encKey, lookup: (hash) => clients[hash] ?? null });
  }
  const ctxFor = (apiKey: string): any => ({
    request: { headers: { get: () => null } },
    body: { api_key: apiKey },
    set: { status: 200 },
  });

  it("what addClient writes resolves back through the auth hook to the stored key", async () => {
    const encKey = randomBytes(32);
    const sql = captureSql();
    const { apiKey } = await addClient(sql as any, encKey, "acme", "sk-ant-provisioned-secret");
    const [{ values }] = sql.calls;
    const gated = gatedFor(encKey, values[1] as string, values[2] as string);

    const ctx = ctxFor(apiKey);
    await gated.authenticate(ctx);
    expect(ctx.lightningClient?.name).toBe("acme");
    expect(gated.resolveKey(ctx)).toEqual({ kind: "useKey", key: "sk-ant-provisioned-secret" });
  });

  it("a different api_key does not resolve the provisioned client and is rejected", async () => {
    const encKey = randomBytes(32);
    const sql = captureSql();
    await addClient(sql as any, encKey, "acme", "sk-ant-secret");
    const [{ values }] = sql.calls;
    const gated = gatedFor(encKey, values[1] as string, values[2] as string);

    // The lookup completes and confirms no such client, so the present-but-unknown
    // key is rejected outright (401).
    const ctx = ctxFor("sk-ant-some-other-key");
    await gated.authenticate(ctx);
    expect(ctx.lightningClient).toBeUndefined();
    expect(ctx.set.status).toBe(401);
  });
});

// Live-DB tier: the end-to-end add/rotate/verify path against real Postgres.
const hasDb = !!process.env.POSTGRES_URL;
const describeDb = hasDb ? describe : describe.skip;

if (!hasDb) {
  console.log("commands.test.ts: POSTGRES_URL unset — skipping live-DB tests (run in CI).");
}

describeDb("client/commands end-to-end (live DB)", () => {
  beforeAll(async () => {
    await runMigrations();
  });

  afterAll(async () => {
    await getDb()`DELETE FROM lightning_clients WHERE name LIKE 'client-test-%'`;
    await closeDb();
  });

  const testName = () => `client-test-${randomBytes(6).toString("hex")}`;

  it("add inserts an encrypted row; rotate replaces the key but keeps the credential", async () => {
    const encKey = randomBytes(32);
    const name = testName();

    const { apiKey } = await addClient(getDb(), encKey, name, "sk-ant-e2e-1");
    expect(apiKey).toBeTruthy();

    const row1 = await getClientByName(getDb(), name);
    expect(row1?.anthropic_api_key?.startsWith("enc:v1:")).toBe(true);
    expect(decryptKey(row1!.anthropic_api_key!, encKey)).toBe("sk-ant-e2e-1");
    const hashBefore = row1?.auth_token_hash;

    await rotateClient(getDb(), encKey, name, "sk-ant-e2e-2");
    const row2 = await getClientByName(getDb(), name);
    expect(decryptKey(row2!.anthropic_api_key!, encKey)).toBe("sk-ant-e2e-2");
    expect(row2?.auth_token_hash).toBe(hashBefore); // unchanged across rotate
  });

  it("verifyClient classifies a stored row and an unknown name", async () => {
    const encKey = randomBytes(32);
    expect(await verifyClient(getDb(), encKey, testName())).toBe("unknown_client");

    const name = testName();
    await addClient(getDb(), encKey, name, "sk-ant-verify");
    expect(await verifyClient(getDb(), encKey, name)).toBe("decrypts");
    expect(await verifyClient(getDb(), randomBytes(32), name)).toBe("decrypt_failed");
  });
});
