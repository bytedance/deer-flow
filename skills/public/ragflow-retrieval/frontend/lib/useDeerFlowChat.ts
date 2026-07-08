"use client";

import { useCallback, useState } from "react";

import {
  fetchQuerySummary,
  streamDeerFlowAnswer,
  type CitationItem,
  type QuerySummary,
  type StreamDeerFlowAnswerOptions,
} from "./deerflow-stream";

export interface UseDeerFlowChatState {
  answer: string;
  citations: CitationItem[];
  summary: QuerySummary | null;
  threadId: string | null;
  loading: boolean;
  error: string | null;
}

export interface UseDeerFlowChatReturn extends UseDeerFlowChatState {
  ask: (question: string) => Promise<void>;
  reset: () => void;
}

/**
 * React hook: send a question to DeerFlow 2.0 and stream the assistant answer.
 * After the run completes, loads ragflow-retrieval citations from thread artifacts.
 */
export function useDeerFlowChat(
  streamOptions?: StreamDeerFlowAnswerOptions,
): UseDeerFlowChatReturn {
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<CitationItem[]>([]);
  const [summary, setSummary] = useState<QuerySummary | null>(null);
  const [threadId, setThreadId] = useState<string | null>(
    streamOptions?.threadId ?? null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback(() => {
    setAnswer("");
    setCitations([]);
    setSummary(null);
    setError(null);
  }, []);

  const ask = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed) return;

      setLoading(true);
      setError(null);
      setAnswer("");
      setCitations([]);
      setSummary(null);

      try {
        const result = await streamDeerFlowAnswer(
          trimmed,
          {
            onDelta: (_delta, fullText) => setAnswer(fullText),
            onError: (err) => setError(err.message),
          },
          { ...streamOptions, threadId: streamOptions?.threadId ?? threadId ?? undefined },
        );

        setThreadId(result.threadId);

        const loaded = await fetchQuerySummary(result.threadId);
        if (loaded) {
          setSummary(loaded);
          if (loaded.citations?.length) {
            setCitations(loaded.citations);
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [streamOptions, threadId],
  );

  return {
    ask,
    reset,
    answer,
    citations,
    summary,
    threadId,
    loading,
    error,
  };
}
