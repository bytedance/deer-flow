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
import { forceChatRunStreamOptions } from "./stream-mode";

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

// This is a rejoin budget: the original stream is not counted, so exhausting
// five recovery attempts can consume six streams in total.
const MAX_STREAM_GAP_RECOVERIES = 5;

export type StreamReplayGapData = {
  code: "stream_replay_gap";
  run_id: string;
  requested_event_id: string | null;
  earliest_available_event_id: string | null;
  latest_available_event_id: string | null;
  recovery: "reload_durable_state";
};

type StreamPart = {
  id?: string;
  event: string;
  data: unknown;
};

type ReconnectInputSnapshot = Record<string, unknown> & {
  messages: unknown[];
};

function streamOptionSignal(options: unknown): AbortSignal | undefined {
  if (typeof AbortSignal === "undefined") {
    return undefined;
  }
  if (options instanceof AbortSignal) {
    return options;
  }
  if (typeof options !== "object" || options === null) {
    return undefined;
  }
  const signal = Reflect.get(options, "signal");
  return signal instanceof AbortSignal ? signal : undefined;
}

/**
 * Recover the submitted input before replaying an active run. The incremental
 * chat stream intentionally omits `values`, so a page reload can otherwise
 * receive the run's AI/tool chunks before its human message has reached the
 * durable history feed. `runs.get` retains the original graph input in
 * `kwargs.input`; merge it into the latest durable values for one synthetic
 * snapshot. Any read failure is deliberately ignored so reconnect semantics
 * remain unchanged for deployments without run metadata.
 */
async function loadReconnectInputSnapshot(
  client: LangGraphClient,
  threadId: string,
  runId: string,
  run?: Awaited<ReturnType<LangGraphClient["runs"]["get"]>>,
  durableValues?: unknown,
  signal?: AbortSignal,
): Promise<ReconnectInputSnapshot | undefined> {
  try {
    const resolvedRun =
      run ?? (await client.runs.get(threadId, runId, { signal }));
    const runKwargs = Reflect.get(resolvedRun, "kwargs");
    const input =
      typeof runKwargs === "object" && runKwargs !== null
        ? Reflect.get(runKwargs, "input")
        : undefined;
    const inputMessages =
      typeof input === "object" && input !== null
        ? Reflect.get(input, "messages")
        : undefined;
    if (!Array.isArray(inputMessages) || inputMessages.length === 0) {
      return undefined;
    }

    const resolvedDurableValues =
      durableValues ??
      (await client.threads.getState(threadId, undefined, { signal })).values;
    const normalizedDurableValues =
      typeof resolvedDurableValues === "object" &&
      resolvedDurableValues !== null
        ? resolvedDurableValues
        : {};
    const durableMessages = Array.isArray(
      Reflect.get(normalizedDurableValues, "messages"),
    )
      ? (Reflect.get(normalizedDurableValues, "messages") as unknown[])
      : [];
    const seenIds = new Set(
      durableMessages.flatMap((message) => {
        const id =
          typeof message === "object" && message !== null
            ? Reflect.get(message, "id")
            : undefined;
        return typeof id === "string" && id.length > 0 ? [id] : [];
      }),
    );
    const messages = [
      ...durableMessages,
      ...inputMessages.filter((message) => {
        const id =
          typeof message === "object" && message !== null
            ? Reflect.get(message, "id")
            : undefined;
        if (typeof id !== "string" || id.length === 0) return true;
        if (seenIds.has(id)) return false;
        seenIds.add(id);
        return true;
      }),
    ];
    return { ...normalizedDurableValues, messages } as ReconnectInputSnapshot;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }
    return undefined;
  }
}

export class StreamReplayGapError extends Error {
  constructor(
    readonly gap: StreamReplayGapData,
    readonly recoveryAttempts: number,
    readonly recoveryCause?: unknown,
  ) {
    super(
      `Unable to recover SSE history after ${recoveryAttempts} attempts (requested ${gap.requested_event_id ?? "initial stream"}, earliest ${gap.earliest_available_event_id ?? "none"})`,
    );
    this.name = "StreamReplayGapError";
  }
}

