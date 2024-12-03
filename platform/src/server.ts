import { Elysia } from "elysia";

import setupDir from "./middleware/dir";
import setupServices from "./middleware/services";
import { html } from "@elysiajs/html";

export default async (port: number | string = 3000) => {
  const app = new Elysia();

  app.use(html());

  await setupDir(app);
  await setupServices(app, +port);

  console.log("Apollo Server listening on ", port);
  app.listen(port);

  return app;
};
