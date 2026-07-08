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
