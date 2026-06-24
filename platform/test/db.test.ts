import { afterAll, describe, expect, it } from "bun:test";
import { closeDb, getDb } from "../src/db";
import { runMigrations } from "../src/db/migrate";

// Real-connection coverage: no mock. Runs only when POSTGRES_URL points at a live
// database (set in CI against a Postgres service container). Skipped offline so
// `bun test` stays usable locally without Postgres.
const hasDb = !!process.env.POSTGRES_URL;
const describeDb = hasDb ? describe : describe.skip;

if (!hasDb) {
  console.log(
    "db.test.ts: POSTGRES_URL unset — skipping real-connection DB tests (they run in CI)."
  );
}

describeDb("DB helper (real connection)", () => {
  afterAll(async () => {
    await closeDb();
  });

  it("getDb() opens a connection and runs SELECT 1", async () => {
    const rows = (await getDb()`SELECT 1 AS one`) as Array<{ one: number }>;
    expect(rows[0]?.one).toBe(1);
  });

  it("runMigrations() creates lightning_clients with the expected columns", async () => {
    await runMigrations();

    const cols = (await getDb()`
      SELECT column_name FROM information_schema.columns
      WHERE table_name = 'lightning_clients'
    `) as Array<{ column_name: string }>;
    const names = new Set(cols.map((c) => c.column_name));

    expect(names.has("id")).toBe(true);
    expect(names.has("name")).toBe(true);
    expect(names.has("auth_token_hash")).toBe(true);
    expect(names.has("anthropic_api_key")).toBe(true);
  });

  it("runMigrations() is idempotent against an already-provisioned database", async () => {
    const applied = await runMigrations();
    expect(applied).toBe(0);
  });
});
