"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { ChevronDownIcon, CoinsIcon } from "lucide-react";
import { useMemo } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { accumulateUsage, formatTokenCount } from "@/core/messages/usage";
import {
  getTokenUsageViewPreset,
  tokenUsagePreferencesFromPreset,
  type TokenUsagePreferences,
  type TokenUsageViewPreset,
} from "@/core/messages/usage-model";
import { cn } from "@/lib/utils";

interface TokenUsageIndicatorProps {
  messages: Message[];
  enabled?: boolean;
  preferences: TokenUsagePreferences;
  onPreferencesChange: (preferences: TokenUsagePreferences) => void;
  className?: string;
}

export function TokenUsageIndicator({
  messages,
  enabled = false,
  preferences,
  onPreferencesChange,
  className,
}: TokenUsageIndicatorProps) {
  const { t } = useI18n();

  const usage = useMemo(() => accumulateUsage(messages), [messages]);
  const preset = getTokenUsageViewPreset(preferences);

  if (!enabled) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          className={cn(
            "text-muted-foreground bg-background/70 hover:bg-background/90 flex h-auto items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-normal",
            className,
          )}
        >
          <CoinsIcon size={14} />
          <span>{t.tokenUsage.label}</span>
          <span className="font-mono">
            {preferences.headerTotal
              ? usage
                ? formatTokenCount(usage.totalTokens)
                : "-"
              : t.tokenUsage.presets[presetKeyToTranslationKey(preset)]}
          </span>
          <ChevronDownIcon className="size-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="bottom" align="end" className="w-80">
        <DropdownMenuLabel>{t.tokenUsage.title}</DropdownMenuLabel>
        <div className="px-2 py-1 text-xs">
          {usage ? (
            <div className="space-y-1">
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
          ) : (
            <div className="text-muted-foreground">
              {t.tokenUsage.unavailable}
            </div>
          )}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t.tokenUsage.view}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preset}
          onValueChange={(value) =>
            onPreferencesChange(
              tokenUsagePreferencesFromPreset(value as TokenUsageViewPreset),
            )
          }
        >
          {(
            ["off", "summary", "per_turn", "debug"] as TokenUsageViewPreset[]
          ).map((value) => {
            const translationKey = presetKeyToTranslationKey(value);
            return (
              <DropdownMenuRadioItem key={value} value={value}>
                <div className="grid gap-0.5">
                  <span>{t.tokenUsage.presets[translationKey]}</span>
                  <span className="text-muted-foreground text-xs">
                    {t.tokenUsage.presetDescriptions[translationKey]}
                  </span>
                </div>
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <div className="text-muted-foreground px-2 py-2 text-xs leading-relaxed">
          {t.tokenUsage.note}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function presetKeyToTranslationKey(preset: TokenUsageViewPreset) {
  switch (preset) {
    case "per_turn":
      return "perTurn" as const;
    default:
      return preset;
  }
}
