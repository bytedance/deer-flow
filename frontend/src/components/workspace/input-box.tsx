import type { ChatStatus } from "ai";
import {
  ArrowUpIcon,
  CheckIcon,
  ChevronDownIcon,
  GraduationCapIcon,
  LightbulbIcon,
  PaperclipIcon,
  PlusIcon,
  SparklesIcon,
  RocketIcon,
  ZapIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ComponentProps } from "react";
import { useSearchParams } from "react-router";

import {
  PromptInput,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuItem,
  PromptInputActionMenuTrigger,
  PromptInputAttachment,
  PromptInputAttachments,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputAttachments,
  usePromptInputController,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { ConfettiButton } from "@/components/ui/confetti-button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { resolveThinkingEffortForModel, useModels } from "@/core/models/hooks";
import { useLocalSettings } from "@/core/settings";
import type { AgentThreadContext } from "@/core/threads";
import { cn } from "@/lib/utils";

import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "../ai-elements/model-selector";
import { Suggestion, Suggestions } from "../ai-elements/suggestion";

import { ModeHoverGuide } from "./mode-hover-guide";
import { Tooltip } from "./tooltip";

type InputMode = "flash" | "thinking" | "pro" | "ultra";

function normalizeModeForModel(
  mode: InputMode | undefined,
  modelSupportsThinking: boolean,
): InputMode {
  if (!mode) {
    return modelSupportsThinking ? "thinking" : "flash";
  }
  if (modelSupportsThinking && mode === "flash") {
    return "thinking";
  }
  if (!modelSupportsThinking && mode === "thinking") {
    return "flash";
  }
  return mode;
}

function preferredThinkingEffortForMode(mode: InputMode): string {
  return mode === "pro" || mode === "ultra" ? "high" : "medium";
}

function resolveThinkingEffortForMode(
  model: ReturnType<typeof useModels>["models"][number] | undefined,
  mode: InputMode,
  currentEffort: string | undefined,
): string | undefined {
  const supportsThinking = model?.thinking_enabled ?? model?.supports_thinking ?? false;
  if (!supportsThinking) {
    return currentEffort;
  }
  return (
    resolveThinkingEffortForModel(
      model,
      preferredThinkingEffortForMode(mode),
    ) ?? currentEffort
  );
}

export function InputBox({
  className,
  disabled,
  autoFocus,
  status = "ready",
  context,
  extraHeader,
  isNewThread,
  initialValue,
  onContextChange,
  onSubmit,
  onStop,
  ...props
}: Omit<ComponentProps<typeof PromptInput>, "onSubmit"> & {
  assistantId?: string | null;
  status?: ChatStatus;
  disabled?: boolean;
  context: Omit<
    AgentThreadContext,
    "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
  > & {
    mode: InputMode | undefined;
  };
  extraHeader?: React.ReactNode;
  isNewThread?: boolean;
  initialValue?: string;
  onContextChange?: (
    context: Omit<
      AgentThreadContext,
      "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
    > & {
      mode: InputMode | undefined;
    },
  ) => void;
  onSubmit?: (message: PromptInputMessage) => void;
  onStop?: () => void;
}) {
  const { t } = useI18n();
  const [settings] = useLocalSettings();
  const [searchParams] = useSearchParams();
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const { models } = useModels();
  const selectedModel = useMemo(() => {
    if (!context.model_name && models.length > 0) {
      const model = models[0]!;
      const alwaysThinking =
        model.thinking_enabled ?? model.supports_thinking ?? false;
      const defaultMode = normalizeModeForModel(undefined, alwaysThinking);
      const defaultEffort = resolveThinkingEffortForMode(
        model,
        defaultMode,
        context.thinking_effort,
      );
      setTimeout(() => {
        onContextChange?.({
          ...context,
          model_name: model.id,
          mode: defaultMode,
          thinking_effort: defaultEffort,
        });
      }, 0);
      return model;
    }
    return models.find((m) => m.id === context.model_name);
  }, [context, models, onContextChange]);
  const modelThinkingEnabled = useMemo(
    () => selectedModel?.thinking_enabled ?? selectedModel?.supports_thinking ?? false,
    [selectedModel],
  );
  const activeMode = useMemo(
    () => normalizeModeForModel(context.mode, modelThinkingEnabled),
    [context.mode, modelThinkingEnabled],
  );
  useEffect(() => {
    if (!selectedModel) {
      return;
    }
    const nextMode = normalizeModeForModel(context.mode, modelThinkingEnabled);
    const nextThinkingEffort = resolveThinkingEffortForMode(
      selectedModel,
      nextMode,
      context.thinking_effort,
    );
    if (
      nextMode !== context.mode ||
      nextThinkingEffort !== context.thinking_effort
    ) {
      onContextChange?.({
        ...context,
        mode: nextMode,
        thinking_effort: nextThinkingEffort,
      });
    }
  }, [
    context,
    context.mode,
    context.thinking_effort,
    modelThinkingEnabled,
    onContextChange,
    selectedModel,
  ]);
  const selectedProviderConfig = useMemo(() => {
    if (!selectedModel) {
      return undefined;
    }
    return settings.models.providers[selectedModel.provider];
  }, [selectedModel, settings.models.providers]);
  const isMissingProviderKey = useMemo(() => {
    if (!selectedModel) {
      return false;
    }
    return !selectedProviderConfig?.has_key;
  }, [selectedModel, selectedProviderConfig?.has_key]);
  const handleModelSelect = useCallback(
    (model_id: string) => {
      const model = models.find((item) => item.id === model_id);
      const alwaysThinking = model?.thinking_enabled ?? model?.supports_thinking ?? false;
      const normalizedMode = normalizeModeForModel(context.mode, alwaysThinking);
      const normalizedThinkingEffort = resolveThinkingEffortForMode(
        model,
        normalizedMode,
        context.thinking_effort,
      );
      onContextChange?.({
        ...context,
        model_name: model_id,
        mode: normalizedMode,
        thinking_effort: normalizedThinkingEffort,
      });
      setModelDialogOpen(false);
    },
    [context, models, onContextChange],
  );
  const handleModeSelect = useCallback(
    (mode: InputMode) => {
      if ((mode === "flash" && modelThinkingEnabled) || (mode === "thinking" && !modelThinkingEnabled)) {
        return;
      }
      const nextMode = normalizeModeForModel(mode, modelThinkingEnabled);
      const nextThinkingEffort = resolveThinkingEffortForMode(
        selectedModel,
        nextMode,
        context.thinking_effort,
      );
      onContextChange?.({
        ...context,
        mode: nextMode,
        thinking_effort: nextThinkingEffort,
      });
    },
    [context, modelThinkingEnabled, onContextChange, selectedModel],
  );
  const handleSubmit = useCallback(
    async (message: PromptInputMessage) => {
      if (status === "streaming") {
        onStop?.();
        return;
      }
      if (!message.text) {
        return;
      }
      if (isMissingProviderKey) {
        return;
      }
      onSubmit?.(message);
    },
    [isMissingProviderKey, onSubmit, onStop, status],
  );
  const modeLabel =
    activeMode === "flash"
      ? t.inputBox.flashMode
      : activeMode === "thinking"
        ? t.inputBox.reasoningMode
        : activeMode === "pro"
          ? t.inputBox.proMode
          : t.inputBox.ultraMode;
  const submitDisabled = disabled ? true : isMissingProviderKey;
  return (
    <PromptInput
      className={cn(
        "rounded-2xl border border-border bg-card shadow-sm transition-all duration-300 ease-out",
        "*:data-[slot='input-group']:rounded-2xl *:data-[slot='input-group']:border-0 *:data-[slot='input-group']:bg-transparent",
        className,
      )}
      disabled={disabled}
      globalDrop
      multiple
      onSubmit={handleSubmit}
      {...props}
    >
      {extraHeader && (
        <div className="absolute top-0 right-0 left-0 z-10">
          <div className="absolute right-0 bottom-0 left-0 flex items-center justify-center">
            {extraHeader}
          </div>
        </div>
      )}
      <PromptInputAttachments>
        {(attachment) => <PromptInputAttachment data={attachment} />}
      </PromptInputAttachments>
      <PromptInputBody className="absolute top-0 right-0 left-0 z-3">
        <PromptInputTextarea
          className={cn("size-full text-lg")}
          disabled={disabled}
          placeholder={t.inputBox.placeholder}
          autoFocus={autoFocus}
          defaultValue={initialValue}
        />
      </PromptInputBody>
      <PromptInputFooter className="flex">
        <PromptInputTools>
          {/* Folder selector
          <PromptInputButton className="gap-2 px-3 text-foreground/70 hover:text-foreground">
            <FolderIcon className="size-4" />
            <span className="text-sm font-medium">Work in a folder</span>
            <ChevronDownIcon className="size-3.5" />
          </PromptInputButton>
          */}
          <AddAttachmentsButton className="px-1! text-foreground/70 hover:text-foreground" />
          <PromptInputActionMenu>
            <ModeHoverGuide
              mode={
                activeMode
              }
            >
              <PromptInputActionMenuTrigger className="gap-1.5! px-2! text-foreground/70 hover:text-foreground">
                <div>
                  {activeMode === "flash" && <ZapIcon className="size-4" />}
                  {activeMode === "thinking" && (
                    <LightbulbIcon className="size-4" />
                  )}
                  {activeMode === "pro" && (
                    <GraduationCapIcon className="size-4" />
                  )}
                  {activeMode === "ultra" && (
                    <RocketIcon className="size-4 text-[#dabb5e]" />
                  )}
                </div>
                <div
                  className={cn(
                    "text-sm font-medium",
                    activeMode === "ultra" ? "golden-text" : "",
                  )}
                >
                  {modeLabel}
                </div>
              </PromptInputActionMenuTrigger>
            </ModeHoverGuide>
            <PromptInputActionMenuContent className="w-80">
              <DropdownMenuGroup>
                <DropdownMenuLabel className="text-muted-foreground text-xs">
                  {t.inputBox.mode}
                </DropdownMenuLabel>
                <PromptInputActionMenu>
                  {!modelThinkingEnabled && (
                    <PromptInputActionMenuItem
                      className={cn(
                        activeMode === "flash"
                          ? "text-accent-foreground"
                          : "text-muted-foreground/65",
                      )}
                      onSelect={() => handleModeSelect("flash")}
                    >
                      <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-1 font-bold">
                          <ZapIcon
                            className={cn(
                              "mr-2 size-4",
                              activeMode === "flash" &&
                                "text-accent-foreground",
                            )}
                          />
                          {t.inputBox.flashMode}
                        </div>
                        <div className="pl-7 text-xs">
                          {t.inputBox.flashModeDescription}
                        </div>
                      </div>
                      {activeMode === "flash" ? (
                        <CheckIcon className="ml-auto size-4" />
                      ) : (
                        <div className="ml-auto size-4" />
                      )}
                    </PromptInputActionMenuItem>
                  )}
                  {modelThinkingEnabled && (
                    <PromptInputActionMenuItem
                      className={cn(
                        activeMode === "thinking"
                          ? "text-accent-foreground"
                          : "text-muted-foreground/65",
                      )}
                      onSelect={() => handleModeSelect("thinking")}
                    >
                      <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-1 font-bold">
                          <LightbulbIcon
                            className={cn(
                              "mr-2 size-4",
                              activeMode === "thinking" &&
                                "text-accent-foreground",
                            )}
                          />
                          {t.inputBox.reasoningMode}
                        </div>
                        <div className="pl-7 text-xs">
                          {t.inputBox.reasoningModeDescription}
                        </div>
                      </div>
                      {activeMode === "thinking" ? (
                        <CheckIcon className="ml-auto size-4" />
                      ) : (
                        <div className="ml-auto size-4" />
                      )}
                    </PromptInputActionMenuItem>
                  )}
                  <PromptInputActionMenuItem
                    className={cn(
                      activeMode === "pro"
                        ? "text-accent-foreground"
                        : "text-muted-foreground/65",
                    )}
                    onSelect={() => handleModeSelect("pro")}
                  >
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-1 font-bold">
                        <GraduationCapIcon
                          className={cn(
                            "mr-2 size-4",
                            activeMode === "pro" && "text-accent-foreground",
                          )}
                        />
                        {t.inputBox.proMode}
                      </div>
                      <div className="pl-7 text-xs">
                        {t.inputBox.proModeDescription}
                      </div>
                    </div>
                    {activeMode === "pro" ? (
                      <CheckIcon className="ml-auto size-4" />
                    ) : (
                      <div className="ml-auto size-4" />
                    )}
                  </PromptInputActionMenuItem>
                  <PromptInputActionMenuItem
                    className={cn(
                      activeMode === "ultra"
                        ? "text-accent-foreground"
                        : "text-muted-foreground/65",
                    )}
                    onSelect={() => handleModeSelect("ultra")}
                  >
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-1 font-bold">
                        <RocketIcon
                          className={cn(
                            "mr-2 size-4",
                            activeMode === "ultra" && "text-[#dabb5e]",
                          )}
                        />
                        <div
                          className={cn(
                            activeMode === "ultra" && "golden-text",
                          )}
                        >
                          {t.inputBox.ultraMode}
                        </div>
                      </div>
                      <div className="pl-7 text-xs">
                        {t.inputBox.ultraModeDescription}
                      </div>
                    </div>
                    {activeMode === "ultra" ? (
                      <CheckIcon className="ml-auto size-4" />
                    ) : (
                      <div className="ml-auto size-4" />
                    )}
                  </PromptInputActionMenuItem>
                </PromptInputActionMenu>
              </DropdownMenuGroup>
            </PromptInputActionMenuContent>
          </PromptInputActionMenu>
        </PromptInputTools>
        <PromptInputTools className="gap-2">
          <div className="flex flex-col gap-1">
            <ModelSelector
              open={modelDialogOpen}
              onOpenChange={setModelDialogOpen}
            >
              <ModelSelectorTrigger asChild>
                <PromptInputButton className="gap-2 rounded-lg border border-border bg-muted/50 px-4 py-2 hover:bg-muted">
                  <ModelSelectorName className="text-sm font-medium">
                    {selectedModel?.display_name ?? t.inputBox.selectModel ?? "Select model"}
                  </ModelSelectorName>
                  <ChevronDownIcon className="size-4 text-muted-foreground" />
                </PromptInputButton>
              </ModelSelectorTrigger>
              <ModelSelectorContent className="w-80">
                <ModelSelectorInput placeholder={t.inputBox.searchModels} />
                {isMissingProviderKey && (
                  <div className="px-4 pt-3 text-xs text-rose-500">
                    {t.inputBox.missingApiKey}
                  </div>
                )}
                <ModelSelectorList>
                  {models.map((m) => {
                    const modelDescription = m.description?.trim();
                    const fallbackDescription =
                      (m.thinking_enabled ?? m.supports_thinking)
                        ? "Best for everyday tasks"
                        : "Fastest for quick answers";
                    return (
                      <ModelSelectorItem
                        key={m.id}
                        value={m.id}
                        onSelect={() => handleModelSelect(m.id)}
                        className="flex-col items-start gap-1 py-3"
                      >
                        <div className="flex w-full items-center justify-between">
                          <ModelSelectorName className="text-base font-medium">{m.display_name}</ModelSelectorName>
                          {m.id === context.model_name && (
                            <CheckIcon className="size-4 text-primary" />
                          )}
                        </div>
                        <span className="text-sm text-muted-foreground">
                          {modelDescription && modelDescription.length > 0
                            ? modelDescription
                            : fallbackDescription}
                        </span>
                      </ModelSelectorItem>
                    );
                  })}
                </ModelSelectorList>
              </ModelSelectorContent>
            </ModelSelector>
            {isMissingProviderKey && (
              <div className="text-xs text-rose-500">
                {t.inputBox.missingApiKey}
              </div>
            )}
          </div>
          <SubmitButton
            disabled={submitDisabled}
            status={status}
          />
        </PromptInputTools>
      </PromptInputFooter>
      {/* Temporarily hidden suggestion chips below the input box */}
      {false && isNewThread && searchParams.get("mode") !== "skill" && (
        <div className="absolute right-0 -bottom-20 left-0 z-0 flex items-center justify-center">
          <SuggestionList />
        </div>
      )}
      {/* {!isNewThread && (
        <div className="bg-background absolute right-0 -bottom-[17px] left-0 z-0 h-4"></div>
      )} */}
    </PromptInput>
  );
}

function SuggestionList() {
  const { t } = useI18n();
  const { textInput } = usePromptInputController();
  const handleSuggestionClick = useCallback(
    (prompt: string | undefined) => {
      if (!prompt) return;
      textInput.setInput(prompt);
      setTimeout(() => {
        const textarea = document.querySelector<HTMLTextAreaElement>(
          "textarea[name='message']",
        );
        if (textarea) {
          const selStart = prompt.indexOf("[");
          const selEnd = prompt.indexOf("]");
          if (selStart !== -1 && selEnd !== -1) {
            textarea.setSelectionRange(selStart, selEnd + 1);
            textarea.focus();
          }
        }
      }, 500);
    },
    [textInput],
  );
  return (
    <Suggestions className="min-h-16 w-fit items-start">
      <ConfettiButton
        className="text-muted-foreground cursor-pointer rounded-full px-4 text-xs font-normal"
        variant="outline"
        size="sm"
        onClick={() => handleSuggestionClick(t.inputBox.surpriseMePrompt)}
      >
        <SparklesIcon className="size-4" /> {t.inputBox.surpriseMe}
      </ConfettiButton>
      {t.inputBox.suggestions.map((suggestion) => (
        <Suggestion
          key={suggestion.suggestion}
          icon={suggestion.icon}
          suggestion={suggestion.suggestion}
          onClick={() => handleSuggestionClick(suggestion.prompt)}
        />
      ))}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Suggestion icon={PlusIcon} suggestion={t.common.create} />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuGroup>
            {t.inputBox.suggestionsCreate.map((suggestion, index) =>
              "type" in suggestion && suggestion.type === "separator" ? (
                <DropdownMenuSeparator key={index} />
              ) : (
                !("type" in suggestion) && (
                  <DropdownMenuItem
                    key={suggestion.suggestion}
                    onClick={() => handleSuggestionClick(suggestion.prompt)}
                  >
                    {suggestion.icon && <suggestion.icon className="size-4" />}
                    {suggestion.suggestion}
                  </DropdownMenuItem>
                )
              ),
            )}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </Suggestions>
  );
}

function AddAttachmentsButton({ className }: { className?: string }) {
  const { t } = useI18n();
  const attachments = usePromptInputAttachments();
  return (
    <Tooltip content={t.inputBox.addAttachments}>
      <PromptInputButton
        className={cn("px-2!", className)}
        onClick={() => attachments.openFileDialog()}
      >
        <PaperclipIcon className="size-4" />
      </PromptInputButton>
    </Tooltip>
  );
}

function SubmitButton({
  disabled,
  status,
}: {
  disabled?: boolean;
  status?: ChatStatus;
}) {
  const isStreaming = status === "streaming";
  const isSubmitted = status === "submitted";

  return (
    <button
      type="submit"
      disabled={disabled}
      className={cn(
        "inline-flex items-center justify-center rounded-lg p-2 text-sm font-medium transition-all",
        "bg-primary text-primary-foreground",
        "hover:bg-primary/90 active:scale-[0.98]",
        "disabled:pointer-events-none disabled:opacity-50",
        "focus:outline-none focus:ring-2 focus:ring-primary/20",
      )}
    >
      {isStreaming ? (
        <>Stop</>
      ) : isSubmitted ? (
        <>Uploading...</>
      ) : (
        <ArrowUpIcon className="size-4" />
      )}
    </button>
  );
}
