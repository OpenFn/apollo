import { Elysia } from "elysia";
import { cors } from "@elysiajs/cors";
import { html } from "@elysiajs/html";

import setupDir from "./middleware/dir";
import setupServices from "./middleware/services";

export const app = new Elysia();

app.use(html());
app.use(cors());

export default async (port: number | string = 3000) => {
  await setupDir(app);
  await setupServices(app, port);

  console.log("Apollo Server listening on ", port);
  app.listen(port);
};
