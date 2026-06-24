import { SQL } from "bun";

// Shared JS-side Postgres handle. Every TS DB consumer (the auth hook, provisioning)
// imports getDb() rather than constructing its own SQL — one pool per process, with
// consistent config and a single close() for graceful shutdown.

// bun:sql's pool is unbounded by default; cap it so a burst of auth checks can't
// exhaust Postgres's connection limit.
const MAX_CONNECTIONS = 5;

let sql: SQL | null = null;

// The client-auth table (lightning_clients) can live in its own database, set via
// APOLLO_CLIENTS_DB_URL, so in staging/prod the credentials sit apart from the
// docs data on POSTGRES_URL. The fallback keeps local dev to one var: set only
// POSTGRES_URL and everything shares a single DB. Every TS DB consumer resolves the
// URL through here, so the two sides can't drift apart silently.
export function clientsDbUrl(): string | undefined {
  return process.env.APOLLO_CLIENTS_DB_URL ?? process.env.POSTGRES_URL;
}

/** Shared pooled connection, opened lazily on first call. See clientsDbUrl(). */
export function getDb(): SQL {
  if (sql) return sql;
  const url = clientsDbUrl();
  if (!url) {
    throw new Error(
      "Neither APOLLO_CLIENTS_DB_URL nor POSTGRES_URL is set; cannot open a database connection."
    );
  }
  console.log(
    process.env.APOLLO_CLIENTS_DB_URL
      ? "clients DB: using APOLLO_CLIENTS_DB_URL."
      : "clients DB: falling back to POSTGRES_URL."
  );
  sql = new SQL({ url, max: MAX_CONNECTIONS });
  return sql;
}

/** Close the shared pool and drop the handle so a later getDb() reopens cleanly. */
export async function closeDb(): Promise<void> {
  if (!sql) return;
  await sql.close();
  sql = null;
}
