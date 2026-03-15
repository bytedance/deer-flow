import { getBackendBaseURL } from "../config";

const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions extends Omit<RequestInit, "signal"> {
  timeout?: number;
  signal?: AbortSignal;
}

/**
 * Thin wrapper around fetch for gateway API calls.
 * - Prepends the backend base URL
 * - Enforces a per-request timeout (default 30 s)
 * - Throws `ApiError` on non-2xx responses
 */
export async function apiFetch(
  path: string,
  options: RequestOptions = {},
): Promise<Response> {
  const { timeout = DEFAULT_TIMEOUT_MS, ...init } = options;

  const timeoutController = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    timeoutController.abort();
  }, timeout);

  const signals: AbortSignal[] = [timeoutController.signal];
  if (init.signal) signals.push(init.signal);

  const combinedController = new AbortController();
  const abortCombined = () => combinedController.abort();
  for (const signal of signals) {
    if (signal.aborted) {
      abortCombined();
      break;
    }
    signal.addEventListener("abort", abortCombined, { once: true });
  }

  try {
    const response = await fetch(`${getBackendBaseURL()}${path}`, {
      ...init,
      signal: combinedController.signal,
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const detail =
        typeof body === "object" && body !== null && "detail" in body
          ? String((body as { detail?: unknown }).detail)
          : undefined;
      throw new ApiError(
        detail ?? `Request failed: ${response.status} ${response.statusText}`,
        response.status,
        detail,
      );
    }

    return response;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      if (timedOut) {
        throw new ApiError("Request timed out", 0, "timeout");
      }
      throw new ApiError("Request was cancelled", 0, "aborted");
    }
    throw error;
  } finally {
    for (const signal of signals) {
      signal.removeEventListener("abort", abortCombined);
    }
    clearTimeout(timer);
  }
}

/** Convenience: apiFetch + parse JSON. */
export async function apiJson<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const res = await apiFetch(path, options);
  if (res.status === 204 || res.status === 205) {
    return undefined as T;
  }

  const body = await res.text();
  if (!body.trim()) {
    return undefined as T;
  }

  try {
    return JSON.parse(body) as T;
  } catch {
    throw new ApiError("Invalid JSON response", res.status, body.slice(0, 500));
  }
}
