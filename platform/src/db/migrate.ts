import { SQL } from "bun";
import { readdir } from "node:fs/promises";
import { join } from "node:path";
import { clientsDbUrl } from "./index";

// List of supported connected databases as name:target
// Each key here must have a matching folder in migrations/ holding that
// database's .sql files.
// Needed because auth may be configured to use a different database
const dbs = {
  clients: clientsDbUrl, // lightning_clients
  services: () => process.env.POSTGRES_URL, // tables used by the Python services
};

export type MigrationDb = keyof typeof dbs;

const MIGRATIONS_DIR = join(import.meta.dir, "../../../migrations");

// Fixed key for the transaction advisory lock that serialises the runner. Every
// instance uses the same key, so concurrent starters queue on it.
const MIGRATION_LOCK_KEY = 8314_2025;

/**
 * Apply any of a database's migrations not yet recorded. Returns the count applied.
 * Applied filenames go in a _migrations table in that database, so re-runs are a
 * no-op (the table is the source of truth, not IF NOT EXISTS guards in the DDL).
 * Filenames are unique across folders, so two databases that are really one (local
 * dev) can share the table.
 */
export async function runMigrations(db: MigrationDb): Promise<number> {
  const url = dbs[db]();
  if (!url) throw new Error(`No database URL is set for the ${db} migrations`);

  const dir = join(MIGRATIONS_DIR, db);
  const files = (await readdir(dir)).filter((f) => f.endsWith(".sql")).sort();

  const sql = new SQL({ url, max: 1 });
  try {
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
        const ddl = await Bun.file(join(dir, file)).text();
        await tx.unsafe(ddl);
        await tx`INSERT INTO _migrations (filename) VALUES (${file})`;
      }

      return pending.length;
    });
  } finally {
    await sql.close();
  }
}

export type MigrationResult = {
  db: MigrationDb;
  applied?: number;
  skipped?: string;
  error?: unknown;
};

/**
 * Migrate every configured database. A failure is reported rather than thrown, so
 * one database can't block the others: the services one needs pgvector, which many
 * instances don't have and don't need.
 */
export async function runAllMigrations(): Promise<MigrationResult[]> {
  const results: MigrationResult[] = [];
  for (const key in dbs) {
    const db = key as MigrationDb;
    if (!dbs[db]()) {
      results.push({ db, skipped: "no database URL set" });
      continue;
    }
    try {
      results.push({ db, applied: await runMigrations(db) });
    } catch (error) {
      results.push({ db, error });
    }
  }
  return results;
}

// Standalone entrypoint: `bun run migrate` migrates every configured database and
// exits. The server startup call (server.ts) is unaffected: import.meta.main is
// false there.
if (import.meta.main) {
  const results = await runAllMigrations();
  if (results.every((r) => r.skipped)) {
    console.error(
      "No database URL is set; nothing to migrate against. Set APOLLO_CLIENTS_DB_URL and/or\n" +
        "POSTGRES_URL to the instance you're migrating, and run from the repo root so Bun\n" +
        "reads .env."
    );
    process.exit(1);
  }
  for (const r of results) {
    if (r.error) {
      console.error(
        `Migration failed (${r.db}):`,
        (r.error as any)?.message ?? r.error
      );
      process.exitCode = 1;
    } else if (r.skipped) {
      console.log(`Skipped ${r.db} migrations: ${r.skipped}`);
    } else {
      console.log(`Applied ${r.applied} ${r.db} migration(s)`);
    }
  }
}
