import { Elysia } from "elysia";
import path from "node:path";
import describeModules, {
  type ModuleDescription,
} from "../util/describe-modules";

import pkg from "../../../package.json" assert { type: "json" };

/**
 * TODO
 *
 * - sort services alphabetically
 *  - link to (and serve!) readme
 *  - include the first section of the readme in the listing (basic formattitng). Maybe show first sentence + expand?
 */

/**
 * Generates a listing of the available services
 */
export default async (app: Elysia) => {
  // jsx templates!
  // https://elysiajs.com/patterns/mvc.html#view

  const modules = await describeModules(path.resolve("./services"));
  app.get("/", () => {
    return (
      <html lang="en">
        <head>
          <title>OpenFn Apollo Service Listing</title>
        </head>
        <body>
          <h1>OpenFn Apollo Service Listing v{pkg.version}</h1>
          <div>
            <ul>{modules.map((m) => service(m))}</ul>
          </div>
          <footer style="margin-top: 30px;font-size: small;">
            v{pkg.version} &copy; Open Function Group{" "}
            {new Date().getUTCFullYear()}
          </footer>
        </body>
      </html>
    );
  });
};

function service(srv: ModuleDescription) {
  return (
    <li style="margin-bottom: 16px">
      <p style="margin-bottom: 8px;">
        <b>{srv.name}</b> <a href={`/services/${srv.name}/README.md`}>README</a>
      </p>
      <p style="margin-left: 16px; margin-top: 0; padding-left: 6px; border-left: solid 2px #c0c0c0;">
        {srv.summary}
      </p>
    </li>
  );
}
