"use client";

import { Client as LangGraphClient } from "@langchain/langgraph-sdk/client";

import { getLangGraphBaseURL } from "../config";

import { sanitizeRunStreamOptions } from "./stream-mode";

const _clientByApiUrl = new Map<string, LangGraphClient>();

/**
 * Returns a LangGraph client with stream-mode sanitization for langgraph-api 0.7.x compatibility.
 * The SDK may expand streamMode (e.g. tools, updates, events) which causes 422 validation errors.
 * @see https://github.com/bytedance/deer-flow/issues/1043
 */
export function getAPIClient(isMock?: boolean): LangGraphClient {
  const apiUrl = getLangGraphBaseURL(isMock);
  const cached = _clientByApiUrl.get(apiUrl);
  if (cached) return cached;

  const raw = new LangGraphClient({
    apiUrl,
  });

  const rawRuns = raw.runs;

  const wrappedRuns = {
    ...rawRuns,
    stream: (
      threadId: string | null,
      assistantId: string,
      payload?: Record<string, unknown>,
    ) => {
      const sanitized = sanitizeRunStreamOptions(payload);
      return (
        rawRuns.stream as (a: string | null, b: string, c?: unknown) => unknown
      )(threadId, assistantId, sanitized);
    },
    joinStream: (
      threadId: string | undefined | null,
      runId: string,
      options?: Record<string, unknown>,
    ) => {
      const sanitized = sanitizeRunStreamOptions(options);
      return rawRuns.joinStream(threadId, runId, sanitized);
    },
  };

  const wrapped = Object.create(LangGraphClient.prototype) as LangGraphClient;
  Object.assign(wrapped, raw);
  (wrapped as { runs: typeof wrappedRuns }).runs = wrappedRuns;

  _clientByApiUrl.set(apiUrl, wrapped);
  return wrapped;
}
