"use client";

import { Client as LangGraphClient } from "@langchain/langgraph-sdk/client";

import { getLangGraphBaseURL } from "../config";
import { isStaticWebsiteOnly } from "../static-mode";
import {
  loadStaticDemoThread,
  loadStaticDemoThreads,
  staticDemoThreadState,
} from "../threads/static-demo";
import type { AgentThreadState } from "../threads/types";

import { isStateChangingMethod, readCsrfCookie } from "./fetcher";
import { sanitizeRunStreamOptions } from "./stream-mode";

/**
 * SDK ``onRequest`` hook that mints the ``X-CSRF-Token`` header from the
 * live ``csrf_token`` cookie just before each outbound fetch.
 *
 * Reading the cookie per-request (rather than baking it into the SDK's
 * ``defaultHeaders`` at construction) handles login / logout / password
 * change cookie rotation transparently. Both the ``/api/langgraph/*`` SDK
 * path and the direct REST endpoints in ``fetcher.ts:fetchWithAuth``
 * share :func:`readCsrfCookie` and :const:`STATE_CHANGING_METHODS` so
 * the contract stays in lockstep.
 */
function injectCsrfHeader(_url: URL, init: RequestInit): RequestInit {
  if (!isStateChangingMethod(init.method ?? "GET")) {
    return init;
  }
  const token = readCsrfCookie();
  if (!token) return init;
  const headers = new Headers(init.headers);
  if (!headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", token);
  }
  return { ...init, headers };
}

// Run statuses that have reached a terminal state where no further streaming
// is possible. Reconnecting (``joinStream``) to such a run either 409s or, once
// the backend's in-memory stream bridge is reaped (``worker.py`` calls
// ``publish_end`` unconditionally, including for interrupted runs, then reaps
// the bridge after 60s), blocks forever on a drained condition variable —
// pinning ``isLoading`` true so the submit button stays a stop button and the
// first message after a reload never sends. The ``joinStream`` wrapper below
// short-circuits these *before* joining.
//
// ``interrupted`` is included because in DeerFlow it is only ever written by
// ``RunManager.cancel()`` (a user-initiated stop); the resumable human-in-the-
// loop path uses ``Command(goto=END)`` (``ClarificationMiddleware``), which
// ends the run as ``success``, not ``interrupted``. So an interrupted run has
// nothing left to stream — its state lives in the checkpoint, fetched
// independently by ``useThreadHistory``, and resuming means a fresh ``submit``.
//
// ``error``/``timeout`` are terminal too, so a reload within the ~60s
// bridge-reap window no longer replays the buffered error event through
// ``onError`` — the transient error toast (``getStreamErrorMessage``) is
// dropped. The persisted error state still loads from the checkpoint via
// ``useThreadHistory``, so only the toast is lost; that is intentional, since
// surfacing a stale error toast on every reload is noise rather than signal.
const TERMINAL_RUN_STATUSES = new Set([
  "success",
  "error",
  "timeout",
  "interrupted",
]);

/**
 * Shared matcher for the gateway's 409 conflict responses. The SDK surfaces
 * non-2xx responses as ``HTTPError { status, message }`` where ``message`` is
 * ``"HTTP 409: {\"detail\":\"...\"}"``, so a 409 may be detected either via the
 * numeric ``status`` or a substring of ``message``.
 *
 * Every passed ``needles`` substring must be present; this AND semantics is what
 * lets a caller distinguish sibling conflict branches by phrase (e.g. the
 * terminal-state cancel branch from the still-active-on-another-worker branch).
 *
 * Match strings until the API exposes a structured error code; the source of
 * truth is ``_cancel_conflict_detail`` / the store-only response in
 * ``backend/app/gateway/routers/thread_runs.py``.
 */
function isRunConflictError(error: unknown, ...needles: string[]): boolean {
  const status =
    typeof error === "object" && error !== null
      ? Reflect.get(error, "status")
      : undefined;
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : typeof error === "object" && error !== null
          ? String(Reflect.get(error, "message") ?? "")
          : "";

  return (
    (status === 409 || message.includes("HTTP 409")) &&
    needles.every((needle) => message.includes(needle))
  );
}

// Store-only run cannot be streamed (no in-memory stream bridge on this
// worker): reconnect has nothing to rejoin.
export function isInactiveRunStreamError(error: unknown): boolean {
  return isRunConflictError(
    error,
    "not active on this worker",
    "cannot be streamed",
  );
}

/**
 * Matches the gateway's terminal-state cancel conflict, raised by
 * ``_cancel_conflict_detail`` in ``backend/app/gateway/routers/thread_runs.py``
 * as ``Run X is not cancellable (status: success|error|timeout)`` when
 * ``RunManager.cancel`` refuses a run that already finished.
 *
 * The sibling ``"not active on this worker and cannot be cancelled"`` branch
 * (run still pending/running on another worker in a multi-instance deploy) is
 * intentionally NOT matched — that is a real cancel failure on a live run and
 * must stay visible. Only the terminal-state branch is a true no-op.
 */
export function isRunNotCancellableError(error: unknown): boolean {
  return isRunConflictError(error, "is not cancellable");
}