function parseStreamReplayGap(data: unknown): StreamReplayGapData {
  if (typeof data !== "object" || data === null) {
    throw new Error("Invalid stream replay gap payload.");
  }

  const value = data as Record<string, unknown>;
  const requestedEventId = value.requested_event_id;
  const earliestAvailableEventId = value.earliest_available_event_id;
  const latestAvailableEventId = value.latest_available_event_id;
  if (
    value.code !== "stream_replay_gap" ||
    typeof value.run_id !== "string" ||
    (requestedEventId !== null && typeof requestedEventId !== "string") ||
    (earliestAvailableEventId !== null &&
      typeof earliestAvailableEventId !== "string") ||
    (latestAvailableEventId !== null &&
      typeof latestAvailableEventId !== "string") ||
    value.recovery !== "reload_durable_state"
  ) {
    throw new Error("Invalid stream replay gap payload.");
  }

  return value as StreamReplayGapData;
}

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
 * Preflight a reconnect and return the run record when it can be read. A
 * missing record or failed request returns ``undefined`` so a legitimately
 * active reconnect falls back to the original join and the terminal-state
 * check remains owned by the caller.
 *
 * Any error (404 for an evicted record, network blip, auth hiccup, …) falls
 * back to the original join so a legitimately active reconnect is never
 * silently suppressed.
 */
async function getReconnectRun(
  client: LangGraphClient,
  threadId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<Awaited<ReturnType<LangGraphClient["runs"]["get"]>> | undefined> {
  try {
    return await client.runs.get(threadId, runId, { signal });
  } catch {
    return undefined;
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

function rememberReconnectRun(
  threadId: string | null | undefined,
  runId: string,
): void {
  if (typeof window === "undefined" || !threadId) return;

  try {
    window.sessionStorage.setItem(`lg:stream:${threadId}`, runId);
  } catch {
    // Ignore storage access failures so gap recovery remains usable.
  }
}

async function* recoverStreamReplayGaps({
  client,
  threadId,
  expectedRunId,
  initialStream,
  resume,
  signal,
  reconnectRun,
}: {
  client: LangGraphClient;
  threadId: string | null | undefined;
  expectedRunId: () => string | undefined;
  initialStream: AsyncIterable<StreamPart>;
  resume: (runId: string, lastEventId?: string) => AsyncIterable<StreamPart>;
  signal?: AbortSignal;
  reconnectRun?: Awaited<ReturnType<LangGraphClient["runs"]["get"]>>;
}): AsyncGenerator<StreamPart> {
  let stream = initialStream;
  let recoveryAttempts = 0;

  while (true) {
    let gap: StreamReplayGapData | undefined;
    for await (const entry of stream) {
      if (entry.event === "gap") {
        gap = parseStreamReplayGap(entry.data);
        break;
      }
      yield entry;
    }

    if (!gap) {
      return;
    }

    const runId = expectedRunId() ?? gap.run_id;
    if (!threadId || gap.run_id !== runId) {
      throw new Error(
        "Stream replay gap does not match the active thread run.",
      );
    }
    if (recoveryAttempts >= MAX_STREAM_GAP_RECOVERIES) {
      throw new StreamReplayGapError(gap, recoveryAttempts);
    }
    recoveryAttempts += 1;

    // The SDK would otherwise ignore an unknown `gap` event and report a
    // normal finish. Surface a custom control event to DeerFlow's hook, reload
    // durable values, then resume after the retained tail when it exists
    // (or rejoin without a cursor if the buffer is empty).
    clearReconnectRun(threadId, runId);
    yield {
      event: "custom",
      data: { type: "stream_replay_gap", ...gap },
    };

    const durableState = await client.threads
      .getState(threadId, undefined, { signal })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") {
          throw error;
        }
        throw new StreamReplayGapError(gap, recoveryAttempts, error);
      });
    if (durableState.values != null) {
      // A gap can arrive after the initial hydration frame but before the
      // input reaches the checkpoint. Rebuild the snapshot from run metadata
      // so this recovery path cannot overwrite the rescued human message.
      const recoveredSnapshot = reconnectRun
        ? await loadReconnectInputSnapshot(
            client,
            threadId,
            runId,
            reconnectRun,
            durableState.values,
            signal,
          )
        : undefined;
      yield {
        event: "values",
        data: recoveredSnapshot ?? durableState.values,
      };
    }

    rememberReconnectRun(threadId, runId);
    stream = resume(runId, gap.latest_available_event_id ?? undefined);
  }
}

