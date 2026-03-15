"use client";

import type { Message } from "@langchain/langgraph-sdk";

interface UsageMetadata {
  input_tokens: number;
  output_tokens: number;
  total_tokens?: number;
}

function formatTokenCount(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
  return String(count);
}

/**
 * Compact token usage badge shown next to the copy button in the message toolbar.
 * Reads usage_metadata from an AI message (already streamed by LangGraph).
 */
export function TokenUsageBadge({ message }: { message: Message }) {
  if (message.type !== "ai") return null;

  // usage_metadata is present on AIMessage but not reflected in the SDK TS types
  const usage = (message as Message & { usage_metadata?: UsageMetadata })
    .usage_metadata;

  if (!usage) return null;

  const { input_tokens, output_tokens } = usage;
  if (!input_tokens && !output_tokens) return null;

  const total = (input_tokens ?? 0) + (output_tokens ?? 0);

  return (
    <div
      className="text-muted-foreground flex items-center gap-0.5 rounded px-1 text-[10px] tabular-nums select-none"
      title={`Токены: ${input_tokens} вход / ${output_tokens} выход / ${total} всего`}
    >
      <span>↑{formatTokenCount(input_tokens ?? 0)}</span>
      <span className="opacity-40">·</span>
      <span>↓{formatTokenCount(output_tokens ?? 0)}</span>
    </div>
  );
}

/**
 * Session-level token totals computed from all messages + optional background entries.
 */
export interface SessionTokenTotals {
  input: number;
  output: number;
  backgroundEntries: Array<{ process: string; input: number; output: number }>;
}

export function computeSessionTotals(
  messages: Message[],
  backgroundUsage?: Array<{
    process: string;
    input_tokens: number;
    output_tokens: number;
  }>,
): SessionTokenTotals {
  let input = 0;
  let output = 0;

  for (const msg of messages) {
    if (msg.type !== "ai") continue;
    const usage = (msg as Message & { usage_metadata?: UsageMetadata })
      .usage_metadata;
    if (!usage) continue;
    input += usage.input_tokens ?? 0;
    output += usage.output_tokens ?? 0;
  }

  const backgroundEntries = (backgroundUsage ?? []).map((e) => ({
    process: e.process,
    input: e.input_tokens,
    output: e.output_tokens,
  }));

  // Also add background totals
  for (const e of backgroundEntries) {
    input += e.input;
    output += e.output;
  }

  return { input, output, backgroundEntries };
}

/**
 * Session total token counter shown at the bottom of the message list.
 */
export function SessionTokenCounter({
  messages,
  backgroundUsage,
}: {
  messages: Message[];
  backgroundUsage?: Array<{
    process: string;
    input_tokens: number;
    output_tokens: number;
  }>;
}) {
  const totals = computeSessionTotals(messages, backgroundUsage);
  if (totals.input === 0 && totals.output === 0) return null;

  const total = totals.input + totals.output;

  const backgroundLines = totals.backgroundEntries
    .map((e) => `  ${e.process}: ↑${e.input} · ↓${e.output}`)
    .join("\n");

  const tooltipText = [
    `Сессия: ${totals.input} вход / ${totals.output} выход`,
    backgroundLines ? `Фоновые процессы:\n${backgroundLines}` : "",
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <div
      className="text-muted-foreground/60 flex items-center justify-center gap-1.5 py-2 text-[11px] tabular-nums select-none"
      title={tooltipText}
    >
      <span>Сессия:</span>
      <span>↑{formatTokenCount(totals.input)}</span>
      <span className="opacity-40">·</span>
      <span>↓{formatTokenCount(totals.output)}</span>
      <span className="opacity-40">·</span>
      <span>{formatTokenCount(total)} всего</span>
      {totals.backgroundEntries.length > 0 && (
        <span className="opacity-50">
          (+{totals.backgroundEntries.length} фон)
        </span>
      )}
    </div>
  );
}
