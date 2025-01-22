import { Elysia } from "elysia";
import pkg from "../../../package.json" assert { type: "json" };

export default async (app: Elysia) => {
  app.get("/livez", () => {
    return new Response(JSON.stringify({ version: pkg.version }), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
      },
    });
  });
};
