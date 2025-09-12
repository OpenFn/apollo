// middleware to route to python services
import { Elysia } from "elysia";
import path from "node:path";

import { run } from "../bridge";
import describeModules, {
  type ModuleDescription,
} from "../util/describe-modules";
import { isApolloError } from "../util/errors";

const callService = (
  m: ModuleDescription,
  port: number,
  payload?: any,
  onLog?: (str: string) => void
) => {
  if (m.type === "py") {
    return run(m.name, port, payload as any, onLog);
  } else {
    return m.handler!(port, payload as any, onLog);
  }
};

export default async (app: Elysia, port: number) => {
  console.log("Loading routes:");
  const modules = await describeModules(path.resolve("./services"));
  app.group("/services", (app) => {
    modules.forEach((m) => {
      const { name, readme } = m;
      console.log(" - mounted /services/" + name);

      // simple post
      app.post(name, async (ctx) => {
        console.log(`POST to /services/${name}`);
        const payload = ctx.body;
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

      // websocket
      // TODO in the web socket API, does it make more sense to open a socket at root
      // and then pick the service you want? So you'd connect to /ws an send { call: 'echo', payload: {} }
      app.ws(name, {
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
