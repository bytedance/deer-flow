"use client";

import { useCallback, useEffect, useState } from "react";

import { type GreetingResponse, fetchGreeting } from "./api";

const GREETING_TIMEOUT_MS = 2000;

const FALLBACK_GREETING: GreetingResponse = {
  greeting: "你好！有什么我可以帮您的吗？",
  suggestions: ["查看设备状态", "生成今日报告", "分析异常趋势"],
  language: "zh-CN",
};

// Time-based greeting prefixes by language
const TIME_PREFIXES = {
  "zh-CN": {
    morning: "早上好",
    afternoon: "下午好",
    evening: "晚上好",
  },
  "en-US": {
    morning: "Good morning",
    afternoon: "Good afternoon",
    evening: "Good evening",
  },
};

const ALL_TIME_PREFIXES = [
  ...Object.values(TIME_PREFIXES["zh-CN"]),
  ...Object.values(TIME_PREFIXES["en-US"]),
];

/**
 * Get the correct time-of-day key based on the client's local time.
 */
function getClientTimeKey(): "morning" | "afternoon" | "evening" {
  const hour = new Date().getHours();
  if (hour < 12) return "morning";
  if (hour < 18) return "afternoon";
  return "evening";
}

/**
 * Replace any time-based greeting prefix with the correct one for the client's local time.
 *
 * This fixes the issue where the backend uses server time (e.g., UTC in Docker)
 * but the user expects greetings based on their local timezone.
 */
function fixGreetingTime(greeting: string, lang: string): string {
  const clientTimeKey = getClientTimeKey();
  const prefixes = TIME_PREFIXES[lang as keyof typeof TIME_PREFIXES] || TIME_PREFIXES["zh-CN"];
  const correctPrefix = prefixes[clientTimeKey];

  // Check if the greeting starts with any time-based prefix
  for (const prefix of ALL_TIME_PREFIXES) {
    if (greeting.startsWith(prefix)) {
      // Replace the old prefix with the correct one
      return greeting.replace(prefix, correctPrefix);
    }
  }

  // No time prefix found, return as-is
  return greeting;
}

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
      // Fix the greeting time prefix based on client's local time
      const fixedGreeting = fixGreetingTime(result.greeting, result.language);
      setGreeting({ ...result, greeting: fixedGreeting });
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
