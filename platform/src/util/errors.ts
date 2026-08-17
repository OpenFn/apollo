export interface ApolloError {
  code: number;
  type?: string;
  message?: string;
  details?: Record<string, any>;
}

export function isApolloError(value: any): value is ApolloError {
  return value && typeof value.code === 'number';
}

/** Build an ApolloError and set the matching HTTP status on the Elysia context,
 *  so every error path produces the same envelope shape from one definition. */
export function apolloError(
  ctx: any,
  code: number,
  type: string,
  message: string,
  details?: Record<string, any>
): ApolloError {
  if (ctx?.set) ctx.set.status = code;
  return { code, type, message, ...(details ? { details } : {}) };
}

/** An ApolloError that can also be thrown, so a catch block gets a real Error
 *  while the wire shape stays the same. `toJSON` is required: JSON.stringify on
 *  an Error is `{}` without it. */
export class ApolloThrowable extends Error implements ApolloError {
  readonly code: number;
  readonly type: string;
  readonly details?: Record<string, any>;

  constructor(
    code: number,
    type: string,
    message: string,
    details?: Record<string, any>
  ) {
    super(message);
    this.name = "ApolloThrowable";
    this.code = code;
    this.type = type;
    this.details = details;
  }

  toJSON(): ApolloError {
    return {
      code: this.code,
      type: this.type,
      message: this.message,
      ...(this.details ? { details: this.details } : {}),
    };
  }
}

/** The service process exited non-zero. */
export function subprocessFailed(
  service: string,
  exitCode: number
): ApolloThrowable {
  return new ApolloThrowable(
    500,
    "SUBPROCESS_FAILED",
    `Service "${service}" exited with code ${exitCode}`,
    { service, exitCode }
  );
}

/** We never got as far as running the service - poetry or python missing, or
 *  the spawn refused. */
export function subprocessSpawnFailed(
  service: string,
  cause: unknown
): ApolloThrowable {
  return new ApolloThrowable(
    500,
    "SUBPROCESS_SPAWN_FAILED",
    `Service "${service}" could not be started`,
    { service, cause: cause instanceof Error ? cause.message : String(cause) }
  );
}

/** We stopped the service ourselves because the client went away. 499 keeps
 *  these out of the 5xx that mean something is actually broken. */
export function subprocessCancelled(
  service: string,
  signal: string
): ApolloThrowable {
  return new ApolloThrowable(
    499,
    "SUBPROCESS_CANCELLED",
    `Service "${service}" was cancelled because the client disconnected`,
    { service, signal }
  );
}

/** Something outside Apollo killed the service - most often the OOM killer.
 *  Distinct from a cancellation, which is us, and from a non-zero exit, which
 *  is the service deciding to stop. */
export function subprocessKilled(
  service: string,
  signal: string
): ApolloThrowable {
  return new ApolloThrowable(
    500,
    "SUBPROCESS_KILLED",
    `Service "${service}" was killed by ${signal}`,
    { service, signal }
  );
}

/** The service exited cleanly but its output isn't valid JSON. Without this
 *  case the parse error escapes the close handler and the request never
 *  settles. */
export function malformedResult(service: string): ApolloThrowable {
  return new ApolloThrowable(
    502,
    "MALFORMED_RESULT",
    `Service "${service}" produced a result that could not be parsed`,
    { service }
  );
}

/** The service exited cleanly but wrote nothing. entry.py writes a result on
 *  every path it completes, so an empty file means the run died. */
export function emptyResult(service: string): ApolloThrowable {
  return new ApolloThrowable(
    502,
    "EMPTY_RESULT",
    `Service "${service}" finished without producing a result`,
    { service }
  );
}

export function unauthorized(ctx: any): ApolloError {
  return apolloError(ctx, 401, "UNAUTHORIZED", "Missing or invalid API key");
}

export function serviceUnavailable(ctx: any): ApolloError {
  return apolloError(
    ctx,
    503,
    "SERVICE_UNAVAILABLE",
    "Client verification is temporarily unavailable"
  );
}

export function clientMisconfigured(ctx: any): ApolloError {
  return apolloError(
    ctx,
    500,
    "CLIENT_MISCONFIGURED",
    "Client has no API key configured"
  );
}

/** Normalise anything thrown by a service run into the ApolloError envelope, so
 *  a caller sees the same shape whether the failure was typed or not. */
export function toErrorPayload(error: unknown): ApolloError {
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
}
