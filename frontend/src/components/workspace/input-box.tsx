"use client";

import type { ChatStatus } from "ai";
import {
  CheckIcon,
  GraduationCapIcon,
  LightbulbIcon,
  PaperclipIcon,
  PlusIcon,
  SparklesIcon,
  RocketIcon,
  ZapIcon,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ComponentProps,
} from "react";

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
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputAttachments,
  usePromptInputController,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { ConfettiButton } from "@/components/ui/confetti-button";
import {
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

import { ModeHoverGuide } from "./mode-hover-guide";
import { Tooltip } from "./tooltip";

type AgentMode = "flash" | "thinking" | "pro" | "ultra";

const isAgentMode = (mode: unknown): mode is AgentMode =>
  mode === "flash" ||
  mode === "thinking" ||
  mode === "pro" ||
  mode === "ultra";

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
    mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
  };
  extraHeader?: React.ReactNode;
  isNewThread?: boolean;
  initialValue?: string;
  onContextChange?: (
    context: Omit<
      AgentThreadContext,
      "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
    > & {
      mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
    },
  ) => void;
  onSubmit?: (message: PromptInputMessage) => void;
  onStop?: () => void;
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const { models } = useModels();
  const selectedModel = useMemo(() => {
    if (!context.model_name && models.length > 0) {
      const model = models[0]!;
      setTimeout(() => {
        onContextChange?.({
          ...context,
          model_name: model.name,
          mode: model.supports_thinking ? "pro" : "flash",
        });
      }, 0);
      return model;
    }
    return models.find((m) => m.name === context.model_name);
  }, [context, models, onContextChange]);
  const supportThinking = useMemo(
    () => selectedModel?.supports_thinking ?? false,
    [selectedModel],
  );
  const currentMode = useMemo<AgentMode>(() => {
    if (isAgentMode(context.mode)) {
      return context.mode;
    }
    return supportThinking ? "pro" : "flash";
  }, [context.mode, supportThinking]);
  useEffect(() => {
    if (isAgentMode(context.mode)) {
      return;
    }
    onContextChange?.({
      ...context,
      mode: currentMode,
    });
  }, [context, currentMode, onContextChange]);
  const handleModelSelect = useCallback(
    (model_name: string) => {
      onContextChange?.({
        ...context,
        model_name,
      });
      setModelDialogOpen(false);
    },
    [onContextChange, context],
  );
  const handleModeSelect = useCallback(
    (mode: "flash" | "thinking" | "pro" | "ultra") => {
      onContextChange?.({
        ...context,
        mode,
      });
    },
    [onContextChange, context],
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
      onSubmit?.(message);
    },
    [onSubmit, onStop, status],
  );
  return (
    <PromptInput
      className={cn(
        "bg-background/85 rounded-2xl backdrop-blur-sm transition-all duration-300 ease-out *:data-[slot='input-group']:rounded-2xl",
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
          className={cn("size-full")}
          disabled={disabled}
          placeholder={t.inputBox.placeholder}
          autoFocus={autoFocus}
          defaultValue={initialValue}
        />
      </PromptInputBody>
      <PromptInputFooter className="flex">
        <PromptInputTools>
          {/* TODO: Add more connectors here
          <PromptInputActionMenu>
            <PromptInputActionMenuTrigger className="px-2!" />
            <PromptInputActionMenuContent>
              <PromptInputActionAddAttachments
                label={t.inputBox.addAttachments}
              />
            </PromptInputActionMenuContent>
          </PromptInputActionMenu> */}
          <AddAttachmentsButton className="px-2!" />
          <PromptInputActionMenu>
            <ModeHoverGuide mode={currentMode}>
              <PromptInputActionMenuTrigger className="gap-1! px-2!">
                <div>
                  {currentMode === "flash" && <ZapIcon className="size-3" />}
                  {currentMode === "thinking" && (
                    <LightbulbIcon className="size-3" />
                  )}
                  {currentMode === "pro" && (
                    <GraduationCapIcon className="size-3" />
                  )}
                  {currentMode === "ultra" && (
                    <RocketIcon className="size-3 text-[#dabb5e]" />
                  )}
                </div>
                <div
                  className={cn(
                    "text-xs font-normal",
                    currentMode === "ultra" ? "golden-text" : "",
                  )}
                >
                  {(currentMode === "flash" && t.inputBox.flashMode) ||
                    (currentMode === "thinking" &&
                      t.inputBox.reasoningMode) ||
                    (currentMode === "pro" && t.inputBox.proMode) ||
                    (currentMode === "ultra" && t.inputBox.ultraMode)}
                </div>
              </PromptInputActionMenuTrigger>
            </ModeHoverGuide>
            <PromptInputActionMenuContent className="w-80">
              <DropdownMenuGroup>
                <DropdownMenuLabel className="text-muted-foreground text-xs">
                  {t.inputBox.mode}
                </DropdownMenuLabel>
                <PromptInputActionMenu>
                  <PromptInputActionMenuItem
                    className={cn(
                      currentMode === "flash"
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
                            currentMode === "flash" &&
                              "text-accent-foreground",
                          )}
                        />
                        {t.inputBox.flashMode}
                      </div>
                      <div className="pl-7 text-xs">
                        {t.inputBox.flashModeDescription}
                      </div>
                    </div>
                    {currentMode === "flash" ? (
                      <CheckIcon className="ml-auto size-4" />
                    ) : (
                      <div className="ml-auto size-4" />
                    )}
                  </PromptInputActionMenuItem>
                  {supportThinking && (
                    <PromptInputActionMenuItem
                      className={cn(
                        currentMode === "thinking"
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
                              currentMode === "thinking" &&
                                "text-accent-foreground",
                            )}
                          />
                          {t.inputBox.reasoningMode}
                        </div>
                        <div className="pl-7 text-xs">
                          {t.inputBox.reasoningModeDescription}
                        </div>
                      </div>
                      {currentMode === "thinking" ? (
                        <CheckIcon className="ml-auto size-4" />
                      ) : (
                        <div className="ml-auto size-4" />
                      )}
                    </PromptInputActionMenuItem>
                  )}
                  <PromptInputActionMenuItem
                    className={cn(
                      currentMode === "pro"
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
                            currentMode === "pro" &&
                              "text-accent-foreground",
                          )}
                        />
                        {t.inputBox.proMode}
                      </div>
                      <div className="pl-7 text-xs">
                        {t.inputBox.proModeDescription}
                      </div>
                    </div>
                    {currentMode === "pro" ? (
                      <CheckIcon className="ml-auto size-4" />
                    ) : (
                      <div className="ml-auto size-4" />
                    )}
                  </PromptInputActionMenuItem>
                  <PromptInputActionMenuItem
                    className={cn(
                      currentMode === "ultra"
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
                            currentMode === "ultra" && "text-[#dabb5e]",
                          )}
                        />
                        <div
                          className={cn(currentMode === "ultra" && "golden-text")}
                        >
                          {t.inputBox.ultraMode}
                        </div>
                      </div>
                      <div className="pl-7 text-xs">
                        {t.inputBox.ultraModeDescription}
                      </div>
                    </div>
                    {currentMode === "ultra" ? (
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
        <PromptInputTools>
          <ModelSelector
            open={modelDialogOpen}
            onOpenChange={setModelDialogOpen}
          >
            <ModelSelectorTrigger asChild>
              <PromptInputButton>
                <ModelSelectorName className="text-xs font-normal">
                  {selectedModel?.display_name}
                </ModelSelectorName>
              </PromptInputButton>
            </ModelSelectorTrigger>
            <ModelSelectorContent>
              <ModelSelectorInput placeholder={t.inputBox.searchModels} />
              <ModelSelectorList>
                {models.map((m) => (
                  <ModelSelectorItem
                    key={m.name}
                    value={m.name}
                    onSelect={() => handleModelSelect(m.name)}
                  >
                    <ModelSelectorName>{m.display_name}</ModelSelectorName>
                    {m.name === context.model_name ? (
                      <CheckIcon className="ml-auto size-4" />
                    ) : (
                      <div className="ml-auto size-4" />
                    )}
                  </ModelSelectorItem>
                ))}
              </ModelSelectorList>
            </ModelSelectorContent>
          </ModelSelector>
          <PromptInputSubmit
            className="rounded-full"
            disabled={disabled}
            variant="outline"
            status={status}
          />
        </PromptInputTools>
      </PromptInputFooter>
      {isNewThread && searchParams.get("mode") !== "skill" && (
        <div className="absolute right-0 -bottom-20 left-0 z-0 flex items-center justify-center">
          <SuggestionList />
        </div>
      )}
      {!isNewThread && (
        <div className="bg-background absolute right-0 -bottom-[17px] left-0 z-0 h-4"></div>
      )}
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
        <PaperclipIcon className="size-3" />
      </PromptInputButton>
    </Tooltip>
  );
}
