"use client";

import type { ChatStatus } from "ai";
import {
  CheckIcon,
  GraduationCapIcon,
  KeyboardIcon,
  LightbulbIcon,
  MicIcon,
  PaperclipIcon,
  PlusIcon,
  RocketIcon,
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
} from "react";
import { toast } from "sonner";

import {
  appendTranscriptionToInput,
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
  PromptInputSpeechButton,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputAttachments,
  usePromptInputController,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
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
import { fetchGateway } from "@/core/api";
import type { AudioInputConfigResponse } from "@/core/audio/api";
import {
  useAudioInputConfig,
  useAudioTranscription,
} from "@/core/audio/hooks";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import type { AgentThreadContext, KnowledgeBaseSelection } from "@/core/threads";
import { textOfMessage } from "@/core/threads/utils";
import {
  promptInputFilePartToFile,
  type PromptInputFilePart,
} from "@/core/uploads";
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

import { KnowledgeBaseSelector } from "./knowledge-base-selector";
import { useThread } from "./messages/context";
import { ModeHoverGuide } from "./mode-hover-guide";
import { Tooltip } from "./tooltip";

type InputMode = "flash" | "thinking" | "pro" | "ultra";
const AUDIO_FILE_ACCEPT = "audio/*";
const DEFAULT_AUDIO_LOCALES = ["zh-CN", "en-US"] as const;
const DEFAULT_AUDIO_LOCALE = "en-US";

export type InputSource = "text" | "microphone" | "audio-file";

type InputSourceLabels = Record<InputSource, string>;
type AudioPromptInputFile = PromptInputFilePart & { id: string };
type AudioInputAvailability = Pick<
  AudioInputConfigResponse,
  | "enabled"
  | "microphone_enabled"
  | "file_transcription_enabled"
  | "default_locale"
  | "supported_locales"
>;

export function getInputSourceLabel(
  inputSource: InputSource,
  labels: InputSourceLabels,
): string {
  return labels[inputSource];
}

export function isAudioPromptInputFile(
  filePart: Pick<PromptInputFilePart, "file" | "mediaType">,
): boolean {
  const mediaType =
    (typeof filePart.mediaType === "string" && filePart.mediaType) ||
    (filePart.file instanceof File ? filePart.file.type : "");
  return mediaType.startsWith("audio/");
}

export function getNextPendingAudioAttachment<T extends AudioPromptInputFile>(
  files: T[],
  attemptedIds: Set<string>,
): T | undefined {
  return files.find(
    (file) => isAudioPromptInputFile(file) && !attemptedIds.has(file.id),
  );
}

export function getAvailableInputSources(
  audioInputConfig?: AudioInputAvailability | null,
): InputSource[] {
  const sources: InputSource[] = ["text"];
  if (audioInputConfig?.enabled && audioInputConfig.file_transcription_enabled) {
    sources.push("audio-file");
  }
  if (audioInputConfig?.enabled && audioInputConfig.microphone_enabled) {
    sources.push("microphone");
  }
  return sources;
}

export function getSafeInputSource(
  inputSource: InputSource,
  availableInputSources: readonly InputSource[],
): InputSource {
  return availableInputSources.includes(inputSource)
    ? inputSource
    : (availableInputSources[0] ?? "text");
}

export function resolveAudioLocale(
  locale: string | undefined,
  supportedLocales: readonly string[] = DEFAULT_AUDIO_LOCALES,
  fallbackLocale = DEFAULT_AUDIO_LOCALE,
): string {
  const normalizedSupportedLocales =
    supportedLocales.length > 0 ? [...supportedLocales] : [fallbackLocale];

  if (locale) {
    const lowerLocale = locale.toLowerCase();
    const exactMatch = normalizedSupportedLocales.find(
      (candidate) => candidate.toLowerCase() === lowerLocale,
    );
    if (exactMatch) {
      return exactMatch;
    }

    const localePrefix = lowerLocale.split("-")[0];
    const prefixMatch = normalizedSupportedLocales.find((candidate) => {
      const lowerCandidate = candidate.toLowerCase();
      return (
        lowerCandidate === localePrefix ||
        lowerCandidate.startsWith(`${localePrefix}-`)
      );
    });
    if (prefixMatch) {
      return prefixMatch;
    }
  }

  const fallbackMatch = normalizedSupportedLocales.find(
    (candidate) => candidate.toLowerCase() === fallbackLocale.toLowerCase(),
  );
  return fallbackMatch ?? normalizedSupportedLocales[0] ?? fallbackLocale;
}

export function getInputSourcePlaceholder({
  inputSource,
  defaultPlaceholder,
  microphonePlaceholder,
  audioFilePlaceholder,
  microphoneUnsupportedPlaceholder,
  microphoneSupported,
}: {
  inputSource: InputSource;
  defaultPlaceholder: string;
  microphonePlaceholder: string;
  audioFilePlaceholder: string;
  microphoneUnsupportedPlaceholder: string;
  microphoneSupported: boolean;
}): string {
  if (inputSource === "text") {
    return defaultPlaceholder;
  }
  if (inputSource === "audio-file") {
    return audioFilePlaceholder;
  }

  return microphoneSupported
    ? microphonePlaceholder
    : microphoneUnsupportedPlaceholder;
}

function getResolvedMode(
  mode: InputMode | undefined,
  supportsThinking: boolean,
): InputMode {
  if (!supportsThinking && mode === "thinking") {
    return "flash";
  }
  if (mode) {
    return mode;
  }
  return supportsThinking ? "pro" : "flash";
}

export function InputBox({
  className,
  disabled,
  autoFocus,
  status = "ready",
  context,
  extraHeader,
  isNewThread,
  threadId,
  initialValue,
  onContextChange,
  onFollowupsVisibilityChange,
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
    knowledge_base_selection?: KnowledgeBaseSelection;
  };
  extraHeader?: React.ReactNode;
  isNewThread?: boolean;
  threadId: string;
  initialValue?: string;
  onContextChange?: (
    context: Omit<
      AgentThreadContext,
      "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
    > & {
      mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
      reasoning_effort?: "minimal" | "low" | "medium" | "high";
      knowledge_base_selection?: KnowledgeBaseSelection;
    },
  ) => void;
  onFollowupsVisibilityChange?: (visible: boolean) => void;
  onSubmit?: (message: PromptInputMessage) => void;
  onStop?: () => void;
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const { models } = useModels();
  const { data: audioInputConfig } = useAudioInputConfig();
  const { thread, isMock } = useThread();
  const { attachments, textInput } = usePromptInputController();
  const audioTranscription = useAudioTranscription(threadId);
  const promptRootRef = useRef<HTMLDivElement | null>(null);
  const attemptedAudioAttachmentIdsRef = useRef<Set<string>>(new Set());

  const [followups, setFollowups] = useState<string[]>([]);
  const [followupsHidden, setFollowupsHidden] = useState(false);
  const [followupsLoading, setFollowupsLoading] = useState(false);
  const lastGeneratedForAiIdRef = useRef<string | null>(null);
  const wasStreamingRef = useRef(false);
  const messagesRef = useRef(thread.messages);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingSuggestion, setPendingSuggestion] = useState<string | null>(
    null,
  );
  const [inputSource, setInputSource] = useState<InputSource>("text");
  const [microphoneSupported, setMicrophoneSupported] = useState(false);
  const [audioTranscriptionError, setAudioTranscriptionError] = useState<
    string | null
  >(null);
  const [failedAudioAttachmentId, setFailedAudioAttachmentId] = useState<
    string | null
  >(null);
  const [activeAudioAttachmentId, setActiveAudioAttachmentId] = useState<
    string | null
  >(null);

  useEffect(() => {
    if (typeof window === "undefined" || typeof navigator === "undefined") {
      return;
    }

    setMicrophoneSupported(
      typeof window.MediaRecorder !== "undefined" &&
        typeof navigator.mediaDevices?.getUserMedia === "function",
    );
  }, []);

  const availableInputSources = useMemo(
    () => getAvailableInputSources(audioInputConfig),
    [audioInputConfig],
  );

  const activeInputSource = getSafeInputSource(
    inputSource,
    availableInputSources,
  );

  useEffect(() => {
    if (activeInputSource !== inputSource) {
      setInputSource(activeInputSource);
    }
  }, [activeInputSource, inputSource]);

  const audioLocale = useMemo(
    () =>
      resolveAudioLocale(
        typeof navigator !== "undefined" ? navigator.language : undefined,
        audioInputConfig?.supported_locales,
        audioInputConfig?.default_locale ?? DEFAULT_AUDIO_LOCALE,
      ),
    [audioInputConfig],
  );

  const microphoneInputEnabled = availableInputSources.includes("microphone");
  const audioFileInputEnabled = availableInputSources.includes("audio-file");

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

  const handleKnowledgeBaseSelectionChange = useCallback(
    (selection: { enabled: boolean; selected_ids: string[] }) => {
      onContextChange?.({
        ...context,
        knowledge_base_selection: selection,
      });
    },
    [onContextChange, context],
  );

  const transcribeAudioAttachment = useCallback(
    async (attachment: AudioPromptInputFile) => {
      attemptedAudioAttachmentIdsRef.current.add(attachment.id);
      setActiveAudioAttachmentId(attachment.id);
      setAudioTranscriptionError(null);
      setFailedAudioAttachmentId(null);

      try {
        const file = await promptInputFilePartToFile(attachment);
        if (!(file instanceof File)) {
          throw new Error(t.inputBox.audioFileTranscriptionFailed);
        }

        const result = await audioTranscription.mutateAsync({
          file,
          locale: audioLocale,
          attachOriginal: false,
        });
        const nextText = appendTranscriptionToInput(
          textInput.value ?? "",
          result.transcript,
        );
        textInput.setInput(nextText);
        attachments.remove(attachment.id);
      } catch (error) {
        const message =
          error instanceof Error && error.message.trim().length > 0
            ? error.message
            : t.inputBox.audioFileTranscriptionFailed;
        setAudioTranscriptionError(message);
        setFailedAudioAttachmentId(attachment.id);
        toast.error(message);
      } finally {
        setActiveAudioAttachmentId(null);
      }
    },
    [
      attachments,
      audioLocale,
      audioTranscription,
      t.inputBox.audioFileTranscriptionFailed,
      textInput,
    ],
  );

  const handleSubmit = useCallback(
    async (message: PromptInputMessage) => {
      if (status === "streaming") {
        onStop?.();
        return;
      }
      if (audioTranscription.isPending) {
        return;
      }
      if (!message.text) {
        return;
      }
      setFollowups([]);
      setFollowupsHidden(false);
      setFollowupsLoading(false);

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
        setTimeout(() => onSubmit?.(message), 0);
        return;
      }

      onSubmit?.(message);
    },
    [
      context,
      onContextChange,
      onSubmit,
      onStop,
      audioTranscription.isPending,
      resolvedModelName,
      selectedModel?.supports_thinking,
      status,
    ],
  );

  const inputSourceLabels = useMemo(
    () => ({
      text: t.inputBox.textInput,
      microphone: t.inputBox.microphoneInput,
      "audio-file": t.inputBox.audioFileInput,
    }),
    [t],
  );

  const inputSourceLabel = getInputSourceLabel(
    activeInputSource,
    inputSourceLabels,
  );

  const inputPlaceholder = getInputSourcePlaceholder({
    inputSource: activeInputSource,
    defaultPlaceholder: t.inputBox.placeholder,
    microphonePlaceholder: t.inputBox.microphonePlaceholder,
    audioFilePlaceholder: t.inputBox.audioFilePlaceholder,
    microphoneUnsupportedPlaceholder:
      t.inputBox.microphoneUnsupportedPlaceholder,
    microphoneSupported,
  });

  const promptInputAccept =
    activeInputSource === "audio-file" ? AUDIO_FILE_ACCEPT : undefined;

  const microphoneButtonDisabled =
    disabled ||
    status === "streaming" ||
    !microphoneInputEnabled ||
    !microphoneSupported
      ? true
      : undefined;

  const failedAudioAttachment = useMemo(
    () =>
      attachments.files.find(
        (file): file is AudioPromptInputFile =>
          file.id === failedAudioAttachmentId && isAudioPromptInputFile(file),
      ),
    [attachments.files, failedAudioAttachmentId],
  );

  const audioFileStatusMessage =
    audioTranscription.isPending
      ? t.inputBox.audioFileTranscribing
      : audioTranscriptionError ?? t.inputBox.audioFileInputDescription;

  const requestFormSubmit = useCallback(() => {
    const form = promptRootRef.current?.querySelector("form");
    form?.requestSubmit();
  }, []);

  const retryAudioTranscription = useCallback(() => {
    if (!failedAudioAttachment || audioTranscription.isPending) {
      return;
    }
    void transcribeAudioAttachment(failedAudioAttachment);
  }, [audioTranscription.isPending, failedAudioAttachment, transcribeAudioAttachment]);

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

  const showFollowups =
    !disabled &&
    !isNewThread &&
    !followupsHidden &&
    (followupsLoading || followups.length > 0);

  const followupsVisibilityChangeRef = useRef(onFollowupsVisibilityChange);

  useEffect(() => {
    followupsVisibilityChangeRef.current = onFollowupsVisibilityChange;
  }, [onFollowupsVisibilityChange]);

  useEffect(() => {
    followupsVisibilityChangeRef.current?.(showFollowups);
  }, [showFollowups]);

  useEffect(() => {
    messagesRef.current = thread.messages;
  }, [thread.messages]);

  useEffect(() => {
    const attachmentIds = new Set(attachments.files.map((file) => file.id));
    attemptedAudioAttachmentIdsRef.current = new Set(
      [...attemptedAudioAttachmentIdsRef.current].filter((id) =>
        attachmentIds.has(id),
      ),
    );
    if (failedAudioAttachmentId && !attachmentIds.has(failedAudioAttachmentId)) {
      setFailedAudioAttachmentId(null);
      setAudioTranscriptionError(null);
    }
    if (activeAudioAttachmentId && !attachmentIds.has(activeAudioAttachmentId)) {
      setActiveAudioAttachmentId(null);
    }
  }, [activeAudioAttachmentId, attachments.files, failedAudioAttachmentId]);

  useEffect(() => {
    if (
      activeInputSource !== "audio-file" ||
      disabled ||
      status === "streaming"
    ) {
      return;
    }
    if (audioTranscription.isPending || activeAudioAttachmentId) {
      return;
    }

    const nextAudioAttachment = getNextPendingAudioAttachment(
      attachments.files,
      attemptedAudioAttachmentIdsRef.current,
    );
    if (!nextAudioAttachment) {
      return;
    }

    void transcribeAudioAttachment(nextAudioAttachment);
  }, [
    activeAudioAttachmentId,
    activeInputSource,
    attachments.files,
    audioTranscription.isPending,
    disabled,
    status,
    transcribeAudioAttachment,
  ]);

  useEffect(() => {
    if (activeInputSource === "audio-file") {
      return;
    }
    setAudioTranscriptionError(null);
    setFailedAudioAttachmentId(null);
  }, [activeInputSource]);

  useEffect(() => {
    return () => followupsVisibilityChangeRef.current?.(false);
  }, []);

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
    lastGeneratedForAiIdRef.current = lastAiId;

    const recent = messagesRef.current
      .filter((m) => m.type === "human" || m.type === "ai")
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

    const controller = new AbortController();
    setFollowupsHidden(false);
    setFollowupsLoading(true);
    setFollowups([]);

    fetchGateway(`${getBackendBaseURL()}/api/threads/${threadId}/suggestions`, {
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
  }, [context.model_name, disabled, isMock, status, threadId]);

  return (
    <div ref={promptRootRef} className="relative flex flex-col gap-4">
      {showFollowups && (
        <div className="from-background/0 via-background/85 to-background/95 pointer-events-none flex items-center justify-center bg-gradient-to-b pt-4 pb-2">
          <div className="pointer-events-auto flex items-center gap-2">
            {followupsLoading ? (
              <div className="text-muted-foreground bg-background/80 rounded-full border px-4 py-2 text-xs backdrop-blur-sm">
                {t.inputBox.followupLoading}
              </div>
            ) : (
              <Suggestions className="min-h-16 w-fit items-start">
                {followups.map((s) => (
                  <Suggestion
                    key={s}
                    suggestion={s}
                    onClick={() => handleFollowupClick(s)}
                  />
                ))}
                <Button
                  aria-label={t.common.close}
                  className="text-muted-foreground cursor-pointer rounded-full px-3 text-xs font-normal"
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
      <PromptInput
        accept={promptInputAccept}
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
            placeholder={inputPlaceholder}
            autoFocus={autoFocus}
            defaultValue={initialValue}
          />
        </PromptInputBody>
        <PromptInputFooter className="flex">
          <PromptInputTools>
            <PromptInputActionMenu>
              <PromptInputActionMenuTrigger className="gap-1! px-2!">
                {activeInputSource === "text" ? (
                  <KeyboardIcon className="size-3" />
                ) : activeInputSource === "audio-file" ? (
                  <PaperclipIcon className="size-3" />
                ) : (
                  <MicIcon className="size-3" />
                )}
                <div className="text-xs font-normal">{inputSourceLabel}</div>
              </PromptInputActionMenuTrigger>
              <PromptInputActionMenuContent className="w-80">
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="text-muted-foreground text-xs">
                    {t.inputBox.inputSource}
                  </DropdownMenuLabel>
                  <PromptInputActionMenu>
                    <PromptInputActionMenuItem
                      className={cn(
                        activeInputSource === "text"
                          ? "text-accent-foreground"
                          : "text-muted-foreground/65",
                      )}
                      onSelect={() => setInputSource("text")}
                    >
                      <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-1 font-bold">
                          <KeyboardIcon
                            className={cn(
                              "mr-2 size-4",
                              activeInputSource === "text" &&
                                "text-accent-foreground",
                            )}
                          />
                          {t.inputBox.textInput}
                        </div>
                        <div className="pl-7 text-xs">
                          {t.inputBox.textInputDescription}
                        </div>
                      </div>
                      {activeInputSource === "text" ? (
                        <CheckIcon className="ml-auto size-4" />
                      ) : (
                        <div className="ml-auto size-4" />
                      )}
                    </PromptInputActionMenuItem>
                    {audioFileInputEnabled && (
                      <PromptInputActionMenuItem
                        className={cn(
                          activeInputSource === "audio-file"
                            ? "text-accent-foreground"
                            : "text-muted-foreground/65",
                        )}
                        onSelect={() => setInputSource("audio-file")}
                      >
                        <div className="flex flex-col gap-2">
                          <div className="flex items-center gap-1 font-bold">
                            <PaperclipIcon
                              className={cn(
                                "mr-2 size-4",
                                activeInputSource === "audio-file" &&
                                  "text-accent-foreground",
                              )}
                            />
                            {t.inputBox.audioFileInput}
                          </div>
                          <div className="pl-7 text-xs">
                            {t.inputBox.audioFileInputDescription}
                          </div>
                        </div>
                        {activeInputSource === "audio-file" ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </PromptInputActionMenuItem>
                    )}
                    {microphoneInputEnabled && (
                      <PromptInputActionMenuItem
                        className={cn(
                          activeInputSource === "microphone"
                            ? "text-accent-foreground"
                            : "text-muted-foreground/65",
                        )}
                        onSelect={() => setInputSource("microphone")}
                      >
                        <div className="flex flex-col gap-2">
                          <div className="flex items-center gap-1 font-bold">
                            <MicIcon
                              className={cn(
                                "mr-2 size-4",
                                activeInputSource === "microphone" &&
                                  "text-accent-foreground",
                              )}
                            />
                            {t.inputBox.microphoneInput}
                          </div>
                          <div className="pl-7 text-xs">
                            {microphoneSupported
                              ? t.inputBox.microphoneInputDescription
                              : t.inputBox.microphoneUnsupported}
                          </div>
                        </div>
                        {activeInputSource === "microphone" ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </PromptInputActionMenuItem>
                    )}
                  </PromptInputActionMenu>
                </DropdownMenuGroup>
              </PromptInputActionMenuContent>
            </PromptInputActionMenu>
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
            {activeInputSource === "microphone" && microphoneInputEnabled && (
              <Tooltip
                content={
                  microphoneSupported
                    ? t.inputBox.microphoneInputDescription
                    : t.inputBox.microphoneUnsupported
                }
              >
                <PromptInputSpeechButton
                  aria-label={t.inputBox.microphoneInput}
                  className="px-2!"
                  autoStart
                  threadId={threadId}
                  disabled={microphoneButtonDisabled}
                  language={audioLocale}
                />
              </Tooltip>
            )}
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
                <PromptInputActionMenuTrigger className="gap-1! px-2!">
                  <div>
                    {context.mode === "flash" && <ZapIcon className="size-3" />}
                    {context.mode === "thinking" && (
                      <LightbulbIcon className="size-3" />
                    )}
                    {context.mode === "pro" && (
                      <GraduationCapIcon className="size-3" />
                    )}
                    {context.mode === "ultra" && (
                      <RocketIcon className="size-3" />
                    )}
                  </div>
                  <div className="text-xs font-normal">
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
                          <RocketIcon className="mr-2 size-4" />
                          <div>{t.inputBox.ultraMode}</div>
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
                <PromptInputActionMenuTrigger className="gap-1! px-2!">
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
            <KnowledgeBaseSelector
              selection={context.knowledge_base_selection}
              onSelectionChange={handleKnowledgeBaseSelectionChange}
            />
          </PromptInputTools>
          <PromptInputTools>
            <ModelSelector
              open={modelDialogOpen}
              onOpenChange={setModelDialogOpen}
            >
              <ModelSelectorTrigger asChild>
                <PromptInputButton>
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
              disabled={Boolean(disabled) || audioTranscription.isPending}
              variant="outline"
              status={status}
            />
          </PromptInputTools>
        </PromptInputFooter>
        {activeInputSource === "audio-file" && audioFileInputEnabled && (
          <div className="flex items-center justify-between gap-2 px-4 pb-2 text-[11px]">
            <span
              className={cn(
                "text-muted-foreground",
                audioTranscriptionError ? "text-destructive" : "",
              )}
            >
              {audioFileStatusMessage}
            </span>
            {failedAudioAttachment && (
              <Button
                className="h-auto px-2 py-1 text-[11px]"
                size="sm"
                type="button"
                variant="ghost"
                onClick={retryAudioTranscription}
              >
                {t.inputBox.audioFileRetry}
              </Button>
            )}
          </div>
        )}
        {activeInputSource === "microphone" &&
          microphoneInputEnabled &&
          !microphoneSupported && (
          <div className="text-muted-foreground px-4 pb-2 text-[11px]">
            {t.inputBox.microphoneUnsupported}
          </div>
        )}
        {!isNewThread && (
          <div className="bg-background absolute right-0 -bottom-[17px] left-0 z-0 h-4"></div>
        )}
      </PromptInput>

      {isNewThread && searchParams.get("mode") !== "skill" && (
        <div className="flex items-center justify-center">
          <SuggestionList />
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
    <Suggestions className="w-fit items-start py-1">
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
