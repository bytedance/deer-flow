/** Client request lifetime metadata, never an authorization grant. */
export interface WorkspaceRequestScope {
  readonly actorUserId: string;
  readonly workspaceId: string;
  readonly signal: AbortSignal;
}

const WORKSPACE_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function captureWorkspaceRequestScope(
  scope: WorkspaceRequestScope,
): WorkspaceRequestScope {
  if (
    !WORKSPACE_UUID.test(scope.workspaceId) ||
    !scope.actorUserId ||
    scope.actorUserId.length > 64 ||
    scope.actorUserId.trim() !== scope.actorUserId ||
    !scope.signal
  ) {
    throw new Error("Invalid workspace request lifetime");
  }
  // Copy first: a later mutation of caller metadata must not retarget a client.
  return Object.freeze({
    actorUserId: scope.actorUserId,
    workspaceId: scope.workspaceId,
    signal: scope.signal,
  });
}

export function prepareWorkspaceRequest(
  scope: WorkspaceRequestScope,
  apiUrl: string,
  input: RequestInfo | URL,
  init?: RequestInit,
): RequestInit {
  scope.signal.throwIfAborted();
  const root = new URL(apiUrl);
  const url = new URL(
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url,
    root,
  );
  const prefix = root.pathname.replace(/\/+$/, "");
  if (
    url.origin !== root.origin ||
    url.username ||
    url.password ||
    (prefix &&
      url.pathname !== prefix &&
      !url.pathname.startsWith(prefix + "/"))
  ) {
    throw new Error(
      "Workspace requests must stay on the configured Gateway API",
    );
  }
  const request = input instanceof Request ? input : undefined;
  const headers = new Headers(init?.headers ?? request?.headers);
  if (
    headers.has("X-Deerflow-Workspace") &&
    headers.get("X-Deerflow-Workspace") !== scope.workspaceId
  ) {
    throw new Error("Request workspace differs from its captured lifetime");
  }
  headers.set("X-Deerflow-Workspace", scope.workspaceId);
  const callerSignal = init?.signal ?? request?.signal;
  const signal =
    callerSignal && callerSignal !== scope.signal
      ? AbortSignal.any([scope.signal, callerSignal])
      : scope.signal;
  signal.throwIfAborted();
  return {
    ...init,
    headers,
    signal,
    credentials: "include",
    redirect: "error",
  };
}

export function createWorkspaceFetch(
  scope: WorkspaceRequestScope,
  apiUrl: string,
): typeof globalThis.fetch {
  return async (input, init) => {
    const prepared = prepareWorkspaceRequest(scope, apiUrl, input, init);
    try {
      const response = await globalThis.fetch(input, prepared);
      if (prepared.signal?.aborted) {
        try {
          await response.body?.cancel();
        } catch {
          // Native fetch normally aborts its body itself; still reject the reply.
        }
        prepared.signal.throwIfAborted();
      }
      return response;
    } catch (cause) {
      if (prepared.signal?.aborted) {
        // SDK 1.6's AsyncCaller classifies cancellation by message prefix.
        // DOMException's default message otherwise enters its retry backoff.
        const error = new Error("AbortError: workspace request ended", {
          cause,
        });
        error.name = "AbortError";
        throw error;
      }
      throw cause;
    }
  };
}

export async function* guardWorkspaceStream<T>(
  scope: WorkspaceRequestScope,
  source: AsyncIterable<T>,
): AsyncGenerator<T> {
  scope.signal.throwIfAborted();
  for await (const entry of source) {
    scope.signal.throwIfAborted();
    yield entry;
  }
  // An aborted network reader can finish quietly; it is not a normal Run END.
  scope.signal.throwIfAborted();
}
