import { SQL } from "bun";
import { readdir } from "node:fs/promises";
import { join } from "node:path";
import { clientsDbUrl, closeDb, getDb } from "./index";

// Canonical migrations location. Each subdirectory holds the .sql files for one
// database, applied in lexical order; applied filenames are recorded in _migrations
// so re-runs are a no-op (the version table is the source of truth, not IF NOT
// EXISTS guards in the DDL). Python services never migrate: they expect this runner
// to have run.
const MIGRATIONS_DIR = join(import.meta.dir, "../../migrations");

// Fixed key for the transaction advisory lock that serialises the runner. Every
// instance uses the same key, so concurrent starters queue on it.
const MIGRATION_LOCK_KEY = 8314_2025;

export type MigrationTarget = "clients" | "docs";

// Applied in this order. Filenames are unique across targets, so both can share a
// _migrations table when APOLLO_CLIENTS_DB_URL falls back to POSTGRES_URL locally.
export const MIGRATION_TARGETS: MigrationTarget[] = ["clients", "docs"];

type Db = { sql: SQL; close: () => Promise<void> };

// clients: lightning_clients, on APOLLO_CLIENTS_DB_URL (falling back to POSTGRES_URL).
// docs: docsite tables and pgvector, on POSTGRES_URL.
const TARGET_URLS: Record<MigrationTarget, () => string | undefined> = {
  clients: clientsDbUrl,
  docs: () => process.env.POSTGRES_URL,
};

function openDb(target: MigrationTarget): Db {
  // The clients target uses the shared pool that the auth hook also holds.
  if (target === "clients") return { sql: getDb(), close: async () => {} };
  const sql = new SQL({ url: TARGET_URLS[target]()!, max: 1 });
  return { sql, close: () => sql.close() };
}

/** Whether the target has a database URL configured. */
export function hasTargetDb(target: MigrationTarget): boolean {
  return !!TARGET_URLS[target]();
}

/** Apply any of a target's migrations not yet recorded. Returns the count applied. */
export async function runMigrations(target: MigrationTarget): Promise<number> {
  const dir = join(MIGRATIONS_DIR, target);
  const files = (await readdir(dir)).filter((f) => f.endsWith(".sql")).sort();

  const db = openDb(target);
  try {
    return await db.sql.begin(async (tx) => {
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
    await db.close();
  }
}

export type MigrationResult = {
  target: MigrationTarget;
  applied?: number;
  skipped?: string;
  error?: unknown;
};

/**
 * Run every target that has a database configured. A failure in one target is
 * reported rather than thrown, so it can't block the others: the docs target needs
 * pgvector, which many instances don't have and don't need.
 */
export async function runAllMigrations(): Promise<MigrationResult[]> {
  const results: MigrationResult[] = [];
  for (const target of MIGRATION_TARGETS) {
    if (!hasTargetDb(target)) {
      results.push({ target, skipped: "no database URL set" });
      continue;
    }
    try {
      results.push({ target, applied: await runMigrations(target) });
    } catch (error) {
      results.push({ target, error });
    }
  }
  return results;
}

// Standalone entrypoint: `bun run migrate` applies every schema (lightning_clients,
// the docsite tables, and the _migrations tracking table) and exits. The server
// startup call (server.ts) is unaffected: import.meta.main is false there.
if (import.meta.main) {
  if (!clientsDbUrl() && !process.env.POSTGRES_URL) {
    console.error(
      "No database URL is set; nothing to migrate against. Set APOLLO_CLIENTS_DB_URL and/or\n" +
        "POSTGRES_URL to the instance you're migrating, and run from the repo root so Bun\n" +
        "reads .env."
    );
    process.exit(1);
  }
  try {
    for (const r of await runAllMigrations()) {
      if (r.error) {
        console.error(`Migration failed (${r.target}):`, (r.error as any)?.message ?? r.error);
        process.exitCode = 1;
      } else if (r.skipped) {
        console.log(`Skipped ${r.target} migrations: ${r.skipped}`);
      } else {
        console.log(`Applied ${r.applied} ${r.target} migration(s)`);
      }
    }
  } finally {
    await closeDb();
  }
}
