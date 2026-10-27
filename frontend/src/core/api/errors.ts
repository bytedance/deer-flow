/**
 * Raised after the shared fetcher has started a login redirect for a 401.
 *
 * Callers may use this type to avoid showing a second, misleading API error
 * while the browser is already navigating to the authentication flow.
 */
export class UnauthorizedError extends Error {
  constructor() {
    super("Unauthorized");
    this.name = "UnauthorizedError";
  }
}

/**
 * A failed Gateway REST response.
 *
 * `message` keeps the historical meaning (a string `detail`, else
 * `detail.message`, else the caller's fallback), so callers that only read
 * `error.message` are unchanged. Coded errors
 * (`detail: { code, message, params }`) also expose `code` and `params` for
 * localized UI copy; `rawMessage` is the server's own text for a "Details"
 * disclosure.
 */
export class GatewayApiError extends Error {
  readonly status: number;
  /** `detail.code` for a coded error, `"invalid_request"` for FastAPI's list detail, else null. */
  readonly code: string | null;
  readonly params: Record<string, unknown>;
  /** The server's message (string detail, `detail.message`, or the list's `msg`s); "" when there was none. */
  readonly rawMessage: string;

  constructor({
    message,
    status,
    code,
    params,
    rawMessage,
  }: {
    message: string;
    status: number;
    code: string | null;
    params: Record<string, unknown>;
    rawMessage: string;
  }) {
    super(message);
    this.name = "GatewayApiError";
    this.status = status;
    this.code = code;
    this.params = params;
    this.rawMessage = rawMessage;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Interpret a FastAPI error body (`{ detail }`) without throwing. */
export function parseGatewayApiError(
  body: unknown,
  status: number,
  fallback: string,
): GatewayApiError {
  const detail = isRecord(body) ? body.detail : undefined;
  if (typeof detail === "string") {
    return new GatewayApiError({
      message: detail,
      status,
      code: null,
      params: {},
      rawMessage: detail,
    });
  }
  if (isRecord(detail)) {
    const rawMessage = typeof detail.message === "string" ? detail.message : "";
    return new GatewayApiError({
      message: rawMessage || fallback,
      status,
      code: typeof detail.code === "string" && detail.code ? detail.code : null,
      params: isRecord(detail.params) ? detail.params : {},
      rawMessage,
    });
  }
  if (Array.isArray(detail)) {
    // FastAPI's own validation body: malformed JSON or a wrong field type.
    const rawMessage = detail
      .map((item) =>
        isRecord(item) && typeof item.msg === "string" ? item.msg : "",
      )
      .filter(Boolean)
      .join("; ");
    return new GatewayApiError({
      message: fallback,
      status,
      code: "invalid_request",
      params: {},
      rawMessage,
    });
  }
  return new GatewayApiError({
    message: fallback,
    status,
    code: null,
    params: {},
    rawMessage: "",
  });
}

/**
 * Throw a GatewayApiError from a failed Gateway REST response.
 *
 * Parses the FastAPI error envelope (`{ detail: string }`, the coded
 * `{ detail: { code, message, params } }`, or FastAPI's validation list) and
 * falls back to the caller-provided message when the body is missing or has
 * no message. Shared by the domain API modules (channels, scheduled tasks) so
 * the envelope format is interpreted in exactly one place.
 */
export async function throwGatewayApiError(
  response: Response,
  fallback: string,
): Promise<never> {
  const body: unknown = await response.json().catch(() => ({}));
  throw parseGatewayApiError(body, response.status, fallback);
}
