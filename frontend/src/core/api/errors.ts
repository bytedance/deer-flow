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
 * Throw an Error from a failed Gateway REST response.
 *
 * Parses the FastAPI error envelope and falls back to the caller-provided
 * message when the body is missing or not a recognized shape:
 * - `{ detail: string }` — raised by the Gateway's own HTTPException paths;
 * - `{ detail: [...] }` — pydantic request validation (422), where each item
 *   carries a `msg`; the messages are joined with "; " so callers surface one
 *   readable string instead of an implicit fallback.
 * Shared by the domain API modules (channels, scheduled tasks, PATs) so the
 * envelope format is interpreted in exactly one place.
 */
export async function throwGatewayApiError(
  response: Response,
  fallback: string,
): Promise<never> {
  const body = (await response.json().catch(() => ({}))) as {
    detail?: unknown;
  };
  if (typeof body.detail === "string") {
    throw new Error(body.detail);
  }
  if (Array.isArray(body.detail)) {
    const messages = body.detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item
          ? String(item.msg)
          : null,
      )
      .filter((message): message is string => message !== null);
    if (messages.length > 0) {
      throw new Error(messages.join("; "));
    }
  }
  throw new Error(fallback);
}
