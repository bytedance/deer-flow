"use client";

import type { Message } from "@langchain/langgraph-sdk";
import type { ChatStatus } from "ai";
import {
  CheckIcon,
  GraduationCapIcon,
  LightbulbIcon,
  PaperclipIcon,
  PlusIcon,
  SparklesIcon,
  RocketIcon,
  TargetIcon,
  XIcon,
  ZapIcon,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type KeyboardEvent,
  type RefObject,
} from "react";
import { toast } from "sonner";

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
  PromptInputHeader,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputAttachments,
  usePromptInputController,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { ConfettiButton } from "@/components/ui/confetti-button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { isHiddenFromUIMessage } from "@/core/messages/utils";
import { useModels } from "@/core/models/hooks";
import {
  buildReferenceMessageMetadata,
  type SidecarContext,
} from "@/core/sidecar";
import { useSkills } from "@/core/skills/hooks";
import { useSuggestionsConfig } from "@/core/suggestions/hooks";
import type { AgentThreadContext, GoalState } from "@/core/threads";
import { textOfMessage } from "@/core/threads/utils";
import {
  formatUploadSize,
  useUploadLimits,
  validateUploadLimits,
  type UploadLimits,
  type UploadLimitViolation,
} from "@/core/uploads";
import { isIMEComposing } from "@/lib/ime";
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

import {
  abortGoalRequest,
  beginGoalRequest,
  createGoalRequestState,
  findSuggestionTemplatePlaceholder,
  finishGoalRequest,
  getInputSubmitAction,
  getLeadingSlashSkillQuery,
  getMatchingSkillSuggestions,
  type GoalCommand,
  isAbortError,
  isCurrentGoalRequest,
  readGoalResponseError,
  type SlashSuggestion,
} from "./input-box-helpers";
import { useThread } from "./messages/context";
import { ModeHoverGuide } from "./mode-hover-guide";
import { ReferenceAttachmentSummary, useMaybeSidecar } from "./sidecar";
import { Tooltip } from "./tooltip";

type InputMode = "flash" | "thinking" | "pro" | "ultra";

function getResolvedMode(
  mode: InputMode | undefined,
  supportsThinking: boolean,
): InputMode {
  if (!supportsThinking && mode !== "flash") {
    return "flash";
  }
  if (mode) {
    return mode;
  }
  return supportsThinking ? "pro" : "flash";
}

