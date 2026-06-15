import type { Message } from "@langchain/langgraph-sdk";
import { useCallback, useEffect, useRef } from "react";

import {
  extractBlocksIncremental,
  fetchResolvedBlockHistory,
  getHistoryMessageKey,
} from "@/core/genui/history";
import { perfMetrics } from "@/core/perf/metrics";
import { useBlockStore } from "@/core/genui/store";

const DEBOUNCE_MS = 500;

export function useUIBlockExtractor(
  threadId: string | null | undefined,
  messages: Message[],
  isLoading: boolean,
) {
  const extractedKeysRef = useRef<Set<string>>(new Set());
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevIsLoadingRef = useRef(false);

  const runIncrementalExtraction = useCallback(async () => {
    if (!threadId) return;

    const newMessages = messages.filter(
      (m) => !extractedKeysRef.current.has(getHistoryMessageKey(m)),
    );
    if (newMessages.length === 0) return;

    const result = await extractBlocksIncremental(threadId, newMessages);
    perfMetrics.recordUIBlocksExtract();
    for (const block of result.blocks) {
      useBlockStore.getState().upsertBlock(threadId, block);
    }
    for (const msg of newMessages) {
      extractedKeysRef.current.add(getHistoryMessageKey(msg));
    }
  }, [threadId, messages]);

  useEffect(() => {
    if (!threadId || !isLoading) return;

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    debounceTimerRef.current = setTimeout(() => {
      void runIncrementalExtraction();
    }, DEBOUNCE_MS);

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, [threadId, isLoading, messages, runIncrementalExtraction]);

  useEffect(() => {
    const wasLoading = prevIsLoadingRef.current;
    prevIsLoadingRef.current = isLoading;

    if (wasLoading && !isLoading && threadId) {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }

      void fetchResolvedBlockHistory(threadId, messages).then((result) => {
        perfMetrics.recordUIBlocksExtract();
        useBlockStore.getState().replaceAllBlocks(threadId, result.blocks);
        extractedKeysRef.current = new Set(result.blockIdsByMessageKey.keys());
      });
    }
  }, [isLoading, threadId, messages]);

  useEffect(() => {
    if (!threadId) {
      extractedKeysRef.current = new Set();
    }
  }, [threadId]);
}
