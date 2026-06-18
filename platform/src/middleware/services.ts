// middleware to route to python services
import { Elysia } from "elysia";
import path from "node:path";

import { run } from "../bridge";
import describeModules, {
  type ModuleDescription,
} from "../util/describe-modules";
import { isApolloError } from "../util/errors";
import type { InstanceAuth } from "./auth";

const callService = (
  m: ModuleDescription,
  port: number,
  payload?: any,
  onLog?: (str: string) => void,
  onEvent?: (evt: string, payload: any) => void
) => {
  if (m.type === "py") {
    return run(m.name, port, payload as any, onLog, onEvent);
  } else {
    // TODO add event handling to ts services
    return m.handler!(port, payload as any, onLog);
  }
};

export default async (app: Elysia, port: number, auth: InstanceAuth) => {
  console.log("Loading routes:");
  const modules = await describeModules(path.resolve("./services"));

  // Build the service payload, applying instance auth. For an authenticated
  // external client we drop any caller-supplied api_key (they may not bring
  // their own key) and inject the resolved one. Internal calls and the
  // auth-disabled case pass the body through untouched, preserving a
  // parent-forwarded api_key.
  //
  // NOTE: handlers must reference `ctx.body` directly. Elysia decides whether to
  // parse the request body by statically inspecting the handler; hiding the
  // reference makes it skip parsing and the service receives an empty body.
  const buildPayload = (ctx: any, body: any) => {
    const payload = { ...(body ?? {}) };
    if (auth.isExternalClient(ctx)) {
      delete (payload as any).api_key;
    }
    return { ...payload, session_id: ctx.uuid, ...auth.apiKeyOverride(ctx) };
  };

  app.group("/services", (app) => {
    // Gate every /services/* route (no-op when auth is disabled). Internal
    // service-to-service calls authenticate via the shared secret.
    app.onBeforeHandle((ctx) => auth.gate(ctx as any));

    modules.forEach((m) => {
      const { name, readme } = m;
      console.log(" - mounted /services/" + name);

      // simple post
      app.post(name, async (ctx) => {
        console.log(`POST /services/${name}: ${ctx.uuid}`);
        const payload = buildPayload(ctx, ctx.body);
        const result = await callService(m, port, payload as any);

        if (isApolloError(result)) {
          return new Response(JSON.stringify(result), {
            status: result.code,
            headers: {
              "Content-Type": "application/json",
            },
          });
        }

        return result;
      });

      // HTTP streaming
      app.post(`${name}/stream`, async (ctx) => {
        console.log(`STREAM START /services/${name}: ${ctx.uuid}`);
        const payload = buildPayload(ctx, ctx.body);

        const stream = new ReadableStream({
          async start(controller) {
            const encoder = new TextEncoder();
            let isClosed = false;

            const sendSSE = (event: string, data: any) => {
              if (isClosed) {
                return;
              }
              try {
                const message = `event: ${event}\ndata: ${JSON.stringify(
                  data
                )}\n\n`;
                //  console.log(message.trim());
                controller.enqueue(encoder.encode(message));
              } catch (error) {
                // Stream may have been closed
                isClosed = true;
              }
            };

            const onLog = (log: string) => {
              sendSSE("log", log);
            };

            const onEvent = (type: string, payload: any) => {
              sendSSE(type, payload);
            };

            try {
              const result = await callService(
                m,
                port,
                payload as any,
                onLog,
                onEvent
              );

              if (isApolloError(result)) {
                sendSSE("error", result);
              } else {
                sendSSE("complete", result);
              }
            } catch (error) {
              sendSSE("error", {
                message:
                  error instanceof Error ? error.message : "Unknown error",
              });
            } finally {
              console.log(
                `STREAM COMPLETE ${ctx.uuid} in ${
                  (new Date() - ctx.start) / 1000
                }s`
              );
              isClosed = true;
              controller.close();
            }
          },
        });

        return new Response(stream, {
          headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            Connection: "keep-alive",
          },
        });
      });

      // websocket
      // TODO in the web socket API, does it make more sense to open a socket at root
      // and then pick the service you want? So you'd connect to /ws an send { call: 'echo', payload: {} }
      app.ws(name, {
        // Gate the WS upgrade too, so it can't be used to bypass auth. Note:
        // per-client Anthropic key injection is only wired into the POST and
        // /stream paths (the chat transports Lightning uses); WS payloads pass
        // through as-is.
        beforeHandle: (ctx) => auth.gate(ctx as any),
        open() {
          console.log(`Websocket connected  at /services/${name}`);
        },
        message(ws, message) {
          try {
            if (message.event === "start") {
              const onLog = (log: string) => {
                ws.send({
                  event: "log",
                  data: log,
                });
              };
              const onEvent = (type: string, payload: any) => {
                ws.send({
                  event: "event",
                  type,
                  data: payload,
                });
              };

              callService(m, port, message.data as any, onLog, onEvent).then(
                (result) => {
                  ws.send({
                    event: "complete",
                    data: result,
                  });
                }
              );
            }
          } catch (e) {
            console.log(e);
          }
        },
      });

      // TODO: it would be lovely to render the markdown into nice rich html
      app.get(`/${name}/README.md`, async (ctx) => readme);
    });

    return app;
  });

  return app;
};
