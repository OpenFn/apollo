import { initSentry } from "./util/sentry";
import start from "./server";

initSentry();

start(process.env.PORT);
