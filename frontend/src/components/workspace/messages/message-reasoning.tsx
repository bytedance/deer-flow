"use client";

import { ChevronRightIcon } from "lucide-react";

import {
  Reasoning,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { useI18n } from "@/core/i18n/hooks";
import { SafeReasoningContent } from "@/core/streamdown/components";

import { RunDurationLabel } from "./run-duration";

export function MessageReasoning({
  children,
  isLoading,
  durationSeconds,
}: {
  children: string;
  isLoading: boolean;
  durationSeconds?: number;
}) {
  const { t } = useI18n();

  return (
    <Reasoning
      className="border-border/60 mb-3 border-b pb-3"
      isStreaming={isLoading}
    >
      <ReasoningTrigger className="group/reasoning w-fit cursor-pointer gap-1.5 rounded-sm focus-visible:outline-2 focus-visible:outline-offset-4">
        {!isLoading && durationSeconds !== undefined ? (
          <RunDurationLabel durationSeconds={durationSeconds} />
        ) : isLoading ? (
          <Shimmer duration={1}>{t.runDuration.reasoning}</Shimmer>
        ) : (
          <span>{t.runDuration.reasoning}</span>
        )}
        <ChevronRightIcon className="size-4 transition-transform group-data-[state=open]/reasoning:rotate-90" />
      </ReasoningTrigger>
      <SafeReasoningContent>{children}</SafeReasoningContent>
    </Reasoning>
  );
}
