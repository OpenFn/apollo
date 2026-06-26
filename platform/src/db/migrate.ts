import { readdir } from "node:fs/promises";
import { join } from "node:path";
import { clientsDbUrl, closeDb, getDb } from "./index";

// Canonical migrations location. .sql files here are applied in lexical order;
// applied filenames are recorded in _migrations so re-runs are a no-op (the
// version table is the source of truth, not IF NOT EXISTS guards in the DDL).
const MIGRATIONS_DIR = join(import.meta.dir, "../../migrations");

// Fixed key for the session/xact advisory lock that serialises the runner.
// Every instance uses the same key, so concurrent starters queue on it.
const MIGRATION_LOCK_KEY = 8314_2025;

/** Apply any migrations not yet recorded. Returns the count applied this run. */
export async function runMigrations(): Promise<number> {
  const sql = getDb();

  const files = (await readdir(MIGRATIONS_DIR))
    .filter((f) => f.endsWith(".sql"))
    .sort();

  return await sql.begin(async (tx) => {
    // Hold an advisory lock for the whole transaction: a racing instance waits
    // here, then sees the migrations already recorded rather than colliding on
    // CREATE TABLE. The lock releases automatically when the transaction ends.
    await tx`SELECT pg_advisory_xact_lock(${MIGRATION_LOCK_KEY})`;

    await tx`
      CREATE TABLE IF NOT EXISTS _migrations (
        filename   TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
      )
    `;

    const applied = (await tx`SELECT filename FROM _migrations`) as Array<{
      filename: string;
    }>;
    const done = new Set(applied.map((r) => r.filename));

    const pending = files.filter((f) => !done.has(f));
    for (const file of pending) {
      const ddl = await Bun.file(join(MIGRATIONS_DIR, file)).text();
      await tx.unsafe(ddl);
      await tx`INSERT INTO _migrations (filename) VALUES (${file})`;
    }

    return pending.length;
  });
}

// Standalone entrypoint: `bun run migrate` applies the platform/auth schema
// (lightning_clients, _migrations) and exits. The Python services own and
// self-initialise their own table, so this deliberately does not touch it. The
// server startup call (server.ts) is unaffected: import.meta.main is false there.
if (import.meta.main) {
  if (!clientsDbUrl()) {
    console.error(
      "No clients DB URL is set; nothing to migrate against. Set APOLLO_CLIENTS_DB_URL\n" +
        "(or POSTGRES_URL) to the instance you're migrating, and run from the repo root so\n" +
        "Bun reads .env."
    );
    process.exit(1);
  }
  try {
    const applied = await runMigrations();
    console.log(`Applied ${applied} platform migration(s) (lightning_clients, _migrations).`);
  } catch (err: any) {
    console.error("Migration failed:", err?.message ?? err);
    process.exitCode = 1;
  } finally {
    await closeDb();
  }
}
