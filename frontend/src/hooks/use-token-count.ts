"use client";

import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import { useMemo } from "react";

interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

/**
 * Aggregate actual token usage from LLM responses (usage_metadata on AI messages).
 * This reflects the real tokens consumed by the LLM, including system prompt,
 * tool schemas, reasoning tokens, and everything else.
 */
export function useTokenUsage(messages: Message[]): TokenUsage {
  return useMemo(() => {
    let inputTokens = 0;
    let outputTokens = 0;

    for (const message of messages) {
      if (message.type === "ai") {
        const aiMsg = message as AIMessage;
        if (aiMsg.usage_metadata) {
          inputTokens += aiMsg.usage_metadata.input_tokens ?? 0;
          outputTokens += aiMsg.usage_metadata.output_tokens ?? 0;
        }
      }
    }

    return {
      inputTokens,
      outputTokens,
      totalTokens: inputTokens + outputTokens,
    };
  }, [messages]);
}

/**
 * Format token count for display.
 */
export function formatTokenCount(count: number): string {
  if (count === 0) return "0";
  if (count < 1000) return `${count}`;
  if (count < 10000) return `${(count / 1000).toFixed(1)}k`;
  return `${Math.round(count / 1000)}k`;
}

// Pricing per million tokens (input/output) in USD
const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  // Claude
  "claude-sonnet-4-6": { input: 3, output: 15 },
  "claude-sonnet-4-5": { input: 3, output: 15 },
  "claude-sonnet-3-5": { input: 3, output: 15 },
  "claude-haiku-4-5": { input: 0.8, output: 4 },
  "claude-haiku-3-5": { input: 0.8, output: 4 },
  "claude-opus-4-6": { input: 15, output: 75 },
  "claude-opus-4": { input: 15, output: 75 },
  // OpenAI
  "gpt-4o": { input: 2.5, output: 10 },
  "gpt-4o-mini": { input: 0.15, output: 0.6 },
  "gpt-4.1": { input: 2, output: 8 },
  "gpt-4.1-mini": { input: 0.4, output: 1.6 },
  "gpt-4.1-nano": { input: 0.1, output: 0.4 },
  "o3": { input: 10, output: 40 },
  "o3-mini": { input: 1.1, output: 4.4 },
  "o4-mini": { input: 1.1, output: 4.4 },
  // Google
  "gemini-2.5-pro": { input: 1.25, output: 10 },
  "gemini-2.5-flash": { input: 0.15, output: 0.6 },
  "gemini-2.0-flash": { input: 0.1, output: 0.4 },
  // DeepSeek
  "deepseek-chat": { input: 0.27, output: 1.1 },
  "deepseek-reasoner": { input: 0.55, output: 2.19 },
};

/**
 * Calculate cost from actual input/output token counts using model pricing.
 */
export function calculateCost(
  usage: TokenUsage,
  modelName: string | undefined,
): number | null {
  if (!modelName || usage.totalTokens === 0) return null;

  // Find pricing by exact match or partial match
  let pricing = MODEL_PRICING[modelName];
  if (!pricing) {
    const key = Object.keys(MODEL_PRICING).find((k) =>
      modelName.toLowerCase().includes(k.toLowerCase()),
    );
    if (key) pricing = MODEL_PRICING[key];
  }
  if (!pricing) return null;

  return (
    (usage.inputTokens * pricing.input +
      usage.outputTokens * pricing.output) /
    1_000_000
  );
}

/**
 * Format cost for display.
 */
export function formatCost(cost: number): string {
  if (cost < 0.01) return "<$0.01";
  if (cost < 1) return `$${cost.toFixed(2)}`;
  return `$${cost.toFixed(2)}`;
}
