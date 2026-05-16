"use client";

import { ChevronUp } from "lucide-react";
import { useState } from "react";

import { ChainOfThought } from "@/components/ai-elements/chain-of-thought";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

interface GenerationProcessPanelProps {
  stepCount: number;
  children: React.ReactNode;
  defaultExpanded?: boolean;
}

export function GenerationProcessPanel({
  stepCount,
  children,
  defaultExpanded = false,
}: GenerationProcessPanelProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <ChainOfThought
      className={cn("w-full gap-0 rounded-lg border p-0.5")}
      open={true}
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="flex-1">
          {t.toolCalls.generationProcess}
          {" · "}
          {t.toolCalls.generationProcessSteps(stepCount)}
        </span>
        <ChevronUp
          className={cn(
            "size-4 transition-transform duration-200",
            expanded ? "" : "rotate-180",
          )}
        />
      </button>
      {expanded && (
        <div className="border-t px-3 py-2">{children}</div>
      )}
    </ChainOfThought>
  );
}
