"use client";

import { CheckIcon } from "lucide-react";

import { PromptInputActionMenuItem } from "@/components/ai-elements/prompt-input";
import { cn } from "@/lib/utils";

import type { InputMode } from "./input-box-types";

export function ModeMenuItem({
  mode,
  currentMode,
  icon: Icon,
  label,
  description,
  iconClassName,
  labelClassName,
  onSelect,
}: {
  mode: InputMode;
  currentMode: InputMode | undefined;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  description: string;
  iconClassName?: string;
  labelClassName?: string;
  onSelect: () => void;
}) {
  const isSelected = currentMode === mode;
  return (
    <PromptInputActionMenuItem
      className={cn(
        isSelected ? "text-accent-foreground" : "text-muted-foreground/65",
      )}
      onSelect={onSelect}
    >
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-1 font-bold">
          <Icon
            className={cn(
              "mr-2 size-4",
              isSelected && (iconClassName ?? "text-accent-foreground"),
            )}
          />
          <div className={cn(isSelected && labelClassName)}>{label}</div>
        </div>
        <div className="pl-7 text-xs">{description}</div>
      </div>
      {isSelected ? (
        <CheckIcon className="ml-auto size-4" />
      ) : (
        <div className="ml-auto size-4" />
      )}
    </PromptInputActionMenuItem>
  );
}

export function EffortMenuItem({
  effort,
  currentEffort,
  label,
  description,
  onSelect,
}: {
  effort: string;
  currentEffort: string | undefined;
  label: string;
  description: string;
  onSelect: () => void;
}) {
  const isSelected =
    effort === "medium"
      ? currentEffort === effort || !currentEffort
      : currentEffort === effort;
  return (
    <PromptInputActionMenuItem
      className={cn(
        isSelected ? "text-accent-foreground" : "text-muted-foreground/65",
      )}
      onSelect={onSelect}
    >
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-1 font-bold">{label}</div>
        <div className="pl-2 text-xs">{description}</div>
      </div>
      {isSelected ? (
        <CheckIcon className="ml-auto size-4" />
      ) : (
        <div className="ml-auto size-4" />
      )}
    </PromptInputActionMenuItem>
  );
}
