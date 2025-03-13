import { Elysia } from "elysia";
import pkg from "../../../package.json" assert { type: "json" };
import { run } from '../bridge';

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
    const status = await run ('status', 0, {} as any) as any;
    return new Response(status, {
      status: 200,
      headers: {
        "Content-Type": "application/json",
      },
    });
  });
};
