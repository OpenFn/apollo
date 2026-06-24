// middleware to route to python services
import { Elysia } from "elysia";
import path from "node:path";

import { run } from "../bridge";
import describeModules, {
  type ModuleDescription,
} from "../util/describe-modules";
import { isApolloError } from "../util/errors";
import type { InstanceAuth } from "../auth/instance-auth";

const textEncoder = new TextEncoder();

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

  // Apply the resolved key to an outgoing payload with an explicit switch so the
  // inbound-credential-never-forwarded invariant is structural, not positional: a
  // known client's stored key is swapped in (useKey), a NULL stored key drops the
  // field so Python uses the global key (useGlobal), and every other caller forwards
  // the body exactly as received (forward/passthrough). `ctx` is the upgrade-time
  // context that carries lightningClient/internalCall: on POST the route ctx, on WS
  // the captured ws.data, never a fresh per-message one.
  const applyKey = (payload: Record<string, any>, ctx: any) => {
    const resolution = auth.resolveKey(ctx);
    switch (resolution.kind) {
      case "useKey":
        payload.api_key = resolution.key;
        break;
      case "useGlobal":
        delete payload.api_key;
        break;
      case "forward":
      case "passthrough":
        break;
      default: {
        // Exhaustiveness guard: a new KeyResolution tag must be a compile error
        // here, not a silent forward of the inbound credential.
        const _exhaustive: never = resolution;
        throw new Error(
          `unhandled KeyResolution: ${(resolution as { kind: string }).kind}`
        );
      }
    }
    return payload;
  };

  const buildPayload = (ctx: any) =>
    applyKey({ ...(ctx.body ?? {}), session_id: ctx.uuid }, ctx);

  app.group("/services", (app) => {
    // Resolve every /services/* caller: swap a known client's key, forward an
    // unknown sk-ant- (or absent) key, reject a forged internal header or an
    // unknown non-sk-ant- key.
    app.onBeforeHandle(auth.authenticate);

    modules.forEach((m) => {
      const { name, readme } = m;
      console.log(" - mounted /services/" + name);

      // simple post
      app.post(name, async (ctx) => {
        console.log(`POST /services/${name}: ${ctx.uuid}`);
        const payload = buildPayload(ctx);
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
        const payload = buildPayload(ctx);

        const stream = new ReadableStream({
          async start(controller) {
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
                controller.enqueue(textEncoder.encode(message));
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
        // Run the auth hook on the WS upgrade. The handshake is a bodyless GET, so a
        // known client rides its credential as the ?api_key= query param (see
        // auth.authenticate); the auth hook hashes and resolves it just like POST, stashing
        // lightningClient on the upgrade context. ws.data is that same context, so
        // the message handler resolves the outgoing key off it.
        beforeHandle: auth.authenticate,
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

              // The credential rode the upgrade query string, not the message body.
              // Seed a forwardable unknown key onto the payload so applyKey's
              // forward case preserves it; a known client's useKey/useGlobal then
              // overrides or drops it exactly as on POST.
              const base: Record<string, any> = { ...(message.data ?? {}) };
              if (base.api_key == null && (ws.data as any)?.forwardApiKey) {
                base.api_key = (ws.data as any).forwardApiKey;
              }
              const payload = applyKey(base, ws.data);

              callService(m, port, payload as any, onLog, onEvent).then(
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
      app.get(`${name}/README.md`, async (ctx) => readme);
    });

    return app;
  });

  return app;
};
