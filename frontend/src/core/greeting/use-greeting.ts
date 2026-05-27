"use client";

import { useCallback, useEffect, useState } from "react";

import { type GreetingResponse, fetchGreeting } from "./api";

const GREETING_TIMEOUT_MS = 2000;

const FALLBACK_GREETING: GreetingResponse = {
  greeting: "你好！有什么我可以帮您的吗？",
  suggestions: ["查看设备状态", "生成今日报告", "分析异常趋势"],
  language: "zh-CN",
};

interface UseGreetingResult {
  greeting: GreetingResponse | null;
  isLoading: boolean;
  error: Error | null;
  retry: () => void;
}

export function useGreeting(
  threadId: string | undefined,
  enabled: boolean,
): UseGreetingResult {
  const [greeting, setGreeting] = useState<GreetingResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const load = useCallback(async () => {
    if (!threadId || !enabled) return;
    setIsLoading(true);
    setError(null);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), GREETING_TIMEOUT_MS);

    try {
      const result = await fetchGreeting(threadId);
      setGreeting(result);
    } catch (err) {
      if (controller.signal.aborted) {
        setGreeting(FALLBACK_GREETING);
      } else {
        setError(err instanceof Error ? err : new Error(String(err)));
        setGreeting(FALLBACK_GREETING);
      }
    } finally {
      clearTimeout(timeout);
      setIsLoading(false);
    }
  }, [threadId, enabled]);

  useEffect(() => {
    void load();
  }, [load]);

  return { greeting, isLoading, error, retry: load };
}
