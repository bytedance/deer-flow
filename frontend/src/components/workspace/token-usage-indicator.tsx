"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { CoinsIcon } from "lucide-react";
import { useMemo } from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import { accumulateUsage, formatTokenCount } from "@/core/messages/usage";
import { cn } from "@/lib/utils";

interface TokenUsageIndicatorProps {
  messages: Message[];
  className?: string;
}

export function TokenUsageIndicator({
  messages,
  className,
}: TokenUsageIndicatorProps) {
  const { t } = useI18n();

  const usage = useMemo(() => accumulateUsage(messages), [messages]);

  if (!usage) {
    return null;
  }

  return (
    <Tooltip delayDuration={200}>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={cn(
            "text-muted-foreground flex cursor-default items-center gap-1 text-xs",
            className,
          )}
        >
          <CoinsIcon size={14} />
          <span>{formatTokenCount(usage.totalTokens)}</span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="end">
        <div className="space-y-1 text-xs">
          <div className="font-medium">{t.tokenUsage.title}</div>
          <div className="flex justify-between gap-4">
            <span>{t.tokenUsage.input}</span>
            <span className="font-mono">
              {formatTokenCount(usage.inputTokens)}
            </span>
          </div>
          <div className="flex justify-between gap-4">
            <span>{t.tokenUsage.output}</span>
            <span className="font-mono">
              {formatTokenCount(usage.outputTokens)}
            </span>
          </div>
          <div className="border-t pt-1">
            <div className="flex justify-between gap-4">
              <span>{t.tokenUsage.total}</span>
              <span className="font-mono font-medium">
                {formatTokenCount(usage.totalTokens)}
              </span>
            </div>
          </div>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
