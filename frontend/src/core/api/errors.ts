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
 * Parses the FastAPI error envelope (`{ detail: string }`) and falls back to
 * the caller-provided message when the body is missing or not that shape.
 * Shared by the domain API modules (channels, scheduled tasks) so the envelope
 * format is interpreted in exactly one place.
 */
export async function throwGatewayApiError(
  response: Response,
  fallback: string,
): Promise<never> {
  const body = (await response.json().catch(() => ({}))) as {
    detail?: unknown;
  };
  throw new Error(typeof body.detail === "string" ? body.detail : fallback);
}
