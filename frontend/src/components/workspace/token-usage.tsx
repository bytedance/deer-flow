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

// Claude Sonnet 4.6 pricing (per million tokens)
const INPUT_COST_PER_MILLION = 3;
const OUTPUT_COST_PER_MILLION = 12;

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

  const { inputTokens, outputTokens, totalTokens, cost, turns } =
    useMemo(() => {
      let input = 0;
      let output = 0;
      const turns: TurnUsage[] = [];
      let turnIndex = 0;

      for (const message of messages) {
        const usage = getUsageFromMessage(message);
        if (usage) {
          const msgInput = usage.input_tokens ?? 0;
          const msgOutput = usage.output_tokens ?? 0;
          input += msgInput;
          output += msgOutput;
          turnIndex++;
          turns.push({
            turnIndex,
            inputTokens: msgInput,
            outputTokens: msgOutput,
            cost:
              (msgInput / 1_000_000) * INPUT_COST_PER_MILLION +
              (msgOutput / 1_000_000) * OUTPUT_COST_PER_MILLION,
            label: getMessagePreview(message),
          });
        }
      }

      const total = input + output;
      const estimatedCost =
        (input / 1_000_000) * INPUT_COST_PER_MILLION +
        (output / 1_000_000) * OUTPUT_COST_PER_MILLION;

      return {
        inputTokens: input,
        outputTokens: output,
        totalTokens: total,
        cost: estimatedCost,
        turns,
      };
    }, [messages]);

  if (totalTokens === 0) return null;

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
          <ChevronDownIcon className="size-3 opacity-40" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-80 p-0"
        align="end"
        sideOffset={8}
      >
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
                <div className="opacity-60">
                  {formatCost(
                    (inputTokens / 1_000_000) * INPUT_COST_PER_MILLION,
                  )}
                </div>
              </div>
              <div className="space-y-0.5">
                <div className="text-foreground text-xs font-medium">
                  {formatTokenCount(outputTokens)}
                </div>
                <div>Output</div>
                <div className="opacity-60">
                  {formatCost(
                    (outputTokens / 1_000_000) * OUTPUT_COST_PER_MILLION,
                  )}
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
                      <span title={`In: ${turn.inputTokens.toLocaleString()}, Out: ${turn.outputTokens.toLocaleString()}`}>
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
            Estimated cost based on Claude Sonnet 4.6 pricing ($3/1M in,
            $12/1M out)
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
