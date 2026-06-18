import { Elysia } from "elysia";

import setupDir from "./middleware/dir";
import setupHealthcheck from "./middleware/healthcheck";
import setupServices from "./middleware/services";
import { html } from "@elysiajs/html";
import logRequest from "./util/log-request";
import {
  createInstanceAuth,
  resolveAuthConfigFromEnv,
  type InstanceAuth,
} from "./middleware/auth";
import { randomUUID } from "node:crypto";

export default async (port: number | string = 3000, auth?: InstanceAuth) => {
  const app = new Elysia();

  app.use(html());

  app.derive(() => ({ start: Date.now(), uuid: randomUUID() }));
  app.onAfterHandle(logRequest);

  // Decide whether /services/* is gated by an instance token (see auth.ts).
  // Tests inject a configured instance; production resolves it from the env.
  const instanceAuth = auth ?? createInstanceAuth(await resolveAuthConfigFromEnv());

  await setupHealthcheck(app);
  await setupDir(app);
  await setupServices(app, +port, instanceAuth);

  console.log("Apollo Server listening on ", port);
  app.listen(port);

  return app;
};