async function* handleInactiveRunStream({
  threadId,
  expectedRunId,
  stream,
}: {
  threadId: string | null | undefined;
  expectedRunId: () => string | undefined;
  stream: AsyncIterable<StreamPart>;
}): AsyncGenerator<StreamPart> {
  try {
    yield* stream;
  } catch (error) {
    const runId = expectedRunId();
    if (runId && isInactiveRunStreamError(error)) {
      clearReconnectRun(threadId, runId);
      return;
    }
    throw error;
  }
}

function createCompatibleClient(isMock?: boolean): LangGraphClient {
  if (isStaticWebsiteOnly() && !isMock) {
    return createStaticClient();
  }

  const apiUrl = getLangGraphBaseURL(isMock);
  const client = new LangGraphClient({
    apiUrl,
    onRequest: injectCsrfHeader,
  });

  const originalRunStream = client.runs.stream.bind(client.runs);
  const originalJoinStream = client.runs.joinStream.bind(client.runs);
  // Preserve the SDK's lazy AsyncIterable contract. Its StreamManager consumes
  // this return value with `for await`, so run creation still starts on first
  // iteration rather than when `runs.stream()` is called.
  client.runs.stream = async function* (threadId, assistantId, payload) {
    const sanitizedPayload = forceChatRunStreamOptions(payload);
    const originalOnRunCreated = sanitizedPayload?.onRunCreated;
    let runId: string | undefined;
    const initialStream = originalRunStream(threadId, assistantId, {
      ...sanitizedPayload,
      onRunCreated(meta) {
        runId = meta.run_id;
        originalOnRunCreated?.(meta);
      },
    });

    const recoveredStream = recoverStreamReplayGaps({
      client,
      threadId,
      expectedRunId: () => runId,
      initialStream,
      signal: streamOptionSignal(sanitizedPayload),
      reconnectRun: undefined,
      resume: (resolvedRunId, lastEventId) => {
        // Keep the recovery run id available to the shared inactive-stream
        // handler even if the SDK omitted its onRunCreated callback.
        runId = resolvedRunId;
        return originalJoinStream(threadId, resolvedRunId, {
          lastEventId,
          signal: sanitizedPayload?.signal,
          streamMode: sanitizedPayload?.streamMode,
        });
      },
    });
    yield* handleInactiveRunStream({
      threadId,
      expectedRunId: () => runId,
      stream: recoveredStream,
    });
  } as typeof client.runs.stream;

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

  client.runs.joinStream = async function* (threadId, runId, options) {
    // Short-circuit reconnects to runs that have already finished: otherwise a
    // reload after the backend's stream bridge is reaped blocks forever on a
    // drained condition variable, pinning ``isLoading`` true so the first
    // post-reload message is routed to ``stop`` instead of ``submit``.
    const reconnectSignal = streamOptionSignal(options);
    const reconnectRun = threadId
      ? await getReconnectRun(client, threadId, runId, reconnectSignal)
      : undefined;
    if (reconnectRun && TERMINAL_RUN_STATUSES.has(reconnectRun.status)) {
      clearReconnectRun(threadId, runId);
      return;
    }
    if (threadId && reconnectRun) {
      const reconnectSnapshot = await loadReconnectInputSnapshot(
        client,
        threadId,
        runId,
        reconnectRun,
        undefined,
        reconnectSignal,
      );
      if (reconnectSnapshot) {
        // This is an internal hydration frame. The requested network stream
        // remains incremental; the SDK receives the current input before any
        // replayed messages-tuple AI/tool chunks and deduplicates it against
        // later history or stream copies by message id.
        yield { event: "values", data: reconnectSnapshot };
      }
    }
    const sanitizedOptions = forceChatRunStreamOptions(options);
    yield* handleInactiveRunStream({
      threadId,
      expectedRunId: () => runId,
      stream: recoverStreamReplayGaps({
        client,
        threadId,
        expectedRunId: () => runId,
        initialStream: originalJoinStream(threadId, runId, sanitizedOptions),
        signal: reconnectSignal,
        reconnectRun,
        resume: (resolvedRunId, lastEventId) =>
          originalJoinStream(threadId, resolvedRunId, {
            ...sanitizedOptions,
            lastEventId,
          }),
      }),
    });
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
