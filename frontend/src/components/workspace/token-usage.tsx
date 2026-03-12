"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { ChevronDownIcon, CoinsIcon } from "lucide-react";
import { useMemo, useState } from "react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { extractContentFromMessage } from "@/core/messages/utils";
import { cn } from "@/lib/utils";

// Pricing per million tokens: [input, cached_input, output]
const MODEL_PRICING: Record<string, [number, number, number]> = {
  // Anthropic
  "claude-sonnet-4-20250514": [3, 0.3, 12],
  "claude-sonnet-4": [3, 0.3, 12],
  // OpenAI
  "gpt-4o": [2.5, 1.25, 10],
  // Google Gemini
  "gemini-2.5-flash": [0.15, 0.0375, 0.6],
  "gemini-2.5-flash-preview-05-20": [0.15, 0.0375, 0.6],
  "gemini-3.1-flash-lite-preview": [0.25, 0.025, 1.5],
  "gemini-3.1-pro-preview": [2, 0.2, 12],
};

const DEFAULT_PRICING: [number, number, number] = [3, 0.3, 12];

function getPricing(modelName: string | undefined): [number, number, number] {
  if (!modelName) return DEFAULT_PRICING;
  // Exact match first
  if (MODEL_PRICING[modelName]) return MODEL_PRICING[modelName];
  // Prefix match (e.g. "claude-sonnet-4-20250514" matches "claude-sonnet-4")
  for (const [key, pricing] of Object.entries(MODEL_PRICING)) {
    if (modelName.startsWith(key) || key.startsWith(modelName)) return pricing;
  }
  return DEFAULT_PRICING;
}

function getModelDisplayName(modelName: string | undefined): string {
  if (!modelName) return "Unknown";
  if (modelName.includes("claude-sonnet-4")) return "Claude Sonnet 4.6";
  if (modelName.includes("gpt-4o")) return "GPT-4o";
  if (modelName.includes("gemini-3.1-flash")) return "Gemini 3.1 Flash Lite";
  if (modelName.includes("gemini-3.1-pro")) return "Gemini 3.1 Pro";
  if (modelName.includes("gemini-2.5-flash")) return "Gemini 2.5 Flash";
  return modelName;
}

interface UsageMetadata {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  input_token_details?: {
    cache_read?: number;
    cache_creation?: number;
  };
}

interface TurnUsage {
  turnIndex: number;
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number;
  cost: number;
  label: string;
}

function getUsageFromMessage(message: Message): UsageMetadata | null {
  if (message.type !== "ai") return null;

  const msg = message as Message & { usage_metadata?: UsageMetadata };
  if (msg.usage_metadata) return msg.usage_metadata;

  const respMeta = (
    message as Message & { response_metadata?: Record<string, unknown> }
  ).response_metadata;
  if (respMeta?.usage_metadata) return respMeta.usage_metadata as UsageMetadata;
  if (respMeta?.token_usage) return respMeta.token_usage as UsageMetadata;

  return null;
}

function getModelNameFromMessage(message: Message): string | undefined {
  const respMeta = (
    message as Message & { response_metadata?: Record<string, unknown> }
  ).response_metadata;
  return respMeta?.model_name as string | undefined;
}

function calculateCost(
  inputTokens: number,
  outputTokens: number,
  cachedTokens: number,
  pricing: [number, number, number],
): number {
  const [inRate, cachedRate, outRate] = pricing;
  const uncachedInput = inputTokens - cachedTokens;
  return (
    (uncachedInput / 1_000_000) * inRate +
    (cachedTokens / 1_000_000) * cachedRate +
    (outputTokens / 1_000_000) * outRate
  );
}

function formatTokenCount(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
  return count.toString();
}

