import { Elysia } from "elysia";

import setupDir from "./middleware/dir";
import setupHealthcheck from "./middleware/healthcheck";
import setupServices from "./middleware/services";
import { html } from "@elysiajs/html";
import logRequest from "./util/log-request";
import {
  resolveClientLookupFromEnv,
  type ClientLookup,
} from "./middleware/client_keys";
import { randomUUID } from "node:crypto";

export default async (
  port: number | string = 3000,
  lookup?: ClientLookup | null
) => {
  const app = new Elysia();

  app.use(html());

  app.derive(() => ({ start: Date.now(), uuid: randomUUID() }));
  app.onAfterHandle(logRequest);

  // Per-client API key mapping (see client_keys.ts): a known client token in the
  // request is swapped for the key we hold for them. Tests inject a lookup (or
  // null to disable); production resolves it from the env (off unless the
  // lightning_clients table is provisioned).
  const clientLookup =
    lookup !== undefined ? lookup : await resolveClientLookupFromEnv();

  await setupHealthcheck(app);
  await setupDir(app);
  await setupServices(app, +port, clientLookup);

  console.log("Apollo Server listening on ", port);
  app.listen(port);

  return app;
};
