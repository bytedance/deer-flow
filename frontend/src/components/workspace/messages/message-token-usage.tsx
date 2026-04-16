import type { Message } from "@langchain/langgraph-sdk";
import { CoinsIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { formatTokenCount, getUsageMetadata } from "@/core/messages/usage";
import { cn } from "@/lib/utils";

export function MessageTokenUsage({
  className,
  enabled = false,
  isLoading = false,
  message,
}: {
  className?: string;
  enabled?: boolean;
  isLoading?: boolean;
  message: Message;
}) {
  const { t } = useI18n();

  if (!enabled || isLoading || message.type !== "ai") {
    return null;
  }

  const usage = getUsageMetadata(message);

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
      {usage ? (
        <>
          <span>
            {t.tokenUsage.input}: {formatTokenCount(usage.inputTokens)}
          </span>
          <span>
            {t.tokenUsage.output}: {formatTokenCount(usage.outputTokens)}
          </span>
          <span className="font-medium">
            {t.tokenUsage.total}: {formatTokenCount(usage.totalTokens)}
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

  return (
    <>
      {aiMessages.map((message, index) => (
        <MessageTokenUsage
          className={className}
          enabled={enabled}
          isLoading={isLoading}
          key={message.id ?? index}
          message={message}
        />
      ))}
    </>
  );
}
