import {
  CheckIcon,
  GraduationCapIcon,
  LightbulbIcon,
  MessageSquareTextIcon,
  RotateCcwIcon,
  RocketIcon,
  ZapIcon,
} from "lucide-react";

import {
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuItem,
  PromptInputActionMenuTrigger,
  PromptInputButton,
} from "@/components/ai-elements/prompt-input";
import {
  DropdownMenuGroup,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import {
  getResolvedMode,
  INPUT_MODES,
  isThinkingRequired,
  supportsThinking,
  type InputMode,
} from "@/core/models/reasoning";
import type { Model } from "@/core/models/types";
import { cn } from "@/lib/utils";

import { Tooltip } from "./tooltip";

const options = {
  chat: {
    icon: MessageSquareTextIcon,
    label: "chatMode",
    description: "chatModeDescription",
  },
  flash: {
    icon: ZapIcon,
    label: "flashMode",
    description: "flashModeDescription",
  },
  thinking: {
    icon: LightbulbIcon,
    label: "reasoningMode",
    description: "reasoningModeDescription",
  },
  pro: {
    icon: GraduationCapIcon,
    label: "proMode",
    description: "proModeDescription",
  },
  ultra: {
    icon: RocketIcon,
    label: "ultraMode",
    description: "ultraModeDescription",
  },
} as const;

export function InputModeMenu({
  mode,
  model,
  disabled = false,
  runActive,
  className,
  onSelect,
  onRetry,
}: {
  mode?: InputMode;
  model?: Model;
  disabled?: boolean;
  runActive?: boolean;
  className?: string;
  onSelect: (mode: InputMode) => void;
  onRetry?: () => void;
}) {
  const { t } = useI18n();
  if (onRetry) {
    return (
      <PromptInputButton type="button" onClick={onRetry}>
        <RotateCcwIcon className="size-3" />
        {t.inputBox.retryMode}
      </PromptInputButton>
    );
  }
  const current = getResolvedMode(mode, model);
  const selected = options[current];
  const SelectedIcon = selected.icon;
  return (
    <PromptInputActionMenu>
      <Tooltip
        content={`${t.inputBox[selected.label]}: ${t.inputBox[selected.description]}`}
      >
        <PromptInputActionMenuTrigger
          className={cn("min-w-0 gap-1! px-2!", className)}
          disabled={disabled || (runActive && current === "chat")}
        >
          <SelectedIcon
            className={cn("size-3", current === "ultra" && "text-[#dabb5e]")}
          />
          <span
            className={cn(
              "truncate text-xs font-normal",
              current === "ultra" && "golden-text",
            )}
          >
            {t.inputBox[selected.label]}
          </span>
        </PromptInputActionMenuTrigger>
      </Tooltip>
      <PromptInputActionMenuContent className="w-80">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-muted-foreground text-xs">
            {t.inputBox.mode}
          </DropdownMenuLabel>
          {INPUT_MODES.map((value) => {
            if (
              (value === "flash" && isThinkingRequired(model)) ||
              (value === "thinking" && !supportsThinking(model))
            )
              return null;
            const { icon: Icon, label, description } = options[value];
            const active = current === value;
            return (
              <PromptInputActionMenuItem
                key={value}
                disabled={runActive && value === "chat"}
                className={
                  active ? "text-accent-foreground" : "text-muted-foreground/65"
                }
                onSelect={() => onSelect(value)}
              >
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-1 font-bold">
                    <Icon
                      className={cn(
                        "mr-2 size-4",
                        active && value === "ultra" && "text-[#dabb5e]",
                      )}
                    />
                    <span
                      className={cn(
                        active && value === "ultra" && "golden-text",
                      )}
                    >
                      {t.inputBox[label]}
                    </span>
                  </div>
                  <div className="pl-7 text-xs">{t.inputBox[description]}</div>
                </div>
                {active && <CheckIcon className="ml-auto size-4" />}
              </PromptInputActionMenuItem>
            );
          })}
        </DropdownMenuGroup>
      </PromptInputActionMenuContent>
    </PromptInputActionMenu>
  );
}
