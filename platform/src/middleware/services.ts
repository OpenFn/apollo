// middleware to route to python services
import { Elysia } from "elysia";
import path from "node:path";

import { run } from "../bridge";
import describeModules, {
  type ModuleDescription,
} from "../util/describe-modules";
import {
  ApolloThrowable,
  isApolloError,
  type ApolloError,
} from "../util/errors";
import type { InstanceAuth } from "../auth/instance-auth";

const textEncoder = new TextEncoder();

// The space after the colon is required: Lightning's SSE decoder matches
// `": " <> comment` and has no catch-all clause, so ":ping" raises there.
export const HEARTBEAT_FRAME = ": ping\n\n";

// Inside the shortest silence any hop tolerates - our own socket, Lightning's
// inter-chunk timeout, and the 60s read timeout typical of proxies.
export const HEARTBEAT_INTERVAL_MS = 15_000;

// Read per request rather than at import, so it can be turned down without a
// release if a hop turns out to be less patient than we thought. Zero and
// negatives are rejected rather than passed to setInterval, which would treat
// them as "every tick".
export const heartbeatIntervalMs = (): number => {
  const configured = Number(process.env.APOLLO_HEARTBEAT_INTERVAL_MS);

  return Number.isFinite(configured) && configured > 0
    ? configured
    : HEARTBEAT_INTERVAL_MS;
};

/** Normalise anything thrown by a service run into the ApolloError envelope, so
 *  a caller sees the same shape whether the failure was typed or not. */
const toErrorPayload = (error: unknown): ApolloError => {
  if (error instanceof ApolloThrowable) {
    return error.toJSON();
  }
  // Rebuilt field by field rather than returned as-is: isApolloError only
  // checks for a numeric `code`, and anything else hanging off the object
  // would be serialised to the caller along with it.
  if (isApolloError(error)) {
    return {
      code: error.code,
      type: error.type,
      message: error.message,
      ...(error.details === undefined ? {} : { details: error.details }),
    };
  }
  return {
    code: 500,
    type: "INTERNAL_ERROR",
    message: error instanceof Error ? error.message : String(error),
  };
};

const callService = (
  m: ModuleDescription,
  port: number,
  payload?: any,
  onLog?: (str: string) => void,
  onEvent?: (evt: string, payload: any) => void,
  signal?: AbortSignal
) => {
  if (m.type === "py") {
    return run(m.name, port, payload as any, onLog, onEvent, signal);
  } else {
    // TODO add event handling to ts services
    // TODO ts services can't be cancelled - the handler signature has no signal
    return m.handler!(port, payload as any, onLog);
  }
};

export default async (app: Elysia, port: number, auth: InstanceAuth) => {
  console.log("Loading routes:");
  const modules = await describeModules(path.resolve("./services"));

  // Apply the resolved key to an outgoing payload with an explicit switch so the
  // inbound-credential-never-forwarded invariant is structural, not positional: a
  // known client's stored key is swapped in (useKey), a NULL stored key (or a request
  // with no api_key) drops the field so Python uses the global key (useGlobal), and an
  // internal apollo() hop forwards the body exactly as received (passthrough). `ctx` is
  // the upgrade-time context that carries lightningClient/internalCall: on POST the
  // route ctx, on WS the captured ws.data, never a fresh per-message one.
  const applyKey = (payload: Record<string, any>, ctx: any) => {
    const resolution = auth.resolveKey(ctx);
    switch (resolution.kind) {
      case "useKey":
        payload.api_key = resolution.key;
        break;
      case "useGlobal":
        delete payload.api_key;
        break;
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
    // Resolve every /services/* caller: swap a known client's key, drop the field for
    // a no-key request (global key), and reject anything else (forged internal header,
    // or an api_key that isn't a known client -> 401/503).
    app.onBeforeHandle(auth.authenticate);

    modules.forEach((m) => {
      const { name, readme } = m;
      console.log(" - mounted /services/" + name);

      app.head(name, () => new Response(null, { status: 200 }));

      // simple post
      app.post(name, async (ctx) => {
        console.log(`POST /services/${name}: ${ctx.uuid}`);
        const payload = buildPayload(ctx);

        let result: any;
        try {
          result = await callService(m, port, payload as any);
        } catch (error) {
          const payload = toErrorPayload(error);
          return new Response(JSON.stringify(payload), {
            status: payload.code,
            headers: {
              "Content-Type": "application/json",
            },
          });
        }

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

        const abort = new AbortController();

        // Hoisted so cancel() can reach what start() set up
        let isClosed = false;
        let heartbeat: ReturnType<typeof setInterval> | undefined;

        const stopHeartbeat = () => {
          if (heartbeat) {
            clearInterval(heartbeat);
            heartbeat = undefined;
          }
        };

        const stream = new ReadableStream({
          async start(controller) {
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
                // Same as the heartbeat's catch: a throwing enqueue is a
                // dropped connection the runtime has not told us about.
                isClosed = true;
                stopHeartbeat();
                abort.abort();
              }
            };

            const onLog = (log: string) => {
              sendSSE("log", log);
            };

            const onEvent = (type: string, payload: any) => {
              sendSSE(type, payload);
            };

            // Started before the service call so the window while Python boots
            // is covered too
            heartbeat = setInterval(() => {
              if (isClosed) {
                stopHeartbeat();
                return;
              }
              try {
                controller.enqueue(textEncoder.encode(HEARTBEAT_FRAME));
              } catch (error) {
                // The consumer went away between ticks. cancel() may never
                // fire for this, so end the run here rather than leaving the
                // child generating for nobody.
                isClosed = true;
                stopHeartbeat();
                abort.abort();
              }
            }, heartbeatIntervalMs());

            try {
              const result = await callService(
                m,
                port,
                payload as any,
                onLog,
                onEvent,
                abort.signal
              );

              if (isApolloError(result)) {
                sendSSE("error", result);
              } else {
                sendSSE("complete", result);
              }
            } catch (error) {
              sendSSE("error", toErrorPayload(error));
            } finally {
              stopHeartbeat();
              console.log(
                `STREAM COMPLETE ${ctx.uuid} in ${
                  (Date.now() - ctx.start) / 1000
                }s`
              );
              isClosed = true;
              try {
                controller.close();
              } catch (error) {
                // already closed from the consumer's side
              }
            }
          },

          // Everything from here on is work nobody will read
          cancel(reason) {
            isClosed = true;
            stopHeartbeat();
            console.warn(
              `STREAM CANCELLED ${ctx.uuid} after ${
                (Date.now() - ctx.start) / 1000
              }s`
            );
            abort.abort(reason);
          },
        });

        // cancel() depends on the runtime noticing the dropped connection, so
        // listen on the request's own signal too. abort() is idempotent.
        ctx.request?.signal?.addEventListener("abort", () => abort.abort(), {
          once: true,
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

              // The credential rode the upgrade query string and was resolved by the
              // auth hook onto ws.data; applyKey reads the resolution off it. A known
              // client's useKey/useGlobal swaps or drops the field exactly as on POST.
              const base: Record<string, any> = { ...(message.data ?? {}) };
              const payload = applyKey(base, ws.data);

              // The catch matters as much as the then: a run that rejects
              // (spawn failure, empty output) would otherwise leave the client
              // waiting on a frame that never comes. The try around this only
              // sees synchronous throws.
              callService(m, port, payload as any, onLog, onEvent)
                .then((result) => {
                  ws.send({
                    event: "complete",
                    data: result,
                  });
                })
                .catch((error) => {
                  ws.send({
                    event: "error",
                    data: toErrorPayload(error),
                  });
                });
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
