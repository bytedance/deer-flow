import type { Message } from "@langchain/langgraph-sdk";
import { CoinsIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/core/i18n/hooks";
import { accumulateUsage, formatTokenCount } from "@/core/messages/usage";
import type { TokenDebugStep } from "@/core/messages/usage-model";
import { cn } from "@/lib/utils";

function TokenUsageSummary({
  className,
  inputTokens,
  outputTokens,
  totalTokens,
  unavailable = false,
}: {
  className?: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  unavailable?: boolean;
}) {
  const { t } = useI18n();

  return (
    <div
      className={cn(
        "text-muted-foreground border-border/60 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2 text-[11px]",
        className,
      )}
    >
      <span className="inline-flex items-center gap-1 font-medium">
        <CoinsIcon className="size-3" />
        {t.tokenUsage.label}
      </span>
      {!unavailable ? (
        <>
          <span>
            {t.tokenUsage.input}: {formatTokenCount(inputTokens ?? 0)}
          </span>
          <span>
            {t.tokenUsage.output}: {formatTokenCount(outputTokens ?? 0)}
          </span>
          <span className="font-medium">
            {t.tokenUsage.total}: {formatTokenCount(totalTokens ?? 0)}
          </span>
        </>
      ) : (
        <span>{t.tokenUsage.unavailableShort}</span>
      )}
    </div>
  );
}

export function MessageTokenUsageList({
  className,
  enabled = false,
  isLoading = false,
  messages,
}: {
  className?: string;
  enabled?: boolean;
  isLoading?: boolean;
  messages: Message[];
}) {
  if (!enabled || isLoading) {
    return null;
  }

  const aiMessages = messages.filter((message) => message.type === "ai");

  if (aiMessages.length === 0) {
    return null;
  }

  const usage = accumulateUsage(aiMessages);

  return (
    <TokenUsageSummary
      className={className}
      inputTokens={usage?.inputTokens}
      outputTokens={usage?.outputTokens}
      totalTokens={usage?.totalTokens}
      unavailable={!usage}
    />
  );
}

export function MessageTokenUsageDebugList({
  className,
  enabled = false,
  isLoading = false,
  steps,
}: {
  className?: string;
  enabled?: boolean;
  isLoading?: boolean;
  steps: TokenDebugStep[];
}) {
  const { t } = useI18n();

  if (!enabled || isLoading) {
    return null;
  }

  if (steps.length === 0) {
    return null;
  }

  return (
    <div className={cn("border-border/60 mt-1 border-t pt-2", className)}>
      <div className="space-y-2">
        {steps.map((step) => (
          <div
            key={step.id}
            className="bg-muted/30 border-border/50 flex items-start justify-between gap-3 rounded-md border px-3 py-2"
          >
            <div className="min-w-0 flex-1 space-y-1">
              <div className="text-foreground flex items-center gap-2 text-xs font-medium">
                <CoinsIcon className="text-muted-foreground size-3" />
                <span className="truncate">{step.label}</span>
              </div>
              {step.secondaryLabels.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {step.secondaryLabels.map((label, index) => (
                    <Badge
                      key={`${step.id}-${index}-${label}`}
                      className="px-1.5 py-0 text-[10px] font-normal"
                      variant="secondary"
                    >
                      {label}
                    </Badge>
                  ))}
                </div>
              )}
              {step.sharedAttribution && (
                <div className="text-muted-foreground text-[11px]">
                  {t.tokenUsage.sharedAttribution}
                </div>
              )}
              <div className="text-muted-foreground text-[11px]">
                {step.usage ? (
                  <>
                    {t.tokenUsage.input}:{" "}
                    {formatTokenCount(step.usage.inputTokens)}
                    {" · "}
                    {t.tokenUsage.output}:{" "}
                    {formatTokenCount(step.usage.outputTokens)}
                  </>
                ) : (
                  t.tokenUsage.unavailableShort
                )}
              </div>
            </div>
            <Badge className="shrink-0 font-mono" variant="outline">
              {step.usage
                ? `${formatTokenCount(step.usage.totalTokens)} ${t.tokenUsage.label}`
                : t.tokenUsage.unavailableShort}
            </Badge>
          </div>
        ))}
      </div>
    </div>
  );
}
