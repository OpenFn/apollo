import { Elysia } from "elysia";

import setupDir from "./middleware/dir";
import setupHealthcheck from "./middleware/healthcheck";
import setupServices from "./middleware/services";
import { html } from "@elysiajs/html";
import logRequest from "./util/log-request";
import { InstanceAuth } from "./auth/instance-auth";
import { logInternalTokenProvenance } from "./auth/internal-token";
import { captureException } from "./util/sentry";
import { clientsDbUrl, closeDb } from "./db";
import { runMigrations } from "./db/migrate";
import { randomUUID } from "node:crypto";
import { readdir, rm } from "node:fs/promises";
import path from "node:path";

// A run's input file can hold values that belong to the deployment rather
// than the caller, and only the bridge's close handler removes it - so
// anything that stopped the process mid-run left one behind, and nothing else
// ever sweeps them. Startup is the one moment we know no run of ours is
// reading them.
const sweepTempPayloads = async () => {
  const dir = path.resolve("tmp/data");

  try {
    const stale = await readdir(dir);

    await Promise.all(
      stale.map((name) => rm(path.join(dir, name), { force: true }))
    );

    if (stale.length) {
      console.log(`Removed ${stale.length} temp payload(s) left by a previous run`);
    }
  } catch (error) {
    // No directory yet on a first boot, which is not worth reporting.
    if ((error as { code?: string }).code !== "ENOENT") {
      console.error("Could not sweep tmp/data", error);
    }
  }
};
import pkg from "../../package.json";

export default async (
  port: number | string = 3000,
  // One instance per process, shared by the auth hook and the key resolver. Tests
  // pass a pre-configured instance (fake lookup) instead of the live DB-backed one.
  auth: InstanceAuth = new InstanceAuth()
) => {
  // Bun's idle timer applies to in-flight SSE responses, not just idle
  // keep-alive sockets, and Elysia defaults it to 30s - shorter than our own
  // services routinely go without emitting. 255 is Bun's maximum.
  const app = new Elysia({
    serve: {
      idleTimeout: 255,
    },
    // Websockets have their own idle timer, which serve.idleTimeout does not
    // reach - it defaults to 120s, so a WS caller waiting on a slow answer
    // would be dropped well before the SSE route's heartbeat had earned it
    // anything.
    websocket: {
      idleTimeout: 255,
    },
  });

  app.use(html());

  app.derive(() => ({ start: Date.now(), uuid: randomUUID() }));
  app.onAfterHandle(({ set }) => { set.headers["X-Api-Version"] = pkg.version; });
  app.onAfterHandle(logRequest);

  // Report unhandled throws to Sentry, then return nothing so Elysia produces
  // its normal error response (returning a value would replace the body/status).
  app.onError(({ error }) => {
    captureException(error);
  });

  await setupHealthcheck(app);
  await setupDir(app);
  await setupServices(app, +port, auth);

  // Bring the schema up to date before auth probes it. Without a clients DB URL
  // there is nothing to migrate; auth.init() then handles the fail-closed path on
  // its own.
  if (clientsDbUrl()) {
    try {
      const applied = await runMigrations();
      console.log(
        applied > 0 ? `${applied} migration(s) applied.` : "Schema up to date."
      );
    } catch (err) {
      console.error("Apollo migrations failed to run.", err);
    }
  }

  // Elysia's Bun adapter sets reusePort unconditionally, so the guard that
  // warns about a per-process token meeting a shared port is live, not
  // hypothetical. It stays quiet once APOLLO_INTERNAL_TOKEN is set.
  logInternalTokenProvenance(true);
  await sweepTempPayloads();
  await auth.init();

  // No stop path exists otherwise; close the DB pool so a graceful pod termination
  // (or Ctrl-C in dev) exits cleanly without orphaned Postgres connections. In-flight
  // requests, open SSE streams, and spawned Python children are intentionally not
  // drained — termination drops them rather than waiting them out.
  const shutdown = async () => {
    await closeDb();
    process.exit(0);
  };
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);

  console.log("Apollo Server listening on ", port);
  app.listen(port);

  return app;
};
