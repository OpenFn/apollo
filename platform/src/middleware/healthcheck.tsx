import { Elysia } from "elysia";
import pkg from "../../../package.json" assert { type: "json" };
import { run } from '../bridge';
import { toErrorPayload } from '../util/errors';

export default async (app: Elysia) => {
  app.get("/livez", () => {
    return new Response(JSON.stringify({ version: pkg.version }), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
      },
    });
  });
  app.get("/status", async () => {
    // run() rejects now where it used to resolve null, and this is the one
    // caller outside the services routes. Without the catch a spawn failure
    // leaves the route throwing, so the health endpoint answers with Elysia's
    // generic 500 and reports to Sentry rather than saying what is wrong.
    let status: unknown;
    try {
      status = await run("status", 0, {} as any);
    } catch (error) {
      const payload = toErrorPayload(error);
      return new Response(JSON.stringify(payload), {
        status: payload.code,
        headers: {
          "Content-Type": "application/json",
        },
      });
    }

    return new Response(status as any, {
      status: 200,
      headers: {
        "Content-Type": "application/json",
      },
    });
  });
};
