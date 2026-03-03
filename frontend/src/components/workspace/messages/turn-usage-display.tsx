import { ArrowDownIcon, ArrowUpIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { useTurnUsage } from "@/core/threads/usage-context";

export type TurnUsageEstimate = {
  inputTokens: number;
  outputTokens: number;
};

export function estimateTokensFromText(text: string): number {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return 0;
  return Math.max(1, Math.ceil(normalized.length / 4));
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function ElapsedTime({ startTime, isLoading }: { startTime: number; isLoading: boolean }) {
  const [elapsed, setElapsed] = useState(() =>
    ((Date.now() - startTime) / 1000).toFixed(1),
  );

  useEffect(() => {
    if (!isLoading) {
      setElapsed(((Date.now() - startTime) / 1000).toFixed(1));
      return;
    }
    const interval = setInterval(() => {
      setElapsed(((Date.now() - startTime) / 1000).toFixed(1));
    }, 500);
    return () => clearInterval(interval);
  }, [startTime, isLoading]);

  return <span>{elapsed}s</span>;
}

export function TurnUsageDisplay({
  isLoading,
  estimate,
  variant = "inline",
}: {
  isLoading: boolean;
  estimate?: TurnUsageEstimate;
  variant?: "stacked" | "inline";
}) {
  const turnUsage = useTurnUsage();

  if (!turnUsage && !estimate) return null;

  const useEstimate = Boolean(isLoading && estimate);
  const inputTokens = useEstimate
    ? estimate!.inputTokens
    : (turnUsage?.input_tokens ?? 0);
  const outputTokens = useEstimate
    ? estimate!.outputTokens
    : (turnUsage?.output_tokens ?? 0);
  const startTime = turnUsage?.startTime ?? Date.now();

  if (variant === "inline") {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm font-normal tabular-nums">
        <span>(</span>
        <span className="flex items-center gap-1">
          <ArrowUpIcon className="size-3" />
          {formatTokens(inputTokens)}
        </span>
        <span className="text-muted-foreground/40">·</span>
        <span className="flex items-center gap-1">
          <ArrowDownIcon className="size-3" />
          {formatTokens(outputTokens)}
        </span>
        <span className="text-muted-foreground/40">·</span>
        <ElapsedTime startTime={startTime} isLoading={isLoading} />
        <span>)</span>
      </div>
    );
  }

  return (
    <div className="text-muted-foreground/50 flex items-center gap-3 py-1 text-xs tabular-nums">
      <span>
        {formatTokens(inputTokens)} in / {formatTokens(outputTokens)} out
      </span>
      <span className="text-muted-foreground/30">|</span>
      <ElapsedTime startTime={startTime} isLoading={isLoading} />
    </div>
  );
}