function formatCost(cost: number): string {
  if (cost < 0.001) return "$0.00";
  if (cost < 0.01) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

function getMessagePreview(message: Message, maxLen = 40): string {
  const content = extractContentFromMessage(message);
  if (!content) return "...";
  const text = content.replace(/\n/g, " ").trim();
  return text.length > maxLen ? text.substring(0, maxLen) + "..." : text;
}

export function TokenUsage({
  className,
  messages,
}: {
  className?: string;
  messages: Message[];
}) {
  const [open, setOpen] = useState(false);

  const {
    inputTokens,
    outputTokens,
    cachedTokens,
    totalTokens,
    cost,
    turns,
    modelName,
    pricing,
  } = useMemo(() => {
    let input = 0;
    let output = 0;
    let cached = 0;
    const turns: TurnUsage[] = [];
    let turnIndex = 0;
    let detectedModel: string | undefined;

    for (const message of messages) {
      const usage = getUsageFromMessage(message);
      if (usage) {
        const msgInput = usage.input_tokens ?? 0;
        const msgOutput = usage.output_tokens ?? 0;
        const msgCached = usage.input_token_details?.cache_read ?? 0;
        if (!detectedModel) {
          detectedModel = getModelNameFromMessage(message);
        }
        const msgPricing = getPricing(detectedModel);
        input += msgInput;
        output += msgOutput;
        cached += msgCached;
        turnIndex++;
        turns.push({
          turnIndex,
          inputTokens: msgInput,
          outputTokens: msgOutput,
          cachedTokens: msgCached,
          cost: calculateCost(msgInput, msgOutput, msgCached, msgPricing),
          label: getMessagePreview(message),
        });
      }
    }

    const total = input + output;
    const pricing = getPricing(detectedModel);

    return {
      inputTokens: input,
      outputTokens: output,
      cachedTokens: cached,
      totalTokens: total,
      cost: calculateCost(input, output, cached, pricing),
      turns,
      modelName: detectedModel,
      pricing,
    };
  }, [messages]);

  if (totalTokens === 0) return null;

  const [inRate, cachedRate, outRate] = pricing;
  const cacheHitRate =
    inputTokens > 0 ? Math.round((cachedTokens / inputTokens) * 100) : 0;
  const displayName = getModelDisplayName(modelName);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className={cn(
            "text-muted-foreground hover:text-foreground flex cursor-pointer items-center gap-1.5 text-[11px] tabular-nums transition-colors",
            className,
          )}
        >
          <CoinsIcon className="size-3 shrink-0 opacity-60" />
          <span>{formatTokenCount(totalTokens)} tokens</span>
          <span className="opacity-40">|</span>
          <span>{formatCost(cost)}</span>
          {cachedTokens > 0 && (
            <span className="text-green-500 opacity-80">
              {cacheHitRate}% cached
            </span>
          )}
          <ChevronDownIcon className="size-3 opacity-40" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end" sideOffset={8}>
        <div className="space-y-3 p-3">
          {/* Summary */}
          <div className="space-y-1.5">
            <div className="text-foreground text-xs font-medium">
              Token Usage Summary
            </div>
            <div className="text-muted-foreground grid grid-cols-3 gap-2 text-[11px]">
              <div className="space-y-0.5">
                <div className="text-foreground text-xs font-medium">
                  {formatTokenCount(inputTokens)}
                </div>
                <div>Input</div>
                {cachedTokens > 0 && (
                  <div className="text-green-500">
                    {formatTokenCount(cachedTokens)} cached
                  </div>
                )}
                <div className="opacity-60">
                  {formatCost(
                    ((inputTokens - cachedTokens) / 1_000_000) * inRate +
                      (cachedTokens / 1_000_000) * cachedRate,
                  )}
                </div>
              </div>
              <div className="space-y-0.5">
                <div className="text-foreground text-xs font-medium">
                  {formatTokenCount(outputTokens)}
                </div>
                <div>Output</div>
                <div className="opacity-60">
                  {formatCost((outputTokens / 1_000_000) * outRate)}
                </div>
              </div>
              <div className="space-y-0.5">
                <div className="text-foreground text-xs font-medium">
                  {formatCost(cost)}
                </div>
                <div>Total Cost</div>
                <div className="opacity-60">
                  {turns.length} turn{turns.length !== 1 ? "s" : ""}
                </div>
              </div>
            </div>
          </div>

          {/* Per-turn breakdown */}
          {turns.length > 0 && (
            <div className="space-y-1">
              <div className="text-muted-foreground border-t pt-2 text-[10px] font-medium uppercase tracking-wide">
                Per-turn breakdown
              </div>
              <div className="max-h-48 space-y-0.5 overflow-y-auto">
                {turns.map((turn) => (
                  <div
                    key={turn.turnIndex}
                    className="hover:bg-muted/50 flex items-center justify-between rounded px-1.5 py-1 text-[11px]"
                  >
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="text-muted-foreground shrink-0 font-mono text-[10px]">
                        #{turn.turnIndex}
                      </span>
                      <span className="text-muted-foreground truncate">
                        {turn.label}
                      </span>
                    </div>
                    <div className="text-muted-foreground ml-2 flex shrink-0 items-center gap-2 tabular-nums">
                      {turn.cachedTokens > 0 && (
                        <span className="text-green-500 text-[10px]">
                          {Math.round(
                            (turn.cachedTokens / turn.inputTokens) * 100,
                          )}
                          %
                        </span>
                      )}
                      <span
                        title={`In: ${turn.inputTokens.toLocaleString()}${turn.cachedTokens > 0 ? ` (${turn.cachedTokens.toLocaleString()} cached)` : ""}, Out: ${turn.outputTokens.toLocaleString()}`}
                      >
                        {formatTokenCount(turn.inputTokens + turn.outputTokens)}
                      </span>
                      <span className="w-12 text-right opacity-70">
                        {formatCost(turn.cost)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Pricing note */}
          <div className="text-muted-foreground/50 border-t pt-2 text-[10px]">
            {displayName}: ${inRate}/1M in
            {cachedRate > 0 ? `, $${cachedRate}/1M cached` : ""}, ${outRate}/1M
            out
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
