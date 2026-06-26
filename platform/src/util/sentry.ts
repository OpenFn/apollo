import * as Sentry from "@sentry/bun";

// Mirrors the Python side (services/entry.py): all errors captured, traces
// sampled per environment.
const TRACE_RATES: Record<string, number> = {
  development: 1.0,
  staging: 0.05,
  production: 0.03,
  unknown: 0.0,
};

let enabled = false;

/**
 * Initialise Sentry once, before the server starts. A no-op when SENTRY_DSN is
 * unset, matching the Python side. Also registers process-level handlers so an
 * unhandled rejection (e.g. an auth.init() failure that index.ts does not await)
 * or uncaught exception reaches Sentry.
 */
export const initSentry = (): void => {
  const dsn = process.env.SENTRY_DSN;
  if (!dsn) return;

  const environment = process.env.ENVIRONMENT ?? "unknown";

  Sentry.init({
    dsn,
    environment,
    tracesSampleRate: TRACE_RATES[environment] ?? 0.0,
  });

  enabled = true;

  process.on("unhandledRejection", (reason) => captureException(reason));
  process.on("uncaughtException", (err) => captureException(err));
};

/**
 * Report an error to Sentry. A silent no-op when Sentry was not initialised
 * (DSN absent), so call sites can fire it unconditionally.
 */
export const captureException = (
  err: unknown,
  extras?: Record<string, unknown>
): void => {
  if (!enabled) return;
  Sentry.captureException(err, extras ? { extra: extras } : undefined);
};