function escapeXmlAttribute(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export type InputBoxSubmitOptions = {
  additionalKwargs?: Record<string, unknown>;
  additionalInputMessages?: Message[];
  onSent?: () => void;
};

function buildHiddenConversationQuoteMessage({
  contexts,
}: {
  contexts: SidecarContext[];
}): Message {
  return {
    type: "human",
    content: [
      {
        type: "text",
        text: [
          contexts.length === 1
            ? "The user added the following quoted context to this conversation."
            : `The user added the following ${contexts.length} quoted contexts to this conversation.`,
          "Use the referenced_message blocks as reference material for the user's next message.",
          "",
          ...contexts.flatMap((context, index) =>
            [
              `<referenced_message index="${index + 1}" label="${escapeXmlAttribute(
                context.label,
              )}">`,
              `Role: ${context.role === "user" ? "User" : "Assistant"}`,
              context.messageId ? `Message ID: ${context.messageId}` : null,
              "",
              context.content,
              "</referenced_message>",
              "",
            ].filter((line): line is string => line !== null),
          ),
        ]
          .filter((line): line is string => line !== null)
          .join("\n"),
      },
    ],
    additional_kwargs: {
      hide_from_ui: true,
      conversation_quote_context: true,
      // Keep ids/roles/count 1:1 parallel with `contexts` so consumers can zip
      // them safely; do not dedupe ids here.
      referenced_message_ids: contexts.map(
        (context) => context.messageId ?? "",
      ),
      referenced_message_roles: contexts.map((context) => context.role),
      quote_context_count: contexts.length,
    },
  } as Message;
}

export function InputBox({
  className,
  disabled,
  autoFocus,
  status = "ready",
  context,
  extraHeader,
  isWelcomeMode,
  threadId,
  initialValue,
  onContextChange,
  onFollowupsVisibilityChange,
  onGoalChange,
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
    reasoning_effort?: "minimal" | "low" | "medium" | "high";
  };
  extraHeader?: React.ReactNode;
  /**
   * Whether to render the input in welcome layout (vertically centered,
   * with hero + quick action suggestions).  This is purely a visual flag,
   * decoupled from "the backend has created the thread" — see issue #2746.
   */
  isWelcomeMode?: boolean;
  threadId: string;
  initialValue?: string;
  onContextChange?: (
    context: Omit<
      AgentThreadContext,
      "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
    > & {
      mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
      reasoning_effort?: "minimal" | "low" | "medium" | "high";
    },
  ) => void;
  onFollowupsVisibilityChange?: (visible: boolean) => void;
  onGoalChange?: (goal: GoalState | null) => void;
  onSubmit?: (
    message: PromptInputMessage,
    options?: InputBoxSubmitOptions,
  ) => void | Promise<void>;
  onStop?: () => void;
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const { models } = useModels();
  const { thread, isMock } = useThread();
  const { attachments, textInput } = usePromptInputController();
  const sidecar = useMaybeSidecar();
  const attachmentParts = attachments.files;
  const removeAttachment = attachments.remove;
  const { skills } = useSkills();
  const { data: uploadLimits } = useUploadLimits(threadId);
  const promptRootRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const goalRequestStateRef = useRef(createGoalRequestState());
  const promptHistoryIndexRef = useRef<number | null>(null);
  const promptHistoryDraftRef = useRef("");

  const [followups, setFollowups] = useState<string[]>([]);
  const { data: suggestionsConfig } = useSuggestionsConfig();
  const suggestionsConfigLoaded = suggestionsConfig !== undefined;
  const suggestionsEnabled = suggestionsConfig?.enabled;
  const [followupsHidden, setFollowupsHidden] = useState(false);
  const [followupsLoading, setFollowupsLoading] = useState(false);
  const [textareaFocused, setTextareaFocused] = useState(false);
  const [skillSuggestionIndex, setSkillSuggestionIndex] = useState(0);
  const [dismissedSkillSuggestionValue, setDismissedSkillSuggestionValue] =
    useState<string | null>(null);
  const lastGeneratedForAiIdRef = useRef<string | null>(null);
  const wasStreamingRef = useRef(false);
  const messagesRef = useRef(thread.messages);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingSuggestion, setPendingSuggestion] = useState<string | null>(
    null,
  );
  const builtinSlashCommands = useMemo<SlashSuggestion[]>(
    () => [
      {
        name: "goal",
        description: t.inputBox.goalCommandDescription,
        kind: "builtin",
      },
    ],
    [t.inputBox.goalCommandDescription],
  );

  const reportUploadLimitViolations = useCallback(
    (violations: UploadLimitViolation[]) => {
      for (const violation of violations) {
        if (violation.code === "max_file_size") {
          toast.error(
            t.uploads.filesTooLarge(
              violation.files.map((file) => file.name).join(", "),
              formatUploadSize(violation.limit),
            ),
          );
        } else if (violation.code === "max_files") {
          toast.error(
            t.uploads.tooManyFiles(violation.files.length, violation.limit),
          );
        } else {
          toast.error(
            t.uploads.totalSizeTooLarge(
              violation.files.length,
              formatUploadSize(violation.limit),
            ),
          );
        }
      }
    },
    [t.uploads],
  );

  useEffect(() => {
    if (!uploadLimits) {
      return;
    }

    const attachmentEntries = attachmentParts.flatMap((attachment) =>
      attachment.file instanceof File
        ? [{ id: attachment.id, file: attachment.file }]
        : [],
    );
    const validation = validateUploadLimits(
      [],
      attachmentEntries.map(({ file }) => file),
      uploadLimits,
    );
    if (validation.rejected.length === 0) {
      return;
    }

    const rejected = new Set(validation.rejected);
    for (const entry of attachmentEntries) {
      if (rejected.has(entry.file)) {
        removeAttachment(entry.id);
      }
    }
    reportUploadLimitViolations(validation.violations);
  }, [
    attachmentParts,
    removeAttachment,
    reportUploadLimitViolations,
    uploadLimits,
  ]);

  useEffect(() => {
    if (models.length === 0) {
      return;
    }
    const currentModel = models.find((m) => m.name === context.model_name);
    const fallbackModel = currentModel ?? models[0]!;
    const supportsThinking = fallbackModel.supports_thinking ?? false;
    const nextModelName = fallbackModel.name;
    const nextMode = getResolvedMode(context.mode, supportsThinking);

    if (context.model_name === nextModelName && context.mode === nextMode) {
      return;
    }

    onContextChange?.({
      ...context,
      model_name: nextModelName,
      mode: nextMode,
    });
  }, [context, models, onContextChange]);

  const selectedModel = useMemo(() => {
    if (models.length === 0) {
      return undefined;
    }
    return models.find((m) => m.name === context.model_name) ?? models[0];
  }, [context.model_name, models]);

  const resolvedModelName = selectedModel?.name;

  const supportThinking = useMemo(
    () => selectedModel?.supports_thinking ?? false,
    [selectedModel],
  );

  const supportReasoningEffort = useMemo(
    () => selectedModel?.supports_reasoning_effort ?? false,
    [selectedModel],
  );

  const promptHistory = useMemo(() => {
    const history: string[] = [];
    for (const message of thread.messages) {
      if (message.type !== "human") {
        continue;
      }
      const additionalKwargs = message.additional_kwargs;
      if (
        additionalKwargs &&
        typeof additionalKwargs === "object" &&
        Reflect.get(additionalKwargs, "hide_from_ui") === true
      ) {
        continue;
      }
      const text = textOfMessage(message)?.trim();
      if (!text) {
        continue;
      }
      if (history.at(-1) !== text) {
        history.push(text);
      }
    }
    return history;
  }, [thread.messages]);

  useEffect(() => {
    promptHistoryIndexRef.current = null;
    promptHistoryDraftRef.current = "";
  }, [threadId]);

  useEffect(() => {
    const goalRequestState = goalRequestStateRef.current;
    return () => abortGoalRequest(goalRequestState);
  }, [threadId]);

  useEffect(() => {
    const currentIndex = promptHistoryIndexRef.current;
    if (currentIndex !== null && currentIndex >= promptHistory.length) {
      promptHistoryIndexRef.current = null;
      promptHistoryDraftRef.current = "";
    }
  }, [promptHistory.length]);

  const handleModelSelect = useCallback(
    (model_name: string) => {
      const model = models.find((m) => m.name === model_name);
      if (!model) {
        return;
      }
      onContextChange?.({
        ...context,
        model_name,
        mode: getResolvedMode(context.mode, model.supports_thinking ?? false),
        reasoning_effort: context.reasoning_effort,
      });
      setModelDialogOpen(false);
    },
    [onContextChange, context, models],
  );

  const handleModeSelect = useCallback(
    (mode: InputMode) => {
      onContextChange?.({
        ...context,
        mode: getResolvedMode(mode, supportThinking),
        reasoning_effort:
          mode === "ultra"
            ? "high"
            : mode === "pro"
              ? "medium"
              : mode === "thinking"
                ? "low"
                : "minimal",
      });
    },
    [onContextChange, context, supportThinking],
  );

  const handleReasoningEffortSelect = useCallback(
    (effort: "minimal" | "low" | "medium" | "high") => {
      onContextChange?.({
        ...context,
        reasoning_effort: effort,
      });
    },
    [onContextChange, context],
  );

  const handleGoalCommand = useCallback(
    async (command: GoalCommand): Promise<boolean> => {
      const request = beginGoalRequest(goalRequestStateRef.current, threadId);
      const signal = request.controller.signal;
      try {
        let goal: GoalState | null = null;
        if (command.kind === "status") {
          const response = await fetch(
            `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
              threadId,
            )}/goal`,
            { method: "GET", signal },
          );
          if (!response.ok) {
            throw new Error(await readGoalResponseError(response));
          }
          goal =
            ((await response.json()) as { goal?: GoalState | null }).goal ??
            null;
          if (
            !isCurrentGoalRequest(
              goalRequestStateRef.current,
              request,
              threadId,
            )
          ) {
            return false;
          }
          const objective = goal?.objective;
          toast.info(
            objective !== undefined
              ? // Function replacer so a goal containing `$&`/`$1` isn't
                // interpreted as a replacement pattern.
                t.inputBox.goalActive.replace("{goal}", () => objective)
              : t.inputBox.goalNone,
          );
          onGoalChange?.(goal);
        } else if (command.kind === "clear") {
          const response = await fetch(
            `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
              threadId,
            )}/goal`,
            { method: "DELETE", signal },
          );
          if (!response.ok) {
            throw new Error(await readGoalResponseError(response));
          }
          if (
            !isCurrentGoalRequest(
              goalRequestStateRef.current,
              request,
              threadId,
            )
          ) {
            return false;
          }
          toast.success(t.inputBox.goalCleared);
          onGoalChange?.(null);
        } else {
          const response = await fetch(
            `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
              threadId,
            )}/goal`,
            {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ objective: command.objective }),
              signal,
            },
          );
          if (!response.ok) {
            throw new Error(await readGoalResponseError(response));
          }
          goal =
            ((await response.json()) as { goal?: GoalState | null }).goal ??
            null;
          if (
            !isCurrentGoalRequest(
              goalRequestStateRef.current,
              request,
              threadId,
            )
          ) {
            return false;
          }
          toast.success(t.inputBox.goalSet);
          onGoalChange?.(goal);
        }
        textInput.setInput("");
        return true;
      } catch (error) {
        if (
          isAbortError(error) ||
          !isCurrentGoalRequest(goalRequestStateRef.current, request, threadId)
        ) {
          return false;
        }
        toast.error(
          error instanceof Error ? error.message : t.inputBox.goalFailed,
        );
        return false;
      } finally {
        finishGoalRequest(goalRequestStateRef.current, request);
      }
    },
    [
      onGoalChange,
      t.inputBox.goalActive,
      t.inputBox.goalCleared,
      t.inputBox.goalFailed,
      t.inputBox.goalNone,
      t.inputBox.goalSet,
      textInput,
      threadId,
    ],
  );

  const submitThreadMessage = useCallback(
    (message: PromptInputMessage) => {
      const files = message.files.flatMap((file) =>
        file.file instanceof File ? [file.file] : [],
      );
      const uploadValidation = validateUploadLimits([], files, uploadLimits);
      if (uploadValidation.violations.length > 0) {
        reportUploadLimitViolations(uploadValidation.violations);
        return Promise.reject(new Error("Attachment limits exceeded."));
      }
      const placeholder = findSuggestionTemplatePlaceholder(message.text);
      if (placeholder) {
        toast.error(t.inputBox.suggestionPlaceholderRequired);
        requestAnimationFrame(() => {
          const textarea = textareaRef.current;
          if (!textarea) {
            return;
          }
          textarea.focus();
          textarea.setSelectionRange(placeholder.start, placeholder.end);
        });
        return Promise.reject(
          new Error("Suggestion template placeholder is unresolved."),
        );
      }
      promptHistoryIndexRef.current = null;
      promptHistoryDraftRef.current = "";
      setFollowups([]);
      setFollowupsHidden(false);
      setFollowupsLoading(false);
      const quotes = sidecar?.conversationQuotes ?? [];
      const quoteIds = quotes.map((quote) => quote.id);
      const quoteContexts = quotes.map((quote) => quote.context);
      const submitOptions: InputBoxSubmitOptions | undefined = quotes.length
        ? {
            additionalKwargs: buildReferenceMessageMetadata(quoteContexts),
            additionalInputMessages: [
              buildHiddenConversationQuoteMessage({
                contexts: quoteContexts,
              }),
            ],
            // Clear quotes only once the send genuinely proceeds. If the send
            // is dropped by the in-flight guard, `onSent` never fires and the
            // quotes stay attached so they aren't silently lost.
            onSent: () => {
              sidecar?.clearConversationQuotes(quoteIds);
            },
          }
        : undefined;
      const submit = () => onSubmit?.(message, submitOptions);

      // Guard against submitting before the initial model auto-selection
      // effect has flushed thread settings to storage/state.
      if (resolvedModelName && context.model_name !== resolvedModelName) {
        onContextChange?.({
          ...context,
          model_name: resolvedModelName,
          mode: getResolvedMode(
            context.mode,
            selectedModel?.supports_thinking ?? false,
          ),
        });
        return new Promise<void>((resolve, reject) => {
          setTimeout(() => {
            Promise.resolve(submit()).then(resolve).catch(reject);
          }, 0);
        });
      }

      return submit();
    },
    [
      context,
      onContextChange,
      onSubmit,
      reportUploadLimitViolations,
      resolvedModelName,
      selectedModel?.supports_thinking,
      sidecar,
      t.inputBox.suggestionPlaceholderRequired,
      uploadLimits,
    ],
  );

  const handleSubmit = useCallback(
    async (message: PromptInputMessage) => {
      if (status === "streaming") {
        toast.info(t.inputBox.pleaseWaitStreaming);
        return Promise.reject(new Error("streaming"));
      }
      const submitAction = getInputSubmitAction({
        text: message.text,
        fileCount: message.files.length,
        status,
      });
      if (submitAction.kind === "goal") {
        promptHistoryIndexRef.current = null;
        promptHistoryDraftRef.current = "";
        setFollowups([]);
        setFollowupsHidden(false);
        setFollowupsLoading(false);
        const saved = await handleGoalCommand(submitAction.command);
        // Only start a run when a goal was actually saved; status/clear never run.
        if (saved && submitAction.command.kind === "set") {
          return submitThreadMessage({
            ...message,
            text: submitAction.command.objective,
            files: [],
          });
        }
        return;
      }
      if (submitAction.kind === "stop") {
        onStop?.();
        return;
      }
      if (submitAction.kind === "empty") {
        return;
      }
      return submitThreadMessage(message);
    },
    [
      handleGoalCommand,
      onStop,
      status,
      submitThreadMessage,
      t.inputBox.pleaseWaitStreaming,
    ],
  );

  const requestFormSubmit = useCallback(() => {
    const form = promptRootRef.current?.querySelector("form");
    form?.requestSubmit();
  }, []);

  const handleFollowupClick = useCallback(
    (suggestion: string) => {
      if (status === "streaming") {
        return;
      }
      const current = (textInput.value ?? "").trim();
      if (current) {
        setPendingSuggestion(suggestion);
        setConfirmOpen(true);
        return;
      }
      textInput.setInput(suggestion);
      setFollowupsHidden(true);
      setTimeout(() => requestFormSubmit(), 0);
    },
    [requestFormSubmit, status, textInput],
  );

  const confirmReplaceAndSend = useCallback(() => {
    if (!pendingSuggestion) {
      setConfirmOpen(false);
      return;
    }
    textInput.setInput(pendingSuggestion);
    setFollowupsHidden(true);
    setConfirmOpen(false);
    setPendingSuggestion(null);
    setTimeout(() => requestFormSubmit(), 0);
  }, [pendingSuggestion, requestFormSubmit, textInput]);

  const confirmAppendAndSend = useCallback(() => {
    if (!pendingSuggestion) {
      setConfirmOpen(false);
      return;
    }
    const current = (textInput.value ?? "").trim();
    const next = current
      ? `${current}\n${pendingSuggestion}`
      : pendingSuggestion;
    textInput.setInput(next);
    setFollowupsHidden(true);
    setConfirmOpen(false);
    setPendingSuggestion(null);
    setTimeout(() => requestFormSubmit(), 0);
  }, [pendingSuggestion, requestFormSubmit, textInput]);

  const slashSkillQuery = useMemo(
    () => getLeadingSlashSkillQuery(textInput.value ?? ""),
    [textInput.value],
  );
  const skillSuggestions = useMemo(
    () =>
      slashSkillQuery === null
        ? []
        : getMatchingSkillSuggestions(
            skills,
            slashSkillQuery,
            builtinSlashCommands,
          ),
    [builtinSlashCommands, skills, slashSkillQuery],
  );
  const showSkillSuggestions =
    !disabled &&
    textareaFocused &&
    slashSkillQuery !== null &&
    skillSuggestions.length > 0 &&
    dismissedSkillSuggestionValue !== textInput.value;

  useEffect(() => {
    setSkillSuggestionIndex(0);
  }, [slashSkillQuery, skillSuggestions.length]);

  const applySkillSuggestion = useCallback(
    (suggestion: SlashSuggestion) => {
      const nextValue = `/${suggestion.name} `;
      textInput.setInput(nextValue);
      setDismissedSkillSuggestionValue(nextValue);
      requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        if (!textarea) {
          return;
        }
        textarea.focus();
        textarea.setSelectionRange(nextValue.length, nextValue.length);
      });
    },
    [textInput],
  );

  const handleSkillSuggestionKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (!showSkillSuggestions) {
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSkillSuggestionIndex(
          (index) => (index + 1) % skillSuggestions.length,
        );
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setSkillSuggestionIndex(
          (index) =>
            (index - 1 + skillSuggestions.length) % skillSuggestions.length,
        );
        return;
      }

      if (event.key === "Enter" || event.key === "Tab") {
        if (event.shiftKey) {
          return;
        }
        event.preventDefault();
        const selectedSkill = skillSuggestions[skillSuggestionIndex];
        if (selectedSkill) {
          applySkillSuggestion(selectedSkill);
        }
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        setDismissedSkillSuggestionValue(textInput.value);
      }
    },
    [
      applySkillSuggestion,
      showSkillSuggestions,
      skillSuggestionIndex,
      skillSuggestions,
      textInput.value,
    ],
  );

  const setPromptHistoryValue = useCallback(
    (value: string) => {
      textInput.setInput(value);
      requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        if (!textarea) {
          return;
        }
        textarea.focus();
        textarea.setSelectionRange(value.length, value.length);
      });
    },
    [textInput],
  );

  const handlePromptHistoryKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        isIMEComposing(event) ||
        promptHistory.length === 0 ||
        (event.key !== "ArrowUp" && event.key !== "ArrowDown")
      ) {
        return;
      }

      const currentValue = textInput.value ?? "";
      const currentHistoryIndex = promptHistoryIndexRef.current;
      const isBrowsingHistory = currentHistoryIndex !== null;

      if (!isBrowsingHistory && currentValue.length > 0) {
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        const nextIndex = isBrowsingHistory
          ? Math.max(currentHistoryIndex - 1, 0)
          : promptHistory.length - 1;
        if (!isBrowsingHistory) {
          promptHistoryDraftRef.current = currentValue;
        }
        promptHistoryIndexRef.current = nextIndex;
        setPromptHistoryValue(promptHistory[nextIndex] ?? "");
        return;
      }

      if (!isBrowsingHistory) {
        return;
      }

      event.preventDefault();
      if (currentHistoryIndex >= promptHistory.length - 1) {
        promptHistoryIndexRef.current = null;
        setPromptHistoryValue(promptHistoryDraftRef.current);
        promptHistoryDraftRef.current = "";
        return;
      }

      const nextIndex = currentHistoryIndex + 1;
      promptHistoryIndexRef.current = nextIndex;
      setPromptHistoryValue(promptHistory[nextIndex] ?? "");
    },
    [promptHistory, setPromptHistoryValue, textInput.value],
  );

  const handlePromptTextareaKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      handleSkillSuggestionKeyDown(event);
      if (event.defaultPrevented) {
        return;
      }
      handlePromptHistoryKeyDown(event);
    },
    [handlePromptHistoryKeyDown, handleSkillSuggestionKeyDown],
  );

  const handlePromptTextareaChange = useCallback(() => {
    promptHistoryIndexRef.current = null;
    promptHistoryDraftRef.current = "";
  }, []);

  const showFollowups =
    !disabled &&
    !isWelcomeMode &&
    !showSkillSuggestions &&
    !followupsHidden &&
    (followupsLoading || followups.length > 0);

  useEffect(() => {
    onFollowupsVisibilityChange?.(showFollowups);
  }, [onFollowupsVisibilityChange, showFollowups]);

  useEffect(() => {
    return () => onFollowupsVisibilityChange?.(false);
  }, [onFollowupsVisibilityChange]);

  useEffect(() => {
    messagesRef.current = thread.messages;
  }, [thread.messages]);

  useEffect(() => {
    const streaming = status === "streaming";
    const wasStreaming = wasStreamingRef.current;
    wasStreamingRef.current = streaming;
    if (!wasStreaming || streaming) {
      return;
    }

    if (disabled || isMock) {
      return;
    }

    const lastAi = [...messagesRef.current]
      .reverse()
      .find((m) => m.type === "ai");
    const lastAiId = lastAi?.id ?? null;
    if (!lastAiId || lastAiId === lastGeneratedForAiIdRef.current) {
      return;
    }
    if (!suggestionsConfigLoaded) {
      return;
    }
    lastGeneratedForAiIdRef.current = lastAiId;

    const recent = messagesRef.current
      .filter((m) => m.type === "human" || m.type === "ai")
      .filter((m) => !isHiddenFromUIMessage(m))
      .map((m) => {
        const role = m.type === "human" ? "user" : "assistant";
        const content = textOfMessage(m) ?? "";
        return { role, content };
      })
      .filter((m) => m.content.trim().length > 0)
      .slice(-6);

    if (recent.length === 0) {
      return;
    }

    if (!suggestionsEnabled) {
      setFollowups([]);
      return;
    }

    const controller = new AbortController();
    setFollowupsHidden(false);
    setFollowupsLoading(true);
    setFollowups([]);

    fetch(`${getBackendBaseURL()}/api/threads/${threadId}/suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: recent,
        n: 3,
        model_name: context.model_name ?? undefined,
      }),
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          return { suggestions: [] as string[] };
        }
        return (await res.json()) as { suggestions?: string[] };
      })
      .then((data) => {
        const suggestions = (data.suggestions ?? [])
          .map((s) => (typeof s === "string" ? s.trim() : ""))
          .filter((s) => s.length > 0)
          .slice(0, 5);
        setFollowups(suggestions);
      })
      .catch(() => {
        setFollowups([]);
      })
      .finally(() => {
        setFollowupsLoading(false);
      });

    return () => controller.abort();
  }, [
    context.model_name,
    disabled,
    isMock,
    status,
    suggestionsConfigLoaded,
    suggestionsEnabled,
    threadId,
  ]);

  return (
    <div
      ref={promptRootRef}
      className={cn(
        "relative flex min-w-0 flex-col",
        isWelcomeMode ? "gap-4" : "gap-2",
      )}
    >
      {showFollowups && (
        <div className="flex items-center justify-center pb-1">
          <div className="flex items-center gap-2">
            {followupsLoading ? (
              <div className="text-muted-foreground bg-background/80 rounded-full border px-4 py-1.5 text-xs backdrop-blur-sm">
                {t.inputBox.followupLoading}
              </div>
            ) : (
              <Suggestions className="w-fit items-center">
                {followups.map((s) => (
                  <Suggestion
                    key={s}
                    className="py-1.5"
                    suggestion={s}
                    onClick={() => handleFollowupClick(s)}
                  />
                ))}
                <Button
                  aria-label={t.common.close}
                  className="text-muted-foreground h-auto cursor-pointer rounded-full px-2.5 py-1.5 text-xs font-normal"
                  variant="outline"
                  size="sm"
                  type="button"
                  onClick={() => setFollowupsHidden(true)}
                >
                  <XIcon className="size-4" />
                </Button>
              </Suggestions>
            )}
          </div>
        </div>
      )}
      {showSkillSuggestions && (
        <div className="absolute right-0 bottom-full left-0 z-40 mb-2 px-1">
          <div
            aria-label="Skill suggestions"
            className="bg-popover/95 text-popover-foreground border-border max-h-72 overflow-y-auto rounded-xl border p-1 shadow-lg backdrop-blur-sm"
            role="listbox"
          >
            {skillSuggestions.map((suggestion, index) => {
              const selected = index === skillSuggestionIndex;
              return (
                <button
                  aria-selected={selected}
                  className={cn(
                    "flex min-h-12 w-full min-w-0 cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors",
                    selected
                      ? "bg-accent text-accent-foreground"
                      : "text-popover-foreground hover:bg-accent/70 hover:text-accent-foreground",
                  )}
                  key={`${suggestion.kind}:${suggestion.name}`}
                  onClick={() => applySkillSuggestion(suggestion)}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setSkillSuggestionIndex(index)}
                  role="option"
                  type="button"
                >
                  {suggestion.kind === "builtin" ? (
                    <TargetIcon className="text-muted-foreground size-4 shrink-0" />
                  ) : (
                    <SparklesIcon className="text-muted-foreground size-4 shrink-0" />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      /{suggestion.name}
                    </span>
                    {suggestion.description && (
                      <span className="text-muted-foreground block truncate text-xs">
                        {suggestion.description}
                      </span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
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
        <PromptInputHeader className="flex-wrap px-3 pt-3 pb-0 empty:hidden">
          <PromptInputAttachments className="contents p-0">
            {(attachment) => (
              <div className="max-w-60">
                <PromptInputAttachment data={attachment} />
              </div>
            )}
          </PromptInputAttachments>
          {sidecar && sidecar.conversationQuotes.length > 0 && (
            <ReferenceAttachmentSummary
              references={sidecar.conversationQuotes}
              testId="conversation-quote-attachment"
              onClear={() => sidecar.clearConversationQuotes()}
            />
          )}
        </PromptInputHeader>
        <PromptInputBody className="absolute top-0 right-0 left-0 z-3">
          <PromptInputTextarea
            className={cn("size-full")}
            disabled={disabled}
            placeholder={t.inputBox.placeholder}
            autoFocus={autoFocus}
            defaultValue={initialValue}
            onBlur={() => setTextareaFocused(false)}
            onChange={handlePromptTextareaChange}
            onFocus={() => setTextareaFocused(true)}
            onKeyDown={handlePromptTextareaKeyDown}
            ref={textareaRef}
          />
        </PromptInputBody>
        <PromptInputFooter className="flex flex-wrap gap-2 sm:flex-nowrap">
          <PromptInputTools className="min-w-0 flex-1 flex-wrap">
            {/* TODO: Add more connectors here
          <PromptInputActionMenu>
            <PromptInputActionMenuTrigger className="px-2!" />
            <PromptInputActionMenuContent>
              <PromptInputActionAddAttachments
                label={t.inputBox.addAttachments}
              />
            </PromptInputActionMenuContent>
          </PromptInputActionMenu> */}
            <AddAttachmentsButton
              className="px-2!"
              uploadLimits={uploadLimits}
            />
            <PromptInputActionMenu>
              <ModeHoverGuide
                mode={
                  context.mode === "flash" ||
                  context.mode === "thinking" ||
                  context.mode === "pro" ||
                  context.mode === "ultra"
                    ? context.mode
                    : "flash"
                }
              >
                <PromptInputActionMenuTrigger className="max-w-28 gap-1! px-2! sm:max-w-none">
                  <div>
                    {context.mode === "flash" && <ZapIcon className="size-3" />}
                    {context.mode === "thinking" && (
                      <LightbulbIcon className="size-3" />
                    )}
                    {context.mode === "pro" && (
                      <GraduationCapIcon className="size-3" />
                    )}
                    {context.mode === "ultra" && (
                      <RocketIcon className="size-3 text-[#dabb5e]" />
                    )}
                  </div>
                  <div
                    className={cn(
                      "truncate text-xs font-normal",
                      context.mode === "ultra" ? "golden-text" : "",
                    )}
                  >
                    {(context.mode === "flash" && t.inputBox.flashMode) ||
                      (context.mode === "thinking" &&
                        t.inputBox.reasoningMode) ||
                      (context.mode === "pro" && t.inputBox.proMode) ||
                      (context.mode === "ultra" && t.inputBox.ultraMode)}
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
                        context.mode === "flash"
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
                              context.mode === "flash" &&
                                "text-accent-foreground",
                            )}
                          />
                          {t.inputBox.flashMode}
                        </div>
                        <div className="pl-7 text-xs">
                          {t.inputBox.flashModeDescription}
                        </div>
                      </div>
                      {context.mode === "flash" ? (
                        <CheckIcon className="ml-auto size-4" />
                      ) : (
                        <div className="ml-auto size-4" />
                      )}
                    </PromptInputActionMenuItem>
                    {supportThinking && (
                      <PromptInputActionMenuItem
                        className={cn(
                          context.mode === "thinking"
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
                                context.mode === "thinking" &&
                                  "text-accent-foreground",
                              )}
                            />
                            {t.inputBox.reasoningMode}
                          </div>
                          <div className="pl-7 text-xs">
                            {t.inputBox.reasoningModeDescription}
                          </div>
                        </div>
                        {context.mode === "thinking" ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </PromptInputActionMenuItem>
                    )}
                    <PromptInputActionMenuItem
                      className={cn(
                        context.mode === "pro"
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
                              context.mode === "pro" &&
                                "text-accent-foreground",
                            )}
                          />
                          {t.inputBox.proMode}
                        </div>
                        <div className="pl-7 text-xs">
                          {t.inputBox.proModeDescription}
                        </div>
                      </div>
                      {context.mode === "pro" ? (
                        <CheckIcon className="ml-auto size-4" />
                      ) : (
                        <div className="ml-auto size-4" />
                      )}
                    </PromptInputActionMenuItem>
                    <PromptInputActionMenuItem
                      className={cn(
                        context.mode === "ultra"
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
                              context.mode === "ultra" && "text-[#dabb5e]",
                            )}
                          />
                          <div
                            className={cn(
                              context.mode === "ultra" && "golden-text",
                            )}
                          >
                            {t.inputBox.ultraMode}
                          </div>
                        </div>
                        <div className="pl-7 text-xs">
                          {t.inputBox.ultraModeDescription}
                        </div>
                      </div>
                      {context.mode === "ultra" ? (
                        <CheckIcon className="ml-auto size-4" />
                      ) : (
                        <div className="ml-auto size-4" />
                      )}
                    </PromptInputActionMenuItem>
                  </PromptInputActionMenu>
                </DropdownMenuGroup>
              </PromptInputActionMenuContent>
            </PromptInputActionMenu>
            {supportReasoningEffort && context.mode !== "flash" && (
              <PromptInputActionMenu>
                <PromptInputActionMenuTrigger className="hidden gap-1! px-2! sm:inline-flex">
                  <div className="text-xs font-normal">
                    {t.inputBox.reasoningEffort}:
                    {context.reasoning_effort === "minimal" &&
                      " " + t.inputBox.reasoningEffortMinimal}
                    {context.reasoning_effort === "low" &&
                      " " + t.inputBox.reasoningEffortLow}
                    {context.reasoning_effort === "medium" &&
                      " " + t.inputBox.reasoningEffortMedium}
                    {context.reasoning_effort === "high" &&
                      " " + t.inputBox.reasoningEffortHigh}
                  </div>
                </PromptInputActionMenuTrigger>
                <PromptInputActionMenuContent className="w-70">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel className="text-muted-foreground text-xs">
                      {t.inputBox.reasoningEffort}
                    </DropdownMenuLabel>
                    <PromptInputActionMenu>
                      <PromptInputActionMenuItem
                        className={cn(
                          context.reasoning_effort === "minimal"
                            ? "text-accent-foreground"
                            : "text-muted-foreground/65",
                        )}
                        onSelect={() => handleReasoningEffortSelect("minimal")}
                      >
                        <div className="flex flex-col gap-2">
                          <div className="flex items-center gap-1 font-bold">
                            {t.inputBox.reasoningEffortMinimal}
                          </div>
                          <div className="pl-2 text-xs">
                            {t.inputBox.reasoningEffortMinimalDescription}
                          </div>
                        </div>
                        {context.reasoning_effort === "minimal" ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </PromptInputActionMenuItem>
                      <PromptInputActionMenuItem
                        className={cn(
                          context.reasoning_effort === "low"
                            ? "text-accent-foreground"
                            : "text-muted-foreground/65",
                        )}
                        onSelect={() => handleReasoningEffortSelect("low")}
                      >
                        <div className="flex flex-col gap-2">
                          <div className="flex items-center gap-1 font-bold">
                            {t.inputBox.reasoningEffortLow}
                          </div>
                          <div className="pl-2 text-xs">
                            {t.inputBox.reasoningEffortLowDescription}
                          </div>
                        </div>
                        {context.reasoning_effort === "low" ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </PromptInputActionMenuItem>
                      <PromptInputActionMenuItem
                        className={cn(
                          context.reasoning_effort === "medium" ||
                            !context.reasoning_effort
                            ? "text-accent-foreground"
                            : "text-muted-foreground/65",
                        )}
                        onSelect={() => handleReasoningEffortSelect("medium")}
                      >
                        <div className="flex flex-col gap-2">
                          <div className="flex items-center gap-1 font-bold">
                            {t.inputBox.reasoningEffortMedium}
                          </div>
                          <div className="pl-2 text-xs">
                            {t.inputBox.reasoningEffortMediumDescription}
                          </div>
                        </div>
                        {context.reasoning_effort === "medium" ||
                        !context.reasoning_effort ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </PromptInputActionMenuItem>
                      <PromptInputActionMenuItem
                        className={cn(
                          context.reasoning_effort === "high"
                            ? "text-accent-foreground"
                            : "text-muted-foreground/65",
                        )}
                        onSelect={() => handleReasoningEffortSelect("high")}
                      >
                        <div className="flex flex-col gap-2">
                          <div className="flex items-center gap-1 font-bold">
                            {t.inputBox.reasoningEffortHigh}
                          </div>
                          <div className="pl-2 text-xs">
                            {t.inputBox.reasoningEffortHighDescription}
                          </div>
                        </div>
                        {context.reasoning_effort === "high" ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </PromptInputActionMenuItem>
                    </PromptInputActionMenu>
                  </DropdownMenuGroup>
                </PromptInputActionMenuContent>
              </PromptInputActionMenu>
            )}
          </PromptInputTools>
          <PromptInputTools className="min-w-0 justify-end">
            <ModelSelector
              open={modelDialogOpen}
              onOpenChange={setModelDialogOpen}
            >
              <ModelSelectorTrigger asChild>
                <PromptInputButton className="max-w-40 min-w-0 sm:max-w-56">
                  <div className="flex min-w-0 flex-col items-start text-left">
                    <ModelSelectorName className="text-xs font-normal">
                      {selectedModel?.display_name}
                    </ModelSelectorName>
                  </div>
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
                      <div className="flex min-w-0 flex-1 flex-col">
                        <ModelSelectorName>{m.display_name}</ModelSelectorName>
                        <span className="text-muted-foreground truncate text-[10px]">
                          {m.model}
                        </span>
                      </div>
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
              onClick={(e) => {
                if (status === "streaming") {
                  e.preventDefault();
                  onStop?.();
                }
              }}
            />
          </PromptInputTools>
        </PromptInputFooter>
        {!isWelcomeMode && (
          <div className="bg-background absolute right-0 -bottom-[17px] left-0 z-0 h-4"></div>
        )}
      </PromptInput>

      {isWelcomeMode &&
        searchParams.get("mode") !== "skill" &&
        !showSkillSuggestions && (
          <div className="flex items-center justify-center pt-2">
            <SuggestionList textareaRef={textareaRef} />
          </div>
        )}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.inputBox.followupConfirmTitle}</DialogTitle>
            <DialogDescription>
              {t.inputBox.followupConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              {t.common.cancel}
            </Button>
            <Button variant="secondary" onClick={confirmAppendAndSend}>
              {t.inputBox.followupConfirmAppend}
            </Button>
            <Button onClick={confirmReplaceAndSend}>
              {t.inputBox.followupConfirmReplace}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SuggestionList({
  textareaRef,
}: {
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}) {
  const { t } = useI18n();
  const { textInput } = usePromptInputController();
  const handleSuggestionClick = useCallback(
    (prompt: string | undefined) => {
      if (!prompt) return;
      textInput.setInput(prompt);
      requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        const placeholder = findSuggestionTemplatePlaceholder(prompt);
        if (textarea && placeholder) {
          textarea.focus();
          textarea.setSelectionRange(placeholder.start, placeholder.end);
        }
      });
    },
    [textareaRef, textInput],
  );
  return (
    <Suggestions className="min-h-16 w-full max-w-full justify-center px-4 sm:w-fit sm:px-0">
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

function AddAttachmentsButton({
  className,
  uploadLimits,
}: {
  className?: string;
  uploadLimits?: UploadLimits;
}) {
  const { t } = useI18n();
  const attachments = usePromptInputAttachments();
  const tooltipContent = uploadLimits
    ? t.uploads.limitsHint(
        uploadLimits.max_files,
        formatUploadSize(uploadLimits.max_file_size),
        formatUploadSize(uploadLimits.max_total_size),
      )
    : t.inputBox.addAttachments;
  return (
    <Tooltip content={<span className="block max-w-80">{tooltipContent}</span>}>
      <PromptInputButton
        aria-label={t.inputBox.addAttachments}
        className={cn("px-2!", className)}
        data-testid="add-attachments-button"
        onClick={() => attachments.openFileDialog()}
      >
        <PaperclipIcon className="size-3" />
      </PromptInputButton>
    </Tooltip>
  );
}
