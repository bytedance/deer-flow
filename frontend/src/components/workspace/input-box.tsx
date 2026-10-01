"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useQueryClient } from "@tanstack/react-query";
import type { ChatStatus } from "ai";
import {
  AtSignIcon,
  CheckIcon,
  GraduationCapIcon,
  LightbulbIcon,
  Loader2Icon,
  MicIcon,
  PaperclipIcon,
  PlusIcon,
  RocketIcon,
  SparklesIcon,
  SquareIcon,
  TargetIcon,
  Undo2Icon,
  XIcon,
  ZapIcon,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import {
  useCallback,
  useId,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ComponentProps,
  type ClipboardEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { flushSync } from "react-dom";
import { toast } from "sonner";

import {
  PromptInput,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuItem,
  PromptInputActionMenuTrigger,
  PromptInputAttachment,
  PromptInputAttachments,
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
import { useAuth } from "@/core/auth/AuthProvider";
import { getBackendBaseURL } from "@/core/config";
import {
  buildConversationReferenceMetadata,
  type ConversationReference,
} from "@/core/conversation-references";
import { useConversationReferencesCapability } from "@/core/features/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { polishInputDraft } from "@/core/input-polish/api";
import {
  isHiddenFromUIMessage,
  type FileInMessage,
} from "@/core/messages/utils";
import { useModels } from "@/core/models/hooks";
import {
  getReasoningEffortOptions,
  getResolvedMode,
  type InputMode,
  isThinkingRequired,
  type ReasoningEffortValue,
  reasoningEffortForMode,
  resolveReasoningEffort,
  supportsThinking as modelSupportsThinking,
} from "@/core/models/reasoning";
import { attachProjectDocument } from "@/core/projects/api";
import { useStagedProjectAttachments } from "@/core/projects/composer-attach";
import {
  buildReferenceMessageMetadata,
  type SidecarContext,
} from "@/core/sidecar";
import { parseSlashSkillReference } from "@/core/skills";
import { useSkills } from "@/core/skills/hooks";
import { DEFAULT_MAX_SUGGESTIONS } from "@/core/suggestions/api";
import { useSuggestionsConfig } from "@/core/suggestions/hooks";
import type { AgentThreadContext, GoalState } from "@/core/threads";
import { compactThreadContext } from "@/core/threads/api";
import {
  buildComposerDraftKey,
  clearComposerDraft,
  getSessionComposerDraftStorage,
  readComposerDraft,
  resolveComposerDraft,
  type ComposerDraft,
  writeComposerDraft,
} from "@/core/threads/composer-draft";
import { threadTokenUsageQueryKey } from "@/core/threads/token-usage";
import { textOfMessage } from "@/core/threads/utils";
import {
  formatUploadSize,
  splitUnsupportedUploadFiles,
  useUploadLimits,
  validateUploadLimits,
  type UploadLimits,
  type UploadLimitViolation,
} from "@/core/uploads";
import {
  appendSpeechTranscript,
  getSpeechRecognitionConstructor,
  getSpeechRecognitionLanguage,
  mapSpeechRecognitionError,
  readSpeechRecognitionTranscript,
  shouldRestartSpeechRecognition,
  type BrowserSpeechRecognition,
  type SpeechRecognitionErrorKind,
} from "@/core/voice-input/speech-recognition";
import { isCompositionConfirmEnter, isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

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
  canPolishInput,
  createGoalRequestState,
  findSuggestionTemplatePlaceholder,
  finishGoalRequest,
  filterSkillsForAgent,
  getGoalObjectiveCounter,
  getInputSubmitAction,
  getLeadingSlashCommandQuery,
  getMatchingSlashCommands,
  type GoalCommand,
  isAbortError,
  isCurrentGoalRequest,
  isGoalObjectiveTooLong,
  MAX_GOAL_OBJECTIVE_CHARS,
  readGoalResponseError,
  type SlashCommandSuggestion,
} from "./input-box-helpers";
import {
  inlineReferences,
  reconcileConversationReferences,
  MAX_EXPLICIT_SKILLS,
  referenceToken,
  readableReferences,
  restoreReferenceLabels,
  readReferenceEditor,
  referenceCaret,
  focusReferenceAt,
  renderReferenceEditor,
} from "./mentions/inline-references";
import {
  MentionPicker,
  type MentionPickerHandle,
  type MentionSelection,
} from "./mentions/mention-picker";
import { getMentionQuery, type MentionQuery } from "./mentions/query";
import { useThread } from "./messages/context";
import { ModeHoverGuide } from "./mode-hover-guide";
import {
  ModelPicker,
  ModelPickerContent,
  ModelPickerTrigger,
} from "./model-picker-content";
import { ReferenceAttachmentSummary, useMaybeSidecar } from "./sidecar";
import { Tooltip } from "./tooltip";

const COMPOSER_DRAFT_SAVE_DELAY_MS = 300;

function focusContentEditableEnd(element: HTMLElement | null) {
  if (!element) {
    return;
  }

  element.focus();
  const selection = window.getSelection();
  if (!selection) {
    return;
  }

  const range = document.createRange();
  range.selectNodeContents(element);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

function insertPlainTextAtSelection(container: HTMLElement, text: string) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) {
    return false;
  }

  const range = selection.getRangeAt(0);
  const ancestor = range.commonAncestorContainer;
  if (ancestor !== container && !container.contains(ancestor)) {
    return false;
  }

  range.deleteContents();
  const node = document.createTextNode(text);
  range.insertNode(node);
  range.setStartAfter(node);
  range.setEndAfter(node);
  selection.removeAllRanges();
  selection.addRange(range);
  return true;
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
  /** Thread IDs attached through the conversation picker; sent as run context. */
  conversationReferences?: string[];
  onSent?: () => void;
};

type VoiceRecognitionStartOptions = {
  focusAfterStart?: boolean;
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
  draftThreadId = threadId,
  projectId,
  draftAgentName,
  defaultModelName,
  knowledgeScopeControl,
  initialValue,
  onContextChange,
  onFollowupsVisibilityChange,
  onGoalChange,
  onPrepareThread,
  onReferenceFileAttached,
  onSubmit,
  onStop,
  canStopStreaming = true,
  canCreateRuns = true,
  agentSkillNames,
  agentSkillsLoading = false,
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
    reasoning_effort?: ReasoningEffortValue;
  };
  extraHeader?: React.ReactNode;
  /**
   * Whether to render the input in welcome layout (vertically centered,
   * with hero + quick action suggestions).  This is purely a visual flag,
   * decoupled from "the backend has created the thread" — see issue #2746.
   */
  isWelcomeMode?: boolean;
  threadId: string;
  draftThreadId?: string;
  projectId?: string | null;
  draftAgentName?: string | null;
  agentSkillNames?: string[] | null;
  agentSkillsLoading?: boolean;
  /**
   * The active custom agent's configured default model, if any. Used as the
   * auto-selection fallback so an agent chat honors the agent's own default
   * model instead of silently snapping to the first configured model
   * (issue #4336). ``null`` / undefined = no agent default → use models[0].
   */
  defaultModelName?: string | null;
  /** Optional knowledge-scope control rendered directly after mode. */
  knowledgeScopeControl?: React.ReactNode;
  initialValue?: string;
  onContextChange?: (
    // Explicit selections contain only the fields changed by that action,
    // never the whole thread-resolved context (which may override the account).
    context: Partial<
      Omit<
        AgentThreadContext,
        "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
      > & {
        mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
        reasoning_effort?: ReasoningEffortValue;
      }
    >,
    options?: { automatic: boolean },
  ) => void;
  onFollowupsVisibilityChange?: (visible: boolean) => void;
  onGoalChange?: (goal: GoalState | null) => void;
  /**
   * Prepare a not-yet-materialized thread before a builtin command creates
   * it server-side. The `/goal <condition>` PUT endpoint materializes a
   * missing thread row itself, so a project-scoped new chat uses this to
   * assign membership first — the later idempotent thread create would
   * otherwise return that unassigned row without the project. Only runs for
   * goal-set: status/clear never create a thread server-side. Rejecting
   * aborts the command and keeps the composer's text for a retry.
   */
  onPrepareThread?: () => void | Promise<void>;
  /** Move a prepared new project chat to its durable URL after file ingestion. */
  onReferenceFileAttached?: () => void;
  onSubmit?: (
    message: PromptInputMessage,
    options?: InputBoxSubmitOptions,
  ) => void | Promise<void>;
  onStop?: () => void;
  /**
   * Whether the caller's role holds `runs:cancel` (RFC #4063 Phase 4).
   * Defaults to true so callers that don't resolve permissions (pre-Phase-4
   * backends, storybook) keep today's behavior; the Gateway route guard
   * stays the enforcement point.
   */
  canStopStreaming?: boolean;
  /**
   * Whether the caller's role holds `runs:create` (RFC #4063 Phase 4).
   * Defaults to true so callers that don't resolve permissions (pre-Phase-4
   * backends, storybook) keep today's behavior; the Gateway route guard
   * stays the enforcement point.
   */
  canCreateRuns?: boolean;
}) {
  const { locale, t } = useI18n();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const mentionListId = useId();
  const mentionPickerRef = useRef<MentionPickerHandle>(null);
  const [activeMentionOption, setActiveMentionOption] = useState<
    string | undefined
  >();
  const conversationCapability = useConversationReferencesCapability();
  const [mentionQuery, setMentionQuery] = useState<MentionQuery | null>(null);
  const [mentionButtonOpen, setMentionButtonOpen] = useState(false);
  const [mentionBusy, setMentionBusy] = useState(false);
  const [mentionPlacement, setMentionPlacement] = useState({
    above: true,
    maxHeight: 400,
  });
  const [mentionError, setMentionError] = useState<string | null>(null);
  const mentionEpoch = useRef(0);
  const mentionInFlight = useRef(false);
  const dismissedMention = useRef<string | null>(null);
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const { models } = useModels();
  const { user } = useAuth();
  const { thread, isMock } = useThread();
  const { attachments, textInput } = usePromptInputController();
  const setTextInput = textInput.setInput;
  const sidecar = useMaybeSidecar();
  const attachmentParts = attachments.files;
  // References belong to the draft and clear only when its send proceeds.
  const [conversationReferences, setConversationReferences] = useState<
    ConversationReference[]
  >([]);

  useLayoutEffect(() => {
    mentionEpoch.current += 1;
    mentionInFlight.current = false;
    setMentionBusy(false);
    setMentionQuery(null);
    setMentionButtonOpen(false);
    setMentionError(null);
    return () => {
      mentionEpoch.current += 1;
    };
  }, [threadId, projectId]);
  const removeAttachment = attachments.remove;
  // Project documents attached from the shelf arrive already ingested
  // thread-side (spec §9): the composer shows them as completed attachments
  // and includes them in the next send without a re-upload. Staged only on
  // attach success; the hook consumes the staged entry once per thread and
  // keeps it across a Strict-Mode effect replay.
  const [projectAttachments, setProjectAttachments] =
    useStagedProjectAttachments(threadId);
  const {
    skills,
    isLoading: skillsLoading,
    isFetching: skillsFetching,
    error: skillsError,
    refetch: refetchSkills,
  } = useSkills();
  const { data: uploadLimits } = useUploadLimits(threadId);
  const promptRootRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const inlineSkillTextRef = useRef<HTMLSpanElement | null>(null);
  const inlineSkillComposingRef = useRef(false);
  const composerCaretRef = useRef(0);
  const inlineRefs = useMemo(
    () => inlineReferences(textInput.value),
    [textInput.value],
  );
  const hasInlineReferences = inlineRefs.length > 0;
  const conversationReferencesUnavailable =
    (!conversationCapability.isSuccess || conversationCapability.isLoading) &&
    inlineRefs.some((ref) => ref.kind === "conversation");
  const reconciledConversations = useMemo(
    () =>
      reconcileConversationReferences(
        textInput.value,
        conversationReferences,
        {
          enabled: conversationCapability.enabled,
          maxReferences: conversationCapability.maxReferences,
          isLoading: conversationCapability.isLoading,
          isSuccess: conversationCapability.isSuccess,
        },
        threadId,
      ),
    [
      textInput.value,
      conversationReferences,
      conversationCapability.enabled,
      conversationCapability.maxReferences,
      conversationCapability.isLoading,
      conversationCapability.isSuccess,
      threadId,
    ],
  );
  useEffect(() => {
    if (reconciledConversations.text !== textInput.value)
      setTextInput(reconciledConversations.text);
  }, [reconciledConversations.text, textInput.value, setTextInput]);
  const [inlineEditorActive, setInlineEditorActive] = useState(false);
  const projectReferenceCache = useRef(
    new Map<string, (typeof projectAttachments)[number]>(),
  );
  useLayoutEffect(() => {
    projectReferenceCache.current.clear();
    setInlineEditorActive(false);
  }, [threadId, user?.id]);
  useLayoutEffect(() => {
    for (const attachment of projectAttachments) {
      if (attachment.source_document_id)
        projectReferenceCache.current.set(
          attachment.source_document_id,
          attachment,
        );
    }
  }, [projectAttachments]);
  const inlineCompositionEndedAt = useRef(-Infinity);
  const goalRequestStateRef = useRef(createGoalRequestState());
  const compactRequestStateRef = useRef(createGoalRequestState());
  const inputPolishRequestRef = useRef<{
    controller: AbortController | null;
    sequence: number;
  }>({
    controller: null,
    sequence: 0,
  });
  const voiceRecognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const voiceBaseTextRef = useRef("");
  const voiceLatestTextRef = useRef("");
  const voiceLastErrorKindRef = useRef<SpeechRecognitionErrorKind | null>(null);
  const voiceStopRequestedRef = useRef(false);
  const voiceRestartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const startVoiceRecognitionRef = useRef<
    ((options?: VoiceRecognitionStartOptions) => boolean) | null
  >(null);
  const promptHistoryIndexRef = useRef<number | null>(null);
  const promptHistoryDraftRef = useRef("");
  const pendingDraftSubmissionRef = useRef<{
    key: string;
    text: string;
    skillName: string | null;
  } | null>(null);
  const acceptedDraftRef = useRef<{
    key: string;
    text: string;
    skillName: string | null;
  } | null>(null);
  const latestDraftRef = useRef<{
    key: string;
    draft: ComposerDraft;
  } | null>(null);
  const draftSaveTimerRef = useRef<number | null>(null);
  const draftSaveGenerationRef = useRef(0);

  const [followups, setFollowups] = useState<string[]>([]);
  const { data: suggestionsConfig } = useSuggestionsConfig();
  const suggestionsConfigLoaded = suggestionsConfig !== undefined;
  const suggestionsEnabled = suggestionsConfig?.enabled;
  const maxFollowupSuggestions =
    suggestionsConfig?.max_suggestions ?? DEFAULT_MAX_SUGGESTIONS;
  const [followupsHidden, setFollowupsHidden] = useState(false);
  const [followupsLoading, setFollowupsLoading] = useState(false);
  const [polishingInput, setPolishingInput] = useState(false);
  const [voiceListening, setVoiceListening] = useState(false);
  const [inputPolishUndo, setInputPolishUndo] = useState<{
    originalText: string;
    rewrittenText: string;
  } | null>(null);
  const [textareaFocused, setTextareaFocused] = useState(false);
  const [commandSuggestionIndex, setCommandSuggestionIndex] = useState(0);
  const [hydratedDraftKey, setHydratedDraftKey] = useState<string | null>(null);
  const [dismissedCommandSuggestionValue, setDismissedCommandSuggestionValue] =
    useState<string | null>(null);
  const lastGeneratedForAiIdRef = useRef<string | null>(null);
  const wasStreamingRef = useRef(false);
  // Set when the user stops a streaming turn. Such a turn ends on a
  // half-finished response, so we must NOT generate follow-up suggestions for it.
  const stoppedByUserRef = useRef(false);
  const messagesRef = useRef(thread.messages);

  const clearVoiceRestartTimer = useCallback(() => {
    if (voiceRestartTimerRef.current === null) {
      return;
    }
    clearTimeout(voiceRestartTimerRef.current);
    voiceRestartTimerRef.current = null;
  }, []);

  const cleanupVoiceRecognition = useCallback(
    (
      recognition: BrowserSpeechRecognition | null,
      options: { keepListening?: boolean } = {},
    ) => {
      clearVoiceRestartTimer();
      if (!recognition) {
        if (!options.keepListening) {
          voiceLastErrorKindRef.current = null;
          voiceStopRequestedRef.current = false;
          setVoiceListening(false);
        }
        return;
      }
      recognition.onend = null;
      recognition.onerror = null;
      recognition.onresult = null;
      if (voiceRecognitionRef.current === recognition) {
        voiceRecognitionRef.current = null;
      }
      if (!options.keepListening) {
        voiceLastErrorKindRef.current = null;
        voiceStopRequestedRef.current = false;
        setVoiceListening(false);
      }
    },
    [clearVoiceRestartTimer],
  );

  const abortVoiceInput = useCallback(() => {
    const recognition = voiceRecognitionRef.current;
    voiceStopRequestedRef.current = true;
    if (!recognition) {
      cleanupVoiceRecognition(null);
      return;
    }
    cleanupVoiceRecognition(recognition);
    try {
      recognition.abort();
    } catch {
      // Browser implementations can throw when the recognizer already ended.
    }
  }, [cleanupVoiceRecognition]);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingSuggestion, setPendingSuggestion] = useState<string | null>(
    null,
  );
  const builtinSlashCommands = useMemo<SlashCommandSuggestion[]>(
    () => [
      {
        name: "goal",
        description: t.inputBox.goalCommandDescription,
      },
      {
        name: "compact",
        description: t.inputBox.compactCommandDescription,
      },
    ],
    [t.inputBox.compactCommandDescription, t.inputBox.goalCommandDescription],
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
    // Prefer the active agent's configured default model over models[0] as the
    // auto-selection fallback, so an agent chat respects the agent's own
    // default instead of snapping to the first model (issue #4336).
    const agentDefaultModel = defaultModelName
      ? models.find((m) => m.name === defaultModelName)
      : undefined;
    const fallbackModel = currentModel ?? agentDefaultModel ?? models[0]!;
    const nextModelName = fallbackModel.name;
    const nextMode = getResolvedMode(context.mode, fallbackModel);
    // A remembered effort may not exist in this model's contract (issue #5073);
    // map it through the aliases / default instead of sending it verbatim.
    const nextEffort = resolveReasoningEffort(
      fallbackModel,
      context.reasoning_effort,
    );

    if (
      context.model_name === nextModelName &&
      context.mode === nextMode &&
      context.reasoning_effort === nextEffort
    ) {
      return;
    }

    onContextChange?.(
      {
        ...context,
        model_name: nextModelName,
        mode: nextMode,
        reasoning_effort: nextEffort,
      },
      { automatic: true },
    );
  }, [context, models, defaultModelName, onContextChange]);

  const selectedModel = useMemo(() => {
    if (models.length === 0) {
      return undefined;
    }
    return models.find((m) => m.name === context.model_name) ?? models[0];
  }, [context.model_name, models]);

  const resolvedModelName = selectedModel?.name;

  const supportThinking = useMemo(
    () => modelSupportsThinking(selectedModel),
    [selectedModel],
  );

  const thinkingRequired = useMemo(
    () => isThinkingRequired(selectedModel),
    [selectedModel],
  );

  // Effort choices come from the model's reasoning contract (issue #5073), so
  // a provider that only accepts e.g. low/high/max never sees a generic value.
  const reasoningEffortOptions = useMemo(
    () => getReasoningEffortOptions(selectedModel),
    [selectedModel],
  );

  const supportReasoningEffort = reasoningEffortOptions.length > 0;

  const effectiveReasoningEffort = useMemo(
    () =>
      resolveReasoningEffort(
        selectedModel,
        context.reasoning_effort ??
          reasoningEffortForMode(context.mode ?? "pro", selectedModel),
      ),
    [context.mode, context.reasoning_effort, selectedModel],
  );

  const reasoningEffortLabel = useCallback(
    (effort: string | undefined) => {
      switch (effort) {
        case "minimal":
          return t.inputBox.reasoningEffortMinimal;
        case "low":
          return t.inputBox.reasoningEffortLow;
        case "medium":
          return t.inputBox.reasoningEffortMedium;
        case "high":
          return t.inputBox.reasoningEffortHigh;
        case "xhigh":
          return t.inputBox.reasoningEffortXhigh;
        case "max":
          return t.inputBox.reasoningEffortMax;
        default:
          return effort ?? "";
      }
    },
    [t],
  );

  const reasoningEffortDescription = useCallback(
    (effort: string) => {
      switch (effort) {
        case "minimal":
          return t.inputBox.reasoningEffortMinimalDescription;
        case "low":
          return t.inputBox.reasoningEffortLowDescription;
        case "medium":
          return t.inputBox.reasoningEffortMediumDescription;
        case "high":
          return t.inputBox.reasoningEffortHighDescription;
        case "xhigh":
          return t.inputBox.reasoningEffortXhighDescription;
        case "max":
          return t.inputBox.reasoningEffortMaxDescription;
        default:
          return null;
      }
    },
    [t],
  );

  const draftKey = useMemo(
    () =>
      buildComposerDraftKey({
        userId: user?.id ?? "anonymous",
        agentName:
          draftAgentName ??
          (typeof context.agent_name === "string" ? context.agent_name : null),
        threadId: draftThreadId,
      }),
    [context.agent_name, draftAgentName, draftThreadId, user?.id],
  );
  const agentScopedSkills = useMemo(
    () =>
      agentSkillsLoading ? [] : filterSkillsForAgent(skills, agentSkillNames),
    [agentSkillNames, agentSkillsLoading, skills],
  );
  const mentionSkills = useMemo(
    () =>
      agentScopedSkills.filter(
        (skill) =>
          parseSlashSkillReference(`/${skill.name}`)?.name === skill.name,
      ),
    [agentScopedSkills],
  );
  const enabledSkillNames = useMemo(
    () =>
      new Set(
        mentionSkills
          .filter((skill) => skill.enabled)
          .map((skill) => skill.name),
      ),
    [mentionSkills],
  );
  const cancelDraftSaveTimer = useCallback(() => {
    if (draftSaveTimerRef.current === null) {
      return;
    }
    window.clearTimeout(draftSaveTimerRef.current);
    draftSaveTimerRef.current = null;
  }, []);
  const invalidateDraftSaveTimer = useCallback(() => {
    draftSaveGenerationRef.current += 1;
    cancelDraftSaveTimer();
  }, [cancelDraftSaveTimer]);
  const scheduleDraftSave = useCallback(
    (draft: ComposerDraft, key = draftKey) => {
      // An accepted attachment send keeps its text visible until upload finishes.
      // Reference cleanup can rerun this effect meanwhile; do not resurrect the
      // accepted snapshot. Actual input edits release it, even for identical text.
      const accepted = acceptedDraftRef.current;
      if (
        accepted?.key === key &&
        accepted.text === draft.text &&
        accepted.skillName === draft.skillName
      )
        return null;
      if (accepted?.key === key && !draft.text && !draft.skillName) {
        acceptedDraftRef.current = null;
      }
      if (
        !draft.text &&
        !draft.skillName &&
        pendingDraftSubmissionRef.current?.key === key
      ) {
        return null;
      }
      const pending = pendingDraftSubmissionRef.current;
      if (
        pending?.key === key &&
        (draft.text !== pending.text || draft.skillName !== pending.skillName)
      ) {
        pendingDraftSubmissionRef.current = null;
      }

      const reconciled = reconcileConversationReferences(
        draft.text,
        conversationReferences,
        conversationCapability,
        threadId,
      );
      draft = {
        ...draft,
        text: reconciled.text,
        conversationReferences: reconciled.references,
      };
      latestDraftRef.current = { key, draft };
      cancelDraftSaveTimer();
      draftSaveGenerationRef.current += 1;
      const generation = draftSaveGenerationRef.current;
      const timer = window.setTimeout(() => {
        if (
          draftSaveGenerationRef.current !== generation ||
          draftSaveTimerRef.current !== timer
        ) {
          return;
        }
        draftSaveTimerRef.current = null;
        writeComposerDraft(getSessionComposerDraftStorage(), key, draft);
      }, COMPOSER_DRAFT_SAVE_DELAY_MS);
      draftSaveTimerRef.current = timer;
      return timer;
    },
    [
      cancelDraftSaveTimer,
      draftKey,
      conversationReferences,
      conversationCapability,
      threadId,
    ],
  );
  const flushLatestDraft = useCallback(
    (expectedKey?: string) => {
      const latest = latestDraftRef.current;
      if (!latest || (expectedKey && latest.key !== expectedKey)) {
        return;
      }
      cancelDraftSaveTimer();
      writeComposerDraft(
        getSessionComposerDraftStorage(),
        latest.key,
        latest.draft,
      );
    },
    [cancelDraftSaveTimer],
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

  useLayoutEffect(() => {
    promptHistoryIndexRef.current = null;
    promptHistoryDraftRef.current = "";
    setTextInput("");
    setConversationReferences([]);
    setMentionQuery(null);
    setMentionButtonOpen(false);
    setMentionError(null);
    setMentionBusy(false);
    mentionInFlight.current = false;
    mentionEpoch.current += 1;
    setInputPolishUndo(null);
    setHydratedDraftKey(null);
    pendingDraftSubmissionRef.current = null;
    acceptedDraftRef.current = null;
    latestDraftRef.current = null;
    invalidateDraftSaveTimer();
    return () => {
      mentionEpoch.current += 1;
      flushLatestDraft(draftKey);
    };
  }, [draftKey, flushLatestDraft, invalidateDraftSaveTimer, setTextInput]);

  useLayoutEffect(() => {
    const handlePageHide = () => flushLatestDraft();
    window.addEventListener("pagehide", handlePageHide);
    return () => window.removeEventListener("pagehide", handlePageHide);
  }, [flushLatestDraft]);

  useEffect(() => {
    if (skillsLoading || agentSkillsLoading || hydratedDraftKey === draftKey) {
      return;
    }

    const savedDraft = readComposerDraft(
      getSessionComposerDraftStorage(),
      draftKey,
    );
    if (!savedDraft) {
      if (!textInput.value && initialValue) {
        setTextInput(initialValue);
      }
      setHydratedDraftKey(draftKey);
      return;
    }

    const resolvedDraft = resolveComposerDraft(savedDraft, enabledSkillNames);
    const restoredText =
      resolvedDraft.skillName &&
      !inlineReferences(resolvedDraft.text).some(
        (ref) => ref.kind === "skill" && ref.id === resolvedDraft.skillName,
      )
        ? referenceToken(
            "skill",
            resolvedDraft.skillName,
            resolvedDraft.skillName,
          ) + (resolvedDraft.text ? ` ${resolvedDraft.text}` : "")
        : resolvedDraft.text;
    setConversationReferences(savedDraft.conversationReferences ?? []);
    const existingReferences = inlineReferences(restoredText);
    const legacyReferences = (savedDraft.conversationReferences ?? []).filter(
      (ref) =>
        !existingReferences.some(
          (item) => item.kind === "conversation" && item.id === ref.threadId,
        ),
    );
    setTextInput(
      legacyReferences
        .map(
          (ref) =>
            referenceToken("conversation", ref.threadId, ref.title) + " ",
        )
        .join("") + restoredText,
    );
    setHydratedDraftKey(draftKey);
  }, [
    draftKey,
    enabledSkillNames,
    hydratedDraftKey,
    initialValue,
    setTextInput,
    agentScopedSkills,
    agentSkillsLoading,
    skillsLoading,
    textInput.value,
  ]);

  useEffect(() => {
    if (hydratedDraftKey !== draftKey) {
      return;
    }

    const draft: ComposerDraft = {
      text: textInput.value ?? "",
      skillName: null,
    };
    const timer = scheduleDraftSave(draft, draftKey);
    return () => {
      if (timer === null) {
        return;
      }
      window.clearTimeout(timer);
      if (draftSaveTimerRef.current === timer) {
        draftSaveTimerRef.current = null;
      }
    };
  }, [draftKey, hydratedDraftKey, scheduleDraftSave, textInput.value]);

  useEffect(() => {
    const goalRequestState = goalRequestStateRef.current;
    const compactRequestState = compactRequestStateRef.current;
    return () => {
      abortGoalRequest(goalRequestState);
      abortGoalRequest(compactRequestState);
    };
  }, [threadId]);

  const abortInputPolishRequest = useCallback(() => {
    inputPolishRequestRef.current.controller?.abort();
    inputPolishRequestRef.current.controller = null;
    inputPolishRequestRef.current.sequence += 1;
    setPolishingInput(false);
  }, []);

  useEffect(() => {
    return () => abortInputPolishRequest();
  }, [abortInputPolishRequest, threadId]);

  useEffect(() => {
    const currentIndex = promptHistoryIndexRef.current;
    if (currentIndex !== null && currentIndex >= promptHistory.length) {
      promptHistoryIndexRef.current = null;
      promptHistoryDraftRef.current = "";
    }
  }, [promptHistory.length]);

  const handleModelSelect = useCallback(
    (model_name: string) => {
      if (disabled || polishingInput) {
        return;
      }
      const model = models.find((m) => m.name === model_name);
      if (!model) {
        return;
      }
      const mode = getResolvedMode(context.mode, model);
      const reasoning_effort = resolveReasoningEffort(
        model,
        context.reasoning_effort,
      );
      onContextChange?.({
        model_name,
        ...(mode !== context.mode ? { mode } : {}),
        ...(reasoning_effort !== context.reasoning_effort
          ? { reasoning_effort }
          : {}),
      });
      setModelDialogOpen(false);
    },
    [disabled, onContextChange, context, models, polishingInput],
  );

  const handleModeSelect = useCallback(
    (mode: InputMode) => {
      if (disabled || polishingInput) {
        return;
      }
      const nextMode = getResolvedMode(mode, selectedModel);
      onContextChange?.({
        mode: nextMode,
        reasoning_effort: reasoningEffortForMode(nextMode, selectedModel),
      });
    },
    [disabled, onContextChange, polishingInput, selectedModel],
  );

  const handleReasoningEffortSelect = useCallback(
    (effort: ReasoningEffortValue) => {
      if (disabled || polishingInput) {
        return;
      }
      onContextChange?.({
        reasoning_effort: effort,
      });
    },
    [disabled, onContextChange, polishingInput],
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

  const handleCompactCommand = useCallback(async (): Promise<void> => {
    if (isWelcomeMode) {
      textInput.setInput("");
      toast.info(t.inputBox.compactSkipped);
      return;
    }
    const request = beginGoalRequest(compactRequestStateRef.current, threadId);
    const signal = request.controller.signal;
    try {
      const result = await compactThreadContext(threadId, {
        signal,
        agentName:
          typeof context.agent_name === "string" ? context.agent_name : null,
        modelName:
          typeof context.model_name === "string" ? context.model_name : null,
      });
      if (
        !isCurrentGoalRequest(compactRequestStateRef.current, request, threadId)
      ) {
        return;
      }
      textInput.setInput("");
      promptHistoryIndexRef.current = null;
      promptHistoryDraftRef.current = "";
      setFollowups([]);
      setFollowupsHidden(false);
      setFollowupsLoading(false);

      void queryClient.invalidateQueries({ queryKey: ["thread", threadId] });
      void queryClient.invalidateQueries({
        queryKey: threadTokenUsageQueryKey(threadId),
      });

      if (result.compacted) {
        toast.success(t.inputBox.compactSuccess);
      } else {
        toast.info(t.inputBox.compactSkipped);
      }
    } catch (error) {
      if (
        isAbortError(error) ||
        !isCurrentGoalRequest(compactRequestStateRef.current, request, threadId)
      ) {
        return;
      }
      toast.error(
        error instanceof Error ? error.message : t.inputBox.compactFailed,
      );
    } finally {
      finishGoalRequest(compactRequestStateRef.current, request);
    }
  }, [
    context.agent_name,
    context.model_name,
    queryClient,
    t.inputBox.compactFailed,
    t.inputBox.compactSkipped,
    t.inputBox.compactSuccess,
    isWelcomeMode,
    textInput,
    threadId,
  ]);

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
        toast.warning(t.inputBox.suggestionPlaceholderRequired);
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
      setInputPolishUndo(null);
      setFollowups([]);
      setFollowupsHidden(false);
      setFollowupsLoading(false);
      const quotes = sidecar?.conversationQuotes ?? [];
      const quoteIds = quotes.map((quote) => quote.id);
      const quoteContexts = quotes.map((quote) => quote.context);
      const currentReferences = inlineReferences(textInput.value);
      if (
        (!conversationCapability.isSuccess ||
          conversationCapability.isLoading) &&
        currentReferences.some((ref) => ref.kind === "conversation")
      ) {
        return Promise.reject(
          new Error(
            "Conversation capability is not available. Retry discovery before sending.",
          ),
        );
      }
      const activeConversations = reconcileConversationReferences(
        textInput.value,
        conversationReferences,
        conversationCapability,
        threadId,
      ).references;
      const referenceIds = activeConversations.map(
        (reference) => reference.threadId,
      );
      // Project-shelf attachments are already ingested thread-side (§9):
      // they join ``additional_kwargs.files`` as completed uploads without a
      // re-upload, and merge with any files uploaded in this send
      // (buildThreadSubmitMessages concatenates the two lists).
      const stagedFiles: FileInMessage[] = projectAttachments
        .filter(
          (file) =>
            !file.source_document_id ||
            currentReferences.some(
              (ref) =>
                ref.kind === "file" && ref.id === file.source_document_id,
            ),
        )
        .map((attachment) => ({
          filename: attachment.filename,
          size: attachment.size_bytes,
          path: attachment.virtual_path,
          status: "uploaded" as const,
        }));
      const skillReferences = [
        ...new Set(
          inlineReferences(textInput.value)
            .filter((ref) => ref.kind === "skill")
            .map((ref) => ref.id),
        ),
      ];
      if (skillReferences.length > MAX_EXPLICIT_SKILLS) {
        toast.warning(t.inputBox.mentionMultipleSkills);
        return Promise.reject(new Error("Too many skill references."));
      }
      pendingDraftSubmissionRef.current = {
        key: draftKey,
        text: textInput.value,
        skillName: null,
      };
      const additionalKwargs = {
        ...(skillReferences.length
          ? { skill_references: skillReferences }
          : {}),
        ...(quotes.length ? buildReferenceMessageMetadata(quoteContexts) : {}),
        ...(referenceIds.length
          ? buildConversationReferenceMetadata(activeConversations)
          : {}),
        ...(stagedFiles.length > 0 ? { files: stagedFiles } : {}),
      };
      const submitOptions: InputBoxSubmitOptions = {
        ...(Object.keys(additionalKwargs).length ? { additionalKwargs } : {}),
        ...(quotes.length
          ? {
              additionalInputMessages: [
                buildHiddenConversationQuoteMessage({
                  contexts: quoteContexts,
                }),
              ],
            }
          : {}),
        ...(referenceIds.length
          ? { conversationReferences: referenceIds }
          : {}),
        // Clear one-time state only once the send genuinely proceeds. If the
        // send is dropped by the in-flight guard, `onSent` never fires.
        onSent: () => {
          setMentionQuery(null);
          setMentionButtonOpen(false);
          if (pendingDraftSubmissionRef.current?.key === draftKey) {
            acceptedDraftRef.current = {
              key: draftKey,
              text: textInput.value,
              skillName: null,
            };
            pendingDraftSubmissionRef.current = null;
            latestDraftRef.current = null;
            invalidateDraftSaveTimer();
            clearComposerDraft(getSessionComposerDraftStorage(), draftKey);
          }
          sidecar?.clearConversationQuotes(quoteIds);
          setConversationReferences([]);
          setProjectAttachments([]);
        },
      };
      const submit = () => onSubmit?.(message, submitOptions);

      // Guard against submitting before the initial model auto-selection
      // effect has flushed thread settings to storage/state.
      if (resolvedModelName && context.model_name !== resolvedModelName) {
        onContextChange?.(
          {
            ...context,
            model_name: resolvedModelName,
            mode: getResolvedMode(context.mode, selectedModel),
          },
          { automatic: true },
        );
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
      textInput.value,
      conversationReferences,
      draftKey,
      invalidateDraftSaveTimer,
      onContextChange,
      onSubmit,
      projectAttachments,
      setProjectAttachments,
      reportUploadLimitViolations,
      resolvedModelName,
      selectedModel,
      sidecar,
      t.inputBox.suggestionPlaceholderRequired,
      t.inputBox.mentionMultipleSkills,
      conversationCapability,
      threadId,
      uploadLimits,
    ],
  );

  const handleStopStreaming = useCallback(() => {
    // Roles denied runs:cancel must not interrupt the in-progress turn —
    // the Gateway would 403 the cancel anyway. The submit-button click is
    // the only live entry point today (handleSubmit returns early with the
    // pleaseWaitStreaming toast while streaming), but gate in the handler
    // as defense-in-depth so any future stop path is covered too.
    if (!canStopStreaming) {
      return;
    }
    // Mark the in-progress turn as user-interrupted so the next
    // streaming->ready transition does not suggest follow-ups for it.
    stoppedByUserRef.current = true;
    setFollowups([]);
    setFollowupsHidden(true);
    setFollowupsLoading(false);
    onStop?.();
  }, [canStopStreaming, onStop]);

  const handleSubmit = useCallback(
    async (message: PromptInputMessage) => {
      if (mentionInFlight.current)
        return Promise.reject(new Error("Reference is loading"));
      if (status === "streaming") {
        toast.info(t.inputBox.pleaseWaitStreaming);
        return Promise.reject(new Error("streaming"));
      }
      abortVoiceInput();
      message = { ...message, text: readableReferences(message.text) };
      const submitAction = getInputSubmitAction({
        text: message.text,
        // Staged project-shelf attachments count exactly like uploaded
        // files: submitThreadMessage maps them into the outgoing message's
        // ``additional_kwargs.files``, so an attachment-only submit must not
        // read as empty, and /goal or /compact must not intercept while an
        // attach chip or explicit conversation reference is present.
        fileCount:
          message.files.length +
          projectAttachments.length +
          conversationReferences.length +
          inlineRefs.length,
        status,
      });
      // Check run-starting actions before goal preparation or persistence:
      // saving a goal also clears the draft and announces success. Status,
      // clear, and compact commands do not start runs and keep their own gates.
      if (
        !canCreateRuns &&
        (submitAction.kind === "message" ||
          (submitAction.kind === "goal" && submitAction.command.kind === "set"))
      ) {
        toast.info(t.inputBox.startTurnUnavailable);
        return Promise.reject(new Error("runs-create-denied"));
      }
      if (submitAction.kind === "goal") {
        if (
          submitAction.command.kind === "set" &&
          isGoalObjectiveTooLong(submitAction.command.objective)
        ) {
          toast.error(
            t.inputBox.goalTooLong.replace("{max}", () =>
              String(MAX_GOAL_OBJECTIVE_CHARS),
            ),
          );
          // Reject so the composer keeps the user's text for editing instead of
          // clearing it (PromptInput only preserves input on a rejected submit).
          return Promise.reject(new Error("goal-too-long"));
        }
        if (submitAction.command.kind === "set") {
          // A goal-set PUT creates the thread server-side when missing, so a
          // project-scoped new chat must assign membership first. The prepare
          // callback toasts its own failure; reject so the composer keeps the
          // text for a retry instead of issuing an unassigned goal.
          //
          // Fence against conversation switches while preparation runs: the
          // goal PUT registers its AbortController only when it starts, so
          // the thread-change/unmount cleanup cannot cancel an in-flight
          // prepare. Capture the goal-request epoch before the await — the
          // cleanup bumps it via abortGoalRequest — and drop the stale
          // continuation before it can clear the new conversation's composer
          // or launch the abandoned submission.
          const requestEpoch = goalRequestStateRef.current.sequence;
          try {
            await onPrepareThread?.();
          } catch (error) {
            return Promise.reject(
              error instanceof Error
                ? error
                : new Error("thread preparation failed"),
            );
          }
          if (goalRequestStateRef.current.sequence !== requestEpoch) {
            // Reject (not resolve) so PromptInput keeps the current
            // conversation's composer text untouched.
            return Promise.reject(new Error("goal-preparation-stale"));
          }
        }
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
      if (submitAction.kind === "compact") {
        return handleCompactCommand();
      }
      if (submitAction.kind === "empty") {
        return;
      }
      await submitThreadMessage(message);
    },
    [
      abortVoiceInput,
      canCreateRuns,
      handleCompactCommand,
      handleGoalCommand,
      onPrepareThread,
      projectAttachments.length,
      conversationReferences.length,
      inlineRefs.length,
      status,
      submitThreadMessage,
      t.inputBox.goalTooLong,
      t.inputBox.pleaseWaitStreaming,
      t.inputBox.startTurnUnavailable,
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

  const slashCommandQuery = useMemo(
    () => getLeadingSlashCommandQuery(textInput.value ?? ""),
    [textInput.value],
  );
  const goalObjectiveCounter = useMemo(
    () => getGoalObjectiveCounter(textInput.value ?? ""),
    [textInput.value],
  );
  const commandSuggestions = useMemo(
    () =>
      slashCommandQuery === null || hasInlineReferences
        ? []
        : getMatchingSlashCommands(slashCommandQuery, builtinSlashCommands),
    [builtinSlashCommands, hasInlineReferences, slashCommandQuery],
  );
  const showCommandSuggestions =
    !disabled &&
    textareaFocused &&
    slashCommandQuery !== null &&
    commandSuggestions.length > 0 &&
    dismissedCommandSuggestionValue !== textInput.value;
  const isComposerDisabled = disabled === true;
  const isMockThread = isMock === true;
  const composerLocked = isComposerDisabled || polishingInput || mentionBusy;
  const showMentions =
    !disabled &&
    !polishingInput &&
    (mentionButtonOpen || mentionQuery !== null);
  useLayoutEffect(() => {
    if (!showMentions) return;
    const place = () => {
      const box = promptRootRef.current?.getBoundingClientRect();
      if (!box) return;
      const top = box.top - 12;
      const bottom = window.innerHeight - box.bottom - 12;
      const above = top >= bottom;
      setMentionPlacement({
        above,
        maxHeight: Math.max(100, above ? top : bottom),
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [showMentions]);
  const closeMentions = useCallback(() => {
    if (mentionInFlight.current) return;
    dismissedMention.current = `${textInput.value}:${mentionQuery?.end}`;
    setMentionQuery(null);
    setMentionButtonOpen(false);
    setMentionError(null);
  }, [textInput.value, mentionQuery]);
  const openMentions = useCallback(() => {
    dismissedMention.current = null;
    const caret = inlineSkillTextRef.current
      ? referenceCaret(inlineSkillTextRef.current)
      : textareaRef.current?.selectionStart;
    if (caret != null) composerCaretRef.current = caret;
    setMentionQuery(null);
    setMentionButtonOpen(true);
    setMentionError(null);
  }, []);
  const updateMentionQuery = useCallback(
    (value: string, caret: number | null) => {
      if (caret !== null) composerCaretRef.current = caret;
      if (dismissedMention.current === `${value}:${caret}`) return;
      dismissedMention.current = null;
      setMentionButtonOpen(false);
      setMentionError(null);
      setMentionQuery(caret === null ? null : getMentionQuery(value, caret));
    },
    [],
  );
  const focusComposerAt = useCallback((offset: number) => {
    requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (textarea) {
        textarea.focus();
        textarea.setSelectionRange(offset, offset);
      } else if (inlineSkillTextRef.current)
        focusReferenceAt(inlineSkillTextRef.current, offset);
    });
  }, []);
  const selectMention = useCallback(
    async (selection: MentionSelection) => {
      if (mentionInFlight.current || disabled || polishingInput) return;
      const epoch = mentionEpoch.current;
      const originalText = textInput.value;
      const caret =
        mentionQuery?.start ??
        Math.min(composerCaretRef.current, originalText.length);
      const selectionId =
        selection.kind === "skill"
          ? selection.skill.name
          : selection.kind === "conversation"
            ? selection.reference.threadId
            : null;
      const selected =
        selectionId &&
        inlineReferences(originalText).some(
          (ref) => ref.kind === selection.kind && ref.id === selectionId,
        );
      if (selected) {
        let next = mentionQuery
          ? originalText.slice(0, mentionQuery.start) +
            originalText.slice(mentionQuery.end)
          : originalText;
        for (const ref of inlineReferences(next).reverse()) {
          if (ref.kind === selection.kind && ref.id === selectionId)
            next = next.slice(0, ref.start) + next.slice(ref.end);
        }
        if (selection.kind === "conversation")
          setConversationReferences((previous) =>
            previous.filter((ref) => ref.threadId !== selectionId),
          );
        textInput.setInput(next);
        setMentionQuery(null);
        setMentionButtonOpen(false);
        focusComposerAt(Math.min(caret, next.length));
        return;
      }
      let token = "";
      if (selection.kind === "skill")
        token = referenceToken(
          "skill",
          selection.skill.name,
          selection.skill.name,
        );
      if (selection.kind === "conversation")
        token = referenceToken(
          "conversation",
          selection.reference.threadId,
          selection.reference.title,
        );
      if (selection.kind === "file")
        token = referenceToken(
          "file",
          selection.document.id,
          selection.document.name,
        );
      const inserted = token ? token + " " : "";
      const nextText =
        originalText.slice(0, caret) +
        inserted +
        originalText.slice(mentionQuery?.end ?? caret);
      if (selection.kind === "file") {
        if (!projectId) return;
        const duplicate = projectAttachments.some(
          (file) =>
            file.source_document_id === selection.document.id &&
            file.source_project_id === projectId,
        );
        if (!duplicate) {
          const allSizes = [
            ...projectAttachments.map((file) => file.size_bytes),
            ...attachments.files.map((file) => file.file?.size ?? 0),
            selection.document.size_bytes,
          ];
          if (
            uploadLimits &&
            (allSizes.length > uploadLimits.max_files ||
              allSizes.reduce((a, b) => a + b, 0) >
                uploadLimits.max_total_size ||
              selection.document.size_bytes > uploadLimits.max_file_size)
          ) {
            setMentionError(
              t.uploads.limitsHint(
                uploadLimits.max_files,
                formatUploadSize(uploadLimits.max_file_size),
                formatUploadSize(uploadLimits.max_total_size),
              ),
            );
            return;
          }
          mentionInFlight.current = true;
          setMentionBusy(true);
          setMentionError(null);
          try {
            await onPrepareThread?.();
            if (epoch !== mentionEpoch.current) return;
            const attached = await attachProjectDocument(
              projectId,
              selection.document.id,
              threadId,
            );
            if (epoch !== mentionEpoch.current) return;
            setProjectAttachments((previous) => [
              ...previous.filter(
                (file) => file.virtual_path !== attached.virtual_path,
              ),
              {
                ...attached,
                source_document_id: selection.document.id,
                source_project_id: projectId,
              },
            ]);
          } catch {
            if (epoch === mentionEpoch.current)
              setMentionError(t.inputBox.mentionAttachFailed);
            return;
          } finally {
            if (epoch === mentionEpoch.current) {
              mentionInFlight.current = false;
              setMentionBusy(false);
            }
          }
        }
      } else if (selection.kind === "conversation") {
        setConversationReferences((previous) =>
          previous.some(
            (item) => item.threadId === selection.reference.threadId,
          )
            ? previous
            : [...previous, selection.reference],
        );
      } else if (selection.kind === "upload") {
        // Keep the native file dialog in the user gesture for browser permission.
        attachments.openFileDialog();
      }
      if (
        selection.kind === "file" &&
        onReferenceFileAttached &&
        draftThreadId !== threadId
      ) {
        // A prepared new conversation now owns real files. Move its draft to
        // the durable identity before the page replaces /new with that ID.
        const storage = getSessionComposerDraftStorage();
        const nextKey = buildComposerDraftKey({
          userId: user?.id ?? "anonymous",
          agentName:
            draftAgentName ??
            (typeof context.agent_name === "string"
              ? context.agent_name
              : null),
          threadId,
        });
        writeComposerDraft(storage, nextKey, {
          text: nextText,
          skillName: null,
          ...(conversationReferences.length ? { conversationReferences } : {}),
        });
        invalidateDraftSaveTimer();
        latestDraftRef.current = null;
        clearComposerDraft(storage, draftKey);
      }
      textInput.setInput(nextText);
      setMentionQuery(null);
      setMentionButtonOpen(false);
      setMentionError(null);
      focusComposerAt(caret + inserted.length);
      if (selection.kind === "file") onReferenceFileAttached?.();
    },
    [
      attachments,
      context.agent_name,
      conversationReferences,
      draftAgentName,
      draftKey,
      draftThreadId,
      invalidateDraftSaveTimer,
      onReferenceFileAttached,
      user?.id,
      disabled,
      focusComposerAt,
      mentionQuery,
      onPrepareThread,
      polishingInput,
      projectAttachments,
      projectId,
      setProjectAttachments,
      t,
      textInput,
      threadId,
      uploadLimits,
    ],
  );
  useEffect(() => {
    if (!showMentions) return;
    const dismiss = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !promptRootRef.current?.contains(event.target)
      )
        closeMentions();
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [showMentions, closeMentions]);
  // A denied runs:cancel role sees a disabled stop affordance, not a removed
  // one — the composer must still show that a turn is in flight.
  const stopDenied = status === "streaming" && !canStopStreaming;
  // Mirror for runs:create on the send side. While streaming the button is
  // the stop affordance (gated above), so the send denial only applies to
  // the send state.
  const sendDenied = status !== "streaming" && !canCreateRuns;
  const inputPolishUndoAvailable =
    !polishingInput &&
    inputPolishUndo !== null &&
    (textInput.value ?? "") === inputPolishUndo.rewrittenText;
  const inputPolishDisabled =
    isComposerDisabled ||
    isMockThread ||
    polishingInput ||
    (!inputPolishUndoAvailable &&
      (status === "streaming" ||
        slashCommandQuery !== null ||
        !canPolishInput(textInput.value ?? "")));
  const speechRecognitionConstructor = useMemo(
    () =>
      typeof window === "undefined"
        ? null
        : getSpeechRecognitionConstructor(window),
    [],
  );
  const voiceInputSupported = speechRecognitionConstructor !== null;

  const getVoiceInputErrorMessage = useCallback(
    (kind: SpeechRecognitionErrorKind) => {
      switch (kind) {
        case "permission_denied":
          return t.inputBox.voiceInputPermissionDenied;
        case "microphone_unavailable":
          return t.inputBox.voiceInputMicrophoneUnavailable;
        case "unsupported_language":
          return t.inputBox.voiceInputUnsupportedLanguage;
        case "network":
          return t.inputBox.voiceInputNetworkError;
        case "no_speech":
          return t.inputBox.voiceInputNoSpeech;
        case "cancelled":
          return null;
        default:
          return t.inputBox.voiceInputFailed;
      }
    },
    [t],
  );

  const startVoiceRecognition = useCallback(
    (options: VoiceRecognitionStartOptions = {}) => {
      if (composerLocked || !speechRecognitionConstructor) {
        return false;
      }

      const recognition = new speechRecognitionConstructor();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = getSpeechRecognitionLanguage(locale);
      recognition.maxAlternatives = 1;
      voiceLastErrorKindRef.current = null;
      voiceLatestTextRef.current = voiceBaseTextRef.current;
      voiceRecognitionRef.current = recognition;

      recognition.onresult = (event) => {
        if (voiceRecognitionRef.current !== recognition) {
          return;
        }
        const transcript = readSpeechRecognitionTranscript(event.results).text;
        const nextValue = appendSpeechTranscript(
          voiceBaseTextRef.current,
          transcript,
        );
        voiceLatestTextRef.current = nextValue;
        textInput.setInput(nextValue);
      };
      recognition.onerror = (event) => {
        const errorKind = mapSpeechRecognitionError(event.error);
        voiceLastErrorKindRef.current = errorKind;
        if (
          !voiceStopRequestedRef.current &&
          shouldRestartSpeechRecognition(errorKind)
        ) {
          return;
        }

        const message = getVoiceInputErrorMessage(errorKind);
        if (message) {
          toast.error(message);
        }
      };
      recognition.onend = () => {
        const shouldRestart =
          voiceRecognitionRef.current === recognition &&
          !voiceStopRequestedRef.current &&
          shouldRestartSpeechRecognition(voiceLastErrorKindRef.current);
        if (shouldRestart) {
          voiceBaseTextRef.current = voiceLatestTextRef.current;
          cleanupVoiceRecognition(recognition, { keepListening: true });
          voiceRestartTimerRef.current = setTimeout(() => {
            voiceRestartTimerRef.current = null;
            if (voiceStopRequestedRef.current) {
              cleanupVoiceRecognition(null);
              return;
            }
            const restarted = startVoiceRecognitionRef.current?.() ?? false;
            if (!restarted) {
              cleanupVoiceRecognition(null);
            }
          }, 150);
          return;
        }
        cleanupVoiceRecognition(recognition);
      };

      setVoiceListening(true);
      try {
        recognition.start();
        if (options.focusAfterStart) {
          requestAnimationFrame(() => {
            if (inlineSkillTextRef.current) {
              focusContentEditableEnd(inlineSkillTextRef.current);
            } else {
              textareaRef.current?.focus();
            }
          });
        }
        return true;
      } catch {
        cleanupVoiceRecognition(recognition);
        toast.error(t.inputBox.voiceInputFailed);
        return false;
      }
    },
    [
      cleanupVoiceRecognition,
      composerLocked,
      getVoiceInputErrorMessage,
      locale,
      speechRecognitionConstructor,
      t.inputBox.voiceInputFailed,
      textInput,
    ],
  );

  useEffect(() => {
    startVoiceRecognitionRef.current = startVoiceRecognition;
  }, [startVoiceRecognition]);

  const stopVoiceInput = useCallback(() => {
    const recognition = voiceRecognitionRef.current;
    voiceStopRequestedRef.current = true;
    if (!recognition) {
      cleanupVoiceRecognition(null);
      return;
    }
    try {
      recognition.stop();
    } catch {
      cleanupVoiceRecognition(recognition);
    }
  }, [cleanupVoiceRecognition]);

  const toggleVoiceInput = useCallback(() => {
    if (voiceListening) {
      stopVoiceInput();
      return;
    }
    if (composerLocked) {
      return;
    }
    if (!speechRecognitionConstructor) {
      toast.error(t.inputBox.voiceInputUnsupported);
      return;
    }

    abortInputPolishRequest();
    setInputPolishUndo(null);
    promptHistoryIndexRef.current = null;
    promptHistoryDraftRef.current = "";
    voiceStopRequestedRef.current = false;
    voiceBaseTextRef.current = textInput.value ?? "";
    voiceLatestTextRef.current = voiceBaseTextRef.current;
    startVoiceRecognition({ focusAfterStart: true });
  }, [
    abortInputPolishRequest,
    composerLocked,
    speechRecognitionConstructor,
    startVoiceRecognition,
    stopVoiceInput,
    t.inputBox.voiceInputUnsupported,
    textInput,
    voiceListening,
  ]);

  useEffect(() => {
    if (composerLocked && voiceListening) {
      stopVoiceInput();
    }
  }, [composerLocked, stopVoiceInput, voiceListening]);

  useEffect(() => {
    return () => abortVoiceInput();
  }, [abortVoiceInput, threadId]);

  useEffect(() => {
    setCommandSuggestionIndex(0);
  }, [slashCommandQuery, commandSuggestions.length]);

  const applyCommandSuggestion = useCallback(
    (suggestion: SlashCommandSuggestion) => {
      const nextValue = `/${suggestion.name} `;
      // Commit the controlled text before moving the caret so React's selection
      // restoration cannot put fast typing back inside the command name.
      flushSync(() => {
        textInput.setInput(nextValue);
        setDismissedCommandSuggestionValue(nextValue);
      });
      const editor = inlineSkillTextRef.current;
      if (editor) {
        focusReferenceAt(editor, nextValue.length);
      } else {
        focusComposerAt(nextValue.length);
      }
    },
    [focusComposerAt, textInput],
  );

  const handleCommandSuggestionKeyDown = useCallback(
    (event: KeyboardEvent<HTMLElement>) => {
      if (!showCommandSuggestions) {
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setCommandSuggestionIndex(
          (index) => (index + 1) % commandSuggestions.length,
        );
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setCommandSuggestionIndex(
          (index) =>
            (index - 1 + commandSuggestions.length) % commandSuggestions.length,
        );
        return;
      }

      if (event.key === "Enter" || event.key === "Tab") {
        if (event.shiftKey) {
          return;
        }
        event.preventDefault();
        const selectedCommand = commandSuggestions[commandSuggestionIndex];
        if (selectedCommand) {
          applyCommandSuggestion(selectedCommand);
        }
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        setDismissedCommandSuggestionValue(textInput.value);
      }
    },
    [
      applyCommandSuggestion,
      showCommandSuggestions,
      commandSuggestionIndex,
      commandSuggestions,
      textInput.value,
    ],
  );

  const setPromptHistoryValue = useCallback(
    (value: string) => {
      textInput.setInput(value);
      requestAnimationFrame(() => {
        if (inlineSkillTextRef.current)
          focusReferenceAt(inlineSkillTextRef.current, value.length);
        else {
          const textarea = textareaRef.current;
          textarea?.focus();
          textarea?.setSelectionRange(value.length, value.length);
        }
      });
    },
    [textInput],
  );

  const handlePolishInput = useCallback(async () => {
    if (inputPolishDisabled) {
      return;
    }

    const originalText = textInput.value ?? "";
    const controller = new AbortController();
    inputPolishRequestRef.current.controller?.abort();
    const sequence = inputPolishRequestRef.current.sequence + 1;
    inputPolishRequestRef.current = {
      controller,
      sequence,
    };
    setPolishingInput(true);

    try {
      const result = await polishInputDraft(
        {
          text: readableReferences(originalText),
          locale,
          thread_id: threadId,
        },
        { signal: controller.signal },
      );

      const isCurrentRequest =
        inputPolishRequestRef.current.controller === controller &&
        inputPolishRequestRef.current.sequence === sequence &&
        !controller.signal.aborted;
      if (!isCurrentRequest || (textInput.value ?? "") !== originalText) {
        return;
      }

      const rewrittenText = restoreReferenceLabels(
        originalText,
        result.rewritten_text.trim(),
      );
      if (!rewrittenText || !result.changed) {
        toast.info(t.inputBox.inputPolishNoChanges);
        return;
      }

      // Applying the rewrite replaces the draft outside the textarea change
      // handler, so clear any in-progress history browse state; otherwise a
      // stale index would let the next ArrowDown overwrite the rewrite.
      promptHistoryIndexRef.current = null;
      promptHistoryDraftRef.current = "";
      setPromptHistoryValue(rewrittenText);
      setInputPolishUndo({
        originalText,
        rewrittenText,
      });
    } catch (error) {
      const isCurrentRequest =
        inputPolishRequestRef.current.controller === controller &&
        inputPolishRequestRef.current.sequence === sequence;
      if (isAbortError(error) || !isCurrentRequest) {
        return;
      }
      toast.error(
        error instanceof Error ? error.message : t.inputBox.inputPolishFailed,
      );
    } finally {
      if (
        inputPolishRequestRef.current.controller === controller &&
        inputPolishRequestRef.current.sequence === sequence
      ) {
        inputPolishRequestRef.current.controller = null;
        setPolishingInput(false);
      }
    }
  }, [
    inputPolishDisabled,
    locale,
    setPromptHistoryValue,
    t.inputBox.inputPolishFailed,
    t.inputBox.inputPolishNoChanges,
    textInput,
    threadId,
  ]);

  const handleUndoInputPolish = useCallback(() => {
    if (!inputPolishUndoAvailable || inputPolishUndo === null) {
      return;
    }
    promptHistoryIndexRef.current = null;
    promptHistoryDraftRef.current = "";
    setPromptHistoryValue(inputPolishUndo.originalText);
    setInputPolishUndo(null);
  }, [inputPolishUndo, inputPolishUndoAvailable, setPromptHistoryValue]);

  const handlePromptHistoryKeyDown = useCallback(
    (event: KeyboardEvent<HTMLElement>) => {
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
    (event: KeyboardEvent<HTMLElement>) => {
      // Same rule as the inline-skill editor: the catalog's navigation keys must
      // win over Enter-to-submit, but not mid-composition, where Enter belongs
      // to the IME candidate rather than the list. Safari's confirming Enter
      // carries neither composition flag; PromptInputTextarea drops it before
      // this handler runs.
      if (!isIMEComposing(event)) {
        if (showMentions) mentionPickerRef.current?.onKeyDown(event);
        if (event.defaultPrevented) return;
        handleCommandSuggestionKeyDown(event);
        if (event.defaultPrevented) {
          return;
        }
      }
      if (event.defaultPrevented) {
        return;
      }
      handlePromptHistoryKeyDown(event);
    },
    [showMentions, handlePromptHistoryKeyDown, handleCommandSuggestionKeyDown],
  );

  const handlePromptTextareaChange = useCallback(
    (event: ChangeEvent<HTMLTextAreaElement>) => {
      acceptedDraftRef.current = null;
      pendingDraftSubmissionRef.current = null;
      updateMentionQuery(
        event.currentTarget.value,
        event.currentTarget.selectionStart,
      );
      if (voiceListening) {
        abortVoiceInput();
      }
      abortInputPolishRequest();
      setInputPolishUndo(null);
      promptHistoryIndexRef.current = null;
      promptHistoryDraftRef.current = "";
      scheduleDraftSave({
        text: event.currentTarget.value,
        skillName: null,
      });
    },
    [
      abortInputPolishRequest,
      abortVoiceInput,
      scheduleDraftSave,
      updateMentionQuery,
      voiceListening,
    ],
  );

  const updateInlineSkillTextInput = useCallback(
    (element: HTMLElement) => {
      acceptedDraftRef.current = null;
      pendingDraftSubmissionRef.current = null;
      if (voiceListening) {
        abortVoiceInput();
      }
      promptHistoryIndexRef.current = null;
      promptHistoryDraftRef.current = "";
      const nextText = readReferenceEditor(element);
      const refs = inlineReferences(nextText);
      setConversationReferences(
        (previous) =>
          reconcileConversationReferences(
            nextText,
            previous,
            conversationCapability,
            threadId,
          ).references,
      );
      setProjectAttachments((previous) => {
        const ids = new Set(
          refs.filter((ref) => ref.kind === "file").map((ref) => ref.id),
        );
        return [
          ...previous.filter((file) => !file.source_document_id),
          ...[...ids].flatMap((id) => {
            const file = projectReferenceCache.current.get(id);
            return file ? [file] : [];
          }),
        ];
      });
      abortInputPolishRequest();
      setInputPolishUndo(null);
      const caret = referenceCaret(element);
      textInput.setInput(nextText);
      updateMentionQuery(nextText, caret);
      // The inline editor stays mounted after its last reference is removed.
      // Keep its native caret instead of scheduling a stale position that can
      // overwrite the caret set by a subsequently selected command.
      scheduleDraftSave({
        text: nextText,
        skillName: null,
      });
    },
    [
      conversationCapability,
      threadId,
      abortVoiceInput,
      abortInputPolishRequest,
      setProjectAttachments,
      scheduleDraftSave,
      textInput,
      updateMentionQuery,
      voiceListening,
    ],
  );

  useLayoutEffect(() => {
    if (hasInlineReferences) setInlineEditorActive(true);
    const element = inlineSkillTextRef.current;
    if (element && !inlineSkillComposingRef.current)
      renderReferenceEditor(element, textInput.value);
  }, [hasInlineReferences, textInput.value]);

  const handleInlineSkillInput = useCallback(
    (event: FormEvent<HTMLSpanElement>) => {
      updateInlineSkillTextInput(event.currentTarget);
    },
    [updateInlineSkillTextInput],
  );

  const handleInlineSkillPaste = useCallback(
    (event: ClipboardEvent<HTMLSpanElement>) => {
      const pastedFiles = Array.from(event.clipboardData.items)
        .filter((item) => item.kind === "file")
        .flatMap((item) => {
          const file = item.getAsFile();
          return file ? [file] : [];
        });

      if (pastedFiles.length > 0) {
        event.preventDefault();
        const { accepted, message } = splitUnsupportedUploadFiles(pastedFiles);
        if (message) {
          toast.error(message);
        }
        if (accepted.length > 0) {
          attachments.add(accepted);
        }
        return;
      }

      const text = event.clipboardData.getData("text/plain");
      if (!text) {
        return;
      }

      event.preventDefault();
      if (insertPlainTextAtSelection(event.currentTarget, text)) {
        updateInlineSkillTextInput(event.currentTarget);
      }
    },
    [attachments, updateInlineSkillTextInput],
  );

  const handleInlineSkillKeyDown = useCallback(
    (event: KeyboardEvent<HTMLSpanElement>) => {
      if (isCompositionConfirmEnter(event, inlineCompositionEndedAt.current)) {
        event.preventDefault();
        return;
      }
      // The catalog can be reopened from here, so its navigation keys must win
      // over Enter-to-submit. Skip it mid-composition, where Enter belongs to
      // the IME candidate rather than the list.
      if (!isIMEComposing(event, inlineSkillComposingRef.current)) {
        if (showMentions) mentionPickerRef.current?.onKeyDown(event);
        if (event.defaultPrevented) return;
        handleCommandSuggestionKeyDown(event);
        if (event.defaultPrevented) {
          return;
        }
      }

      if (event.defaultPrevented) {
        return;
      }

      handlePromptHistoryKeyDown(event);
      if (event.defaultPrevented || event.key !== "Enter") return;

      if (isIMEComposing(event, inlineSkillComposingRef.current)) {
        return;
      }

      event.preventDefault();

      if (event.shiftKey) {
        if (insertPlainTextAtSelection(event.currentTarget, "\n")) {
          updateInlineSkillTextInput(event.currentTarget);
        }
        return;
      }

      event.currentTarget.closest("form")?.requestSubmit();
    },
    [
      showMentions,
      handlePromptHistoryKeyDown,
      handleCommandSuggestionKeyDown,
      updateInlineSkillTextInput,
    ],
  );

  const showFollowups =
    !disabled &&
    !isWelcomeMode &&
    !showCommandSuggestions &&
    !showMentions &&
    !followupsHidden &&
    // Never show stale follow-up chips while a turn is streaming: a message
    // sent before the previous response finished would otherwise leave the
    // old chips (and the lone close button) overlapping the input box.
    status !== "streaming" &&
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

    // The turn was interrupted by the user, so skip generating follow-ups for
    // this half-finished response.
    if (stoppedByUserRef.current) {
      stoppedByUserRef.current = false;
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
        n: maxFollowupSuggestions,
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
          .slice(0, maxFollowupSuggestions);
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
    maxFollowupSuggestions,
    status,
    suggestionsConfigLoaded,
    suggestionsEnabled,
    threadId,
  ]);

  const onSelectPlaceholder = useCallback((newText: string) => {
    const placeholder = findSuggestionTemplatePlaceholder(newText);
    if (placeholder) {
      requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        if (!textarea) return;
        textarea.focus();
        textarea.setSelectionRange(placeholder.start, placeholder.end);
      });
    }
  }, []);

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
      {showMentions && (
        <div
          className={cn(
            "absolute right-0 left-0 z-50 overflow-y-auto px-1",
            mentionPlacement.above ? "bottom-full mb-2" : "top-full mt-2",
          )}
          style={{ maxHeight: mentionPlacement.maxHeight }}
        >
          <MentionPicker
            ref={mentionPickerRef}
            listId={mentionListId}
            query={mentionQuery?.query ?? ""}
            searchInput={mentionButtonOpen}
            skills={mentionSkills}
            selectedSkills={inlineRefs
              .filter((ref) => ref.kind === "skill")
              .map((ref) => ref.id)}
            references={reconciledConversations.references}
            capability={conversationCapability}
            skillsLoading={skillsLoading || skillsFetching}
            skillsError={skillsError}
            onRetrySkills={refetchSkills}
            onActiveOptionChange={setActiveMentionOption}
            threadId={threadId}
            projectId={projectId}
            busy={mentionBusy}
            error={mentionError}
            onSelect={(selection) => void selectMention(selection)}
            onClose={() => {
              closeMentions();
              focusComposerAt(mentionQuery?.end ?? textInput.value.length);
            }}
          />
        </div>
      )}
      {showCommandSuggestions && !showMentions && (
        <div className="absolute right-0 bottom-full left-0 z-40 mb-2 px-1">
          <div
            aria-label="Command suggestions"
            className="bg-popover/95 text-popover-foreground border-border max-h-72 overflow-y-auto rounded-xl border p-1 shadow-lg backdrop-blur-sm"
            role="listbox"
          >
            {commandSuggestions.map((suggestion, index) => {
              const selected = index === commandSuggestionIndex;
              return (
                <button
                  aria-selected={selected}
                  className={cn(
                    "flex min-h-12 w-full min-w-0 cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors",
                    selected
                      ? "bg-accent text-accent-foreground"
                      : "text-popover-foreground hover:bg-accent/70 hover:text-accent-foreground",
                  )}
                  key={suggestion.name}
                  onClick={() => applyCommandSuggestion(suggestion)}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setCommandSuggestionIndex(index)}
                  role="option"
                  type="button"
                >
                  <TargetIcon className="text-muted-foreground size-4 shrink-0" />
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
          "bg-background/85 relative z-10 rounded-2xl backdrop-blur-sm transition-all duration-300 ease-out *:data-[slot='input-group']:rounded-2xl",
          polishingInput &&
            "shadow-primary/10 ring-primary/25 shadow-lg ring-1",
          className,
        )}
        disabled={composerLocked}
        globalDrop
        multiple
        onSubmit={handleSubmit}
        {...props}
      >
        {polishingInput && (
          <div
            aria-hidden="true"
            className="border-primary/30 bg-primary/5 pointer-events-auto absolute inset-0 z-20 animate-pulse cursor-wait rounded-2xl border opacity-80"
          />
        )}
        {extraHeader && (
          <div className="absolute top-0 right-0 left-0 z-10">
            <div className="absolute right-0 bottom-0 left-0 flex items-center justify-center">
              {extraHeader}
            </div>
          </div>
        )}
        <PromptInputHeader className="flex-wrap px-3 pt-3 pb-0 empty:hidden">
          {!!conversationCapability.error &&
            inlineRefs.some((ref) => ref.kind === "conversation") && (
              <div role="alert" className="w-full text-xs">
                {t.inputBox.mentionFailed}{" "}
                <button
                  type="button"
                  className="underline"
                  data-testid="retry-conversation-capability"
                  onClick={() => void conversationCapability.refetch()}
                >
                  {t.inputBox.mentionRetry}
                </button>
              </div>
            )}
          <PromptInputAttachments className="contents p-0">
            {(attachment) => (
              <div className="max-w-60">
                <PromptInputAttachment data={attachment} />
              </div>
            )}
          </PromptInputAttachments>
          {projectAttachments
            .filter((attachment) => !attachment.source_document_id)
            .map((attachment) => (
              <div
                key={attachment.virtual_path}
                className="bg-muted text-muted-foreground flex h-7 items-center gap-1.5 rounded-full border py-0 pr-1 pl-2.5 text-xs font-medium"
                data-testid="project-attachment-chip"
              >
                <PaperclipIcon className="size-3" />
                <span className="max-w-40 truncate">{attachment.filename}</span>
                <button
                  aria-label={t.inputBox.removeProjectAttachment}
                  className="hover:bg-primary/20 focus-visible:ring-primary/40 -mr-0.5 ml-0.5 flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-full transition-colors focus-visible:ring-2 focus-visible:outline-none"
                  type="button"
                  onClick={() =>
                    setProjectAttachments((previous) =>
                      previous.filter(
                        (candidate) =>
                          candidate.virtual_path !== attachment.virtual_path,
                      ),
                    )
                  }
                >
                  <XIcon className="size-3" />
                </button>
              </div>
            ))}
          {polishingInput && (
            <div
              aria-live="polite"
              className="text-primary bg-primary/10 border-primary/20 relative z-30 flex h-7 items-center gap-1.5 rounded-full border py-0 pr-1 pl-2.5 text-xs font-medium"
              role="status"
            >
              <Loader2Icon className="size-3 animate-spin" />
              {t.inputBox.inputPolishing}
              <button
                aria-label={t.inputBox.inputPolishCancel}
                className="hover:bg-primary/20 focus-visible:ring-primary/40 -mr-0.5 ml-0.5 flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-full transition-colors focus-visible:ring-2 focus-visible:outline-none"
                data-testid="cancel-polish-input-button"
                onClick={abortInputPolishRequest}
                type="button"
              >
                <XIcon className="size-3" />
              </button>
            </div>
          )}
          {sidecar && sidecar.conversationQuotes.length > 0 && (
            <ReferenceAttachmentSummary
              references={sidecar.conversationQuotes}
              testId="conversation-quote-attachment"
              onClear={() => sidecar.clearConversationQuotes()}
            />
          )}
        </PromptInputHeader>
        <div className="min-h-16 w-full min-w-0 px-3 py-3">
          {hasInlineReferences || inlineEditorActive ? (
            <div
              className="max-h-48 min-h-6 w-full min-w-0 cursor-text overflow-y-auto text-base leading-7 break-words whitespace-pre-wrap md:text-sm"
              onClick={(event) => {
                if (event.target === event.currentTarget) {
                  focusContentEditableEnd(inlineSkillTextRef.current);
                }
              }}
            >
              <span
                aria-label={t.inputBox.placeholder}
                aria-multiline="true"
                contentEditable={!composerLocked}
                data-empty={textInput.value.length === 0}
                data-placeholder={t.inputBox.placeholder}
                data-slot="input-group-control"
                onBlur={() => setTextareaFocused(false)}
                onCompositionEnd={() => {
                  inlineSkillComposingRef.current = false;
                  inlineCompositionEndedAt.current = Date.now();
                }}
                onCompositionStart={() => {
                  inlineSkillComposingRef.current = true;
                }}
                onFocus={() => setTextareaFocused(true)}
                aria-controls={showMentions ? mentionListId : undefined}
                aria-activedescendant={
                  showMentions ? activeMentionOption : undefined
                }
                onClick={(event) =>
                  updateMentionQuery(
                    readReferenceEditor(event.currentTarget),
                    referenceCaret(event.currentTarget),
                  )
                }
                onKeyUp={(event) => {
                  if (
                    ["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                      event.key,
                    )
                  )
                    updateMentionQuery(
                      readReferenceEditor(event.currentTarget),
                      referenceCaret(event.currentTarget),
                    );
                }}
                onInput={handleInlineSkillInput}
                onKeyDown={handleInlineSkillKeyDown}
                onPaste={handleInlineSkillPaste}
                aria-placeholder={t.inputBox.placeholder}
                ref={inlineSkillTextRef}
                role="textbox"
                suppressContentEditableWarning
                className={cn(
                  "block min-h-6 outline-none",
                  "before:text-muted-foreground before:pointer-events-none",
                  "data-[empty=true]:before:content-[attr(data-placeholder)]",
                  composerLocked && "cursor-not-allowed opacity-50",
                )}
                tabIndex={composerLocked ? -1 : 0}
              />
            </div>
          ) : (
            <PromptInputTextarea
              className="min-h-6! w-full min-w-0 p-0! leading-6!"
              disabled={composerLocked}
              placeholder={t.inputBox.placeholder}
              autoFocus={autoFocus}
              defaultValue={initialValue}
              onBlur={() => setTextareaFocused(false)}
              aria-controls={showMentions ? mentionListId : undefined}
              aria-activedescendant={
                showMentions ? activeMentionOption : undefined
              }
              onSelect={(event) => {
                const input = event.currentTarget;
                if (!mentionButtonOpen && !mentionInFlight.current)
                  updateMentionQuery(
                    input.value,
                    input.selectionStart === input.selectionEnd
                      ? input.selectionStart
                      : null,
                  );
              }}
              onChange={handlePromptTextareaChange}
              onFocus={() => setTextareaFocused(true)}
              onKeyDown={handlePromptTextareaKeyDown}
              ref={textareaRef}
            />
          )}
        </div>
        <PromptInputFooter className="flex flex-wrap gap-2 sm:flex-nowrap">
          <PromptInputTools className="min-w-0 flex-1 flex-wrap">
            <Tooltip content={t.inputBox.mentionPicker}>
              <PromptInputButton
                aria-label={t.inputBox.mentionPicker}
                data-testid="mention-button"
                disabled={composerLocked}
                onClick={openMentions}
              >
                <AtSignIcon className="size-4" />
              </PromptInputButton>
            </Tooltip>
            <AddAttachmentsButton
              onOpen={openMentions}
              className="px-2!"
              disabled={composerLocked}
              uploadLimits={uploadLimits}
            />
            <VoiceInputButton
              disabled={composerLocked}
              listening={voiceListening}
              supported={voiceInputSupported}
              onToggle={toggleVoiceInput}
            />
            <Tooltip
              content={
                polishingInput
                  ? t.inputBox.inputPolishing
                  : inputPolishUndoAvailable
                    ? t.inputBox.inputPolishUndo
                    : t.inputBox.inputPolish
              }
            >
              <PromptInputButton
                aria-label={
                  inputPolishUndoAvailable
                    ? t.inputBox.inputPolishUndo
                    : t.inputBox.inputPolish
                }
                className="px-2!"
                data-testid="polish-input-button"
                disabled={inputPolishDisabled}
                onClick={
                  inputPolishUndoAvailable
                    ? handleUndoInputPolish
                    : handlePolishInput
                }
              >
                {polishingInput ? (
                  <Loader2Icon className="size-3 animate-spin" />
                ) : inputPolishUndoAvailable ? (
                  <Undo2Icon className="size-3" />
                ) : (
                  <SparklesIcon className="size-3" />
                )}
              </PromptInputButton>
            </Tooltip>
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
                <PromptInputActionMenuTrigger
                  className="max-w-28 gap-1! px-2! sm:max-w-none"
                  disabled={composerLocked}
                >
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
                    {!thinkingRequired && (
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
                    )}
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
            {knowledgeScopeControl}
            {supportReasoningEffort && context.mode !== "flash" && (
              <PromptInputActionMenu>
                <PromptInputActionMenuTrigger
                  className="hidden gap-1! px-2! sm:inline-flex"
                  disabled={composerLocked}
                >
                  <div className="text-xs font-normal">
                    {t.inputBox.reasoningEffort}:{" "}
                    {reasoningEffortLabel(effectiveReasoningEffort)}
                  </div>
                </PromptInputActionMenuTrigger>
                <PromptInputActionMenuContent className="w-70">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel className="text-muted-foreground text-xs">
                      {t.inputBox.reasoningEffort}
                    </DropdownMenuLabel>
                    <PromptInputActionMenu>
                      {reasoningEffortOptions.map((effort) => (
                        <PromptInputActionMenuItem
                          key={effort}
                          className={cn(
                            effectiveReasoningEffort === effort
                              ? "text-accent-foreground"
                              : "text-muted-foreground/65",
                          )}
                          onSelect={() => handleReasoningEffortSelect(effort)}
                        >
                          <div className="flex flex-col gap-2">
                            <div className="flex items-center gap-1 font-bold">
                              {reasoningEffortLabel(effort)}
                            </div>
                            {reasoningEffortDescription(effort) && (
                              <div className="pl-2 text-xs">
                                {reasoningEffortDescription(effort)}
                              </div>
                            )}
                          </div>
                          {effectiveReasoningEffort === effort ? (
                            <CheckIcon className="ml-auto size-4" />
                          ) : (
                            <div className="ml-auto size-4" />
                          )}
                        </PromptInputActionMenuItem>
                      ))}
                    </PromptInputActionMenu>
                  </DropdownMenuGroup>
                </PromptInputActionMenuContent>
              </PromptInputActionMenu>
            )}
          </PromptInputTools>
          <PromptInputTools className="min-w-0 justify-end">
            {goalObjectiveCounter && (
              <span
                aria-label={t.inputBox.goalLengthCounter
                  .replace("{length}", () =>
                    String(goalObjectiveCounter.length),
                  )
                  .replace("{max}", () => String(goalObjectiveCounter.max))}
                className={cn(
                  "shrink-0 text-xs tabular-nums",
                  goalObjectiveCounter.overLimit
                    ? "text-destructive font-medium"
                    : "text-muted-foreground",
                )}
                data-testid="goal-length-counter"
              >
                {goalObjectiveCounter.length}/{goalObjectiveCounter.max}
              </span>
            )}
            <ModelPicker
              open={modelDialogOpen}
              onOpenChange={setModelDialogOpen}
            >
              <ModelPickerTrigger asChild>
                <PromptInputButton
                  className="max-w-40 min-w-0 sm:max-w-56"
                  disabled={composerLocked}
                >
                  <div className="flex min-w-0 flex-col text-left">
                    <span className="flex-1 truncate text-left text-xs font-normal">
                      {selectedModel?.display_name}
                    </span>
                  </div>
                </PromptInputButton>
              </ModelPickerTrigger>
              <ModelPickerContent
                open={modelDialogOpen}
                models={models}
                selectedModelName={selectedModel?.name}
                onModelSelect={handleModelSelect}
              />
            </ModelPicker>
            <PromptInputSubmit
              className="rounded-full"
              disabled={
                composerLocked ||
                stopDenied ||
                sendDenied ||
                (status !== "streaming" && conversationReferencesUnavailable)
              }
              variant="outline"
              status={status}
              // A bare disabled square reads as a broken composer; explain
              // the permission boundary (native title, since a Radix
              // tooltip won't fire on a disabled button). Spread
              // conditionally: an explicitly-undefined aria-label would
              // clobber PromptInputSubmit's default aria-label="Submit"
              // and strip the submit control's accessible name.
              {...(stopDenied
                ? {
                    "aria-label": t.inputBox.stopStreamingUnavailable,
                    title: t.inputBox.stopStreamingUnavailable,
                  }
                : sendDenied
                  ? {
                      "aria-label": t.inputBox.startTurnUnavailable,
                      title: t.inputBox.startTurnUnavailable,
                    }
                  : {})}
              onClick={(e) => {
                if (status === "streaming") {
                  e.preventDefault();
                  handleStopStreaming();
                }
              }}
            />
          </PromptInputTools>
        </PromptInputFooter>
      </PromptInput>
      {!isWelcomeMode && (
        <div className="bg-background absolute right-0 -bottom-[17px] left-0 z-0 h-4"></div>
      )}

      {isWelcomeMode &&
        searchParams.get("mode") !== "skill" &&
        !showCommandSuggestions &&
        !showMentions && (
          <div className="flex items-center justify-center pt-2">
            <SuggestionList onSelectPlaceholder={onSelectPlaceholder} />
          </div>
        )}

      <p
        className={cn(
          "text-muted-foreground/67 z-10 px-4 text-center text-xs leading-4",
          !isWelcomeMode && "absolute top-full right-0 left-0",
        )}
      >
        {t.inputBox.disclaimer}
      </p>

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

function VoiceInputButton({
  disabled,
  listening,
  supported,
  onToggle,
}: {
  disabled?: boolean;
  listening: boolean;
  supported: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const tooltipContent = !supported
    ? t.inputBox.voiceInputUnsupported
    : listening
      ? t.inputBox.voiceInputListening
      : t.inputBox.voiceInputStart;
  const label = listening
    ? t.inputBox.voiceInputStopLabel
    : t.inputBox.voiceInputStartLabel;

  return (
    <Tooltip content={<span className="block max-w-72">{tooltipContent}</span>}>
      <PromptInputButton
        aria-label={label}
        aria-pressed={listening}
        className={cn(
          "px-2!",
          listening && "text-primary bg-primary/10 hover:bg-primary/15",
        )}
        data-testid="voice-input-button"
        disabled={(disabled ?? false) || !supported}
        onClick={onToggle}
      >
        {listening ? (
          <SquareIcon className="size-3 fill-current" />
        ) : (
          <MicIcon className="size-3" />
        )}
      </PromptInputButton>
    </Tooltip>
  );
}

function SuggestionList({
  onSelectPlaceholder,
}: {
  onSelectPlaceholder: (newText: string) => void;
}) {
  const { t } = useI18n();
  const { textInput } = usePromptInputController();
  const handleSuggestionClick = useCallback(
    (prompt: string | undefined) => {
      if (!prompt) return;
      textInput.setInput(prompt);
      onSelectPlaceholder(prompt);
    },
    [textInput, onSelectPlaceholder],
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
  disabled,
  uploadLimits,
  onOpen,
}: {
  onOpen?: () => void;
  className?: string;
  disabled?: boolean;
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
        disabled={disabled}
        onClick={onOpen ?? (() => attachments.openFileDialog())}
      >
        <PaperclipIcon className="size-3" />
      </PromptInputButton>
    </Tooltip>
  );
}
