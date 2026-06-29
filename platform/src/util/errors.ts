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
