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
import pkg from "../../package.json";

export default async (
  port: number | string = 3000,
  // One instance per process, shared by the auth hook and the key resolver. Tests
  // pass a pre-configured instance (fake lookup) instead of the live DB-backed one.
  auth: InstanceAuth = new InstanceAuth()
) => {
  const app = new Elysia();

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

  // app.listen below sets no reusePort, so the multi-process internal-token warn
  // is dormant; pass the flag here if clustering is ever enabled.
  logInternalTokenProvenance(false);
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
