type PrimitiveType =
  | "string"
  | "number"
  | "boolean"
  | "null"
  | "undefined"
  | "bigint"
  | "symbol"
  | "function"
  | "redacted";

type ValueType = PrimitiveType | "array" | "object";

type ObjectShape = {
  type: "object";
  key_count: number;
  keys: string[];
  fields?: Record<string, PayloadShape>;
  truncated?: boolean;
};

type ArrayShape = {
  type: "array";
  length: number;
  item_types: ValueType[];
  item_shape?: PayloadShape;
};

export type PayloadShape = PrimitiveType | ObjectShape | ArrayShape;

type SummarizePayloadOptions = {
  maxDepth?: number;
  maxKeys?: number;
  maxArrayItems?: number;
  sensitiveKeys?: Set<string> | string[];
};

const DEFAULT_OPTIONS: Required<SummarizePayloadOptions> = {
  maxDepth: 2,
  maxKeys: 25,
  maxArrayItems: 25,
  sensitiveKeys: [
    "api_key",
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "x-api-key",
  ],
};

const getValueType = (value: unknown): ValueType => {
  if (value === null) {
    return "null";
  }

  if (Array.isArray(value)) {
    return "array";
  }

  const jsType = typeof value;
  if (jsType === "object") {
    return "object";
  }

  return jsType as PrimitiveType;
};

const summarizeValue = (
  value: unknown,
  currentKey: string | null,
  depth: number,
  options: Omit<Required<SummarizePayloadOptions>, "sensitiveKeys"> & {
    sensitiveKeys: Set<string>;
  }
): PayloadShape => {
  if (currentKey && options.sensitiveKeys.has(currentKey.toLowerCase())) {
    return "redacted";
  }

  const valueType = getValueType(value);

  if (valueType !== "object" && valueType !== "array") {
    return valueType;
  }

  if (valueType === "array") {
    const arrayValue = value as unknown[];
    const sample = arrayValue.slice(0, options.maxArrayItems);
    const itemTypes = [...new Set(sample.map(getValueType))].sort() as ValueType[];

    const result: ArrayShape = {
      type: "array",
      length: arrayValue.length,
      item_types: itemTypes,
    };

    if (depth <= options.maxDepth) {
      const complexItem = sample.find((item) => {
        const itemType = getValueType(item);
        return itemType === "object" || itemType === "array";
      });

      if (complexItem !== undefined) {
        result.item_shape = summarizeValue(complexItem, null, depth + 1, options);
      }
    }

    return result;
  }

  const objectValue = value as Record<string, unknown>;
  const keys = Object.keys(objectValue);
  const limitedKeys = keys.slice(0, options.maxKeys);

  const result: ObjectShape = {
    type: "object",
    key_count: keys.length,
    keys: limitedKeys,
  };

  if (depth <= options.maxDepth) {
    const fields: Record<string, PayloadShape> = {};
    for (const key of limitedKeys) {
      fields[key] = summarizeValue(objectValue[key], key, depth + 1, options);
    }
    result.fields = fields;
  }

  if (keys.length > limitedKeys.length) {
    result.truncated = true;
  }

  return result;
};

export const summarizePayloadShape = (
  payload: unknown,
  options: SummarizePayloadOptions = {}
): PayloadShape => {
  const resolvedOptionsRaw = {
    ...DEFAULT_OPTIONS,
    ...options,
  };
  const sensitiveKeys = new Set(
    [...resolvedOptionsRaw.sensitiveKeys].map((key) => key.toLowerCase())
  );

  return summarizeValue(payload, null, 0, {
    ...resolvedOptionsRaw,
    sensitiveKeys,
  });
};

type RequestLogBase = {
  requestId: string;
  service: string;
  route: string;
  now?: Date;
};

type RequestStartInput = RequestLogBase & {
  payload: unknown;
};

type RequestCompleteInput = RequestLogBase & {
  durationMs: number;
  statusCode: number;
  outcome: "success" | "apollo_error";
};

type RequestErrorInput = RequestLogBase & {
  durationMs: number;
  errorType: string;
};

const getTimestamp = (now?: Date) => (now ?? new Date()).toISOString();

export const buildServiceRequestStartLog = ({
  requestId,
  service,
  route,
  payload,
  now,
}: RequestStartInput) => ({
  event: "service_request_start",
  timestamp: getTimestamp(now),
  request_id: requestId,
  service,
  route,
  payload_shape: summarizePayloadShape(payload),
});

export const buildServiceRequestCompleteLog = ({
  requestId,
  service,
  route,
  durationMs,
  statusCode,
  outcome,
  now,
}: RequestCompleteInput) => ({
  event: "service_request_complete",
  timestamp: getTimestamp(now),
  request_id: requestId,
  service,
  route,
  duration_ms: durationMs,
  status_code: statusCode,
  outcome,
});

export const buildServiceRequestErrorLog = ({
  requestId,
  service,
  route,
  durationMs,
  errorType,
  now,
}: RequestErrorInput) => ({
  event: "service_request_error",
  timestamp: getTimestamp(now),
  request_id: requestId,
  service,
  route,
  duration_ms: durationMs,
  error_type: errorType,
});

export const attachRequestId = (payload: unknown, requestId: string) => {
  if (payload === null || Array.isArray(payload) || typeof payload !== "object") {
    return payload;
  }

  return {
    ...(payload as Record<string, unknown>),
    _request_id: requestId,
  };
};

export const logStructured = (payload: Record<string, unknown>) => {
  console.log(JSON.stringify(payload));
};