/**
 * Preflight a reconnect: if the run already reached a terminal state, there is
 * nothing to rejoin. Returns ``true`` when the caller should skip the
 * underlying ``joinStream`` so the SDK's ``onSuccess`` path runs and
 * ``isLoading`` flips back to false — instead of blocking forever on a drained
 * stream bridge.
 *
 * Any error (404 for an evicted record, network blip, auth hiccup, …) falls
 * back to the original join so a legitimately active reconnect is never
 * silently suppressed.
 */
async function shouldSkipReconnect(
  client: LangGraphClient,
  threadId: string,
  runId: string,
): Promise<boolean> {
  try {
    const run = await client.runs.get(threadId, runId);
    return TERMINAL_RUN_STATUSES.has(run.status);
  } catch {
    return false;
  }
}

export function clearReconnectRun(
  threadId: string | null | undefined,
  runId: string,
): void {
  if (typeof window === "undefined" || !threadId) return;

  const key = `lg:stream:${threadId}`;
  try {
    const storage = window.sessionStorage;
    if (storage.getItem(key) === runId) {
      storage.removeItem(key);
    }
  } catch {
    // Ignore storage access failures so reconnect cleanup never throws.
  }
}

function createCompatibleClient(isMock?: boolean): LangGraphClient {
  if (isStaticWebsiteOnly() && !isMock) {
    return createStaticClient();
  }

  const apiUrl = getLangGraphBaseURL(isMock);
  console.log(`Creating API client with base URL: ${apiUrl}`);
  const client = new LangGraphClient({
    apiUrl,
    onRequest: injectCsrfHeader,
  });

  const originalRunStream = client.runs.stream.bind(client.runs);
  client.runs.stream = ((threadId, assistantId, payload) =>
    originalRunStream(
      threadId,
      assistantId,
      sanitizeRunStreamOptions(payload),
    )) as typeof client.runs.stream;

  const originalCancel = client.runs.cancel.bind(client.runs);
  client.runs.cancel = (async (threadId, runId, wait, action, options) => {
    try {
      return await originalCancel(threadId, runId, wait, action, options);
    } catch (error) {
      if (isRunNotCancellableError(error)) {
        // The run already reached a terminal state, so cancelling it is a
        // no-op. Swallow the 409 so a stop click during the finish window
        // (backend flipped to ``success`` but the SSE stream hasn't drained)
        // doesn't surface as an unhandled rejection, and clear the now-stale
        // reconnect key. clearReconnectRun only removes the key when it still
        // matches this runId, so a newer run's key is never touched.
        clearReconnectRun(threadId, runId);
        return;
      }
      throw error;
    }
  }) as typeof client.runs.cancel;

  const originalJoinStream = client.runs.joinStream.bind(client.runs);
  client.runs.joinStream = async function* (threadId, runId, options) {
    // Short-circuit reconnects to runs that have already finished: otherwise a
    // reload after the backend's stream bridge is reaped blocks forever on a
    // drained condition variable, pinning ``isLoading`` true so the first
    // post-reload message is routed to ``stop`` instead of ``submit``.
    if (threadId && (await shouldSkipReconnect(client, threadId, runId))) {
      clearReconnectRun(threadId, runId);
      return;
    }
    try {
      yield* originalJoinStream(
        threadId,
        runId,
        sanitizeRunStreamOptions(options),
      );
    } catch (error) {
      if (isInactiveRunStreamError(error)) {
        clearReconnectRun(threadId, runId);
        return;
      }
      throw error;
    }
  } as typeof client.runs.joinStream;

  return client;
}

function createStaticClient(): LangGraphClient {
  const apiUrl =
    typeof window === "undefined"
      ? "http://localhost:3000"
      : window.location.origin;
  const client = new LangGraphClient({ apiUrl });

  client.threads.search = (async (query) => {
    return loadStaticDemoThreads(query);
  }) as typeof client.threads.search;

  client.threads.get = (async (threadId) => {
    return loadStaticDemoThread(threadId);
  }) as typeof client.threads.get;

  client.threads.getState = (async (threadId) => {
    return staticDemoThreadState(await loadStaticDemoThread(threadId));
  }) as typeof client.threads.getState;

  client.threads.getHistory = (async (threadId) => {
    return [staticDemoThreadState(await loadStaticDemoThread(threadId))];
  }) as typeof client.threads.getHistory;

  client.threads.update = (async (threadId) => {
    return loadStaticDemoThread(threadId);
  }) as typeof client.threads.update;

  client.runs.list = (async () => []) as typeof client.runs.list;
  client.runs.stream = async function* () {
    /* empty */
  } as typeof client.runs.stream;
  client.runs.joinStream = async function* () {
    /* empty */
  } as typeof client.runs.joinStream;

  return client as LangGraphClient<AgentThreadState>;
}

const _clients = new Map<string, LangGraphClient>();
export function getAPIClient(isMock?: boolean): LangGraphClient {
  const cacheKey = isMock ? "mock" : "default";
  let client = _clients.get(cacheKey);

  if (!client) {
    client = createCompatibleClient(isMock);
    _clients.set(cacheKey, client);
  }

  return client;
}
