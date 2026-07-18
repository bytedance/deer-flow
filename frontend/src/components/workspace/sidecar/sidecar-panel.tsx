"use client";

import type { Message } from "@langchain/langgraph-sdk";
import {
  CheckIcon,
  GraduationCapIcon,
  LightbulbIcon,
  MessageSquareTextIcon,
  PaperclipIcon,
  RocketIcon,
  Trash2Icon,
  XIcon,
  ZapIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
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
  PromptInputProvider,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputAttachments,
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
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildHumanInputResponseText,
  hasOpenHumanInputRequest,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { isHiddenFromUIMessage } from "@/core/messages/utils";
import { useModels } from "@/core/models/hooks";
import type { Model } from "@/core/models/types";
import { useLocalSettings } from "@/core/settings";
import {
  buildParentConversationContext,
  buildReferenceMessageMetadata,
  buildSidecarContextPrompt,
} from "@/core/sidecar";
import { createSidecarThread } from "@/core/sidecar/api";
import {
  useDeleteThread,
  useThreadStream,
  type ThreadStreamOptions,
} from "@/core/threads/hooks";
import {
  formatUploadSize,
  useUploadLimits,
  validateUploadLimits,
  type UploadLimits,
  type UploadLimitViolation,
} from "@/core/uploads";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "../../ai-elements/model-selector";
import { MessageList, MESSAGE_LIST_DEFAULT_PADDING_BOTTOM } from "../messages";
import { useThread as useParentThread } from "../messages/context";
import { ModeHoverGuide } from "../mode-hover-guide";
import { Tooltip } from "../tooltip";

import { type SidecarReference, useSidecar } from "./context";
import { ReferenceAttachmentSummary } from "./reference-attachments";

function buildHiddenSidecarContextMessage({
  prompt,
  parentThreadId,
}: {
  prompt: string;
  parentThreadId: string;
}): Message {
  return {
    type: "human",
    content: [{ type: "text", text: prompt }],
    additional_kwargs: {
      hide_from_ui: true,
      sidecar_context: true,
      parent_thread_id: parentThreadId,
    },
  } as Message;
}

type SidecarInputMode = NonNullable<ThreadStreamOptions["context"]["mode"]>;

function getResolvedMode(
  mode: ThreadStreamOptions["context"]["mode"],
  supportsThinking: boolean,
): SidecarInputMode {
  if (!supportsThinking && mode !== "flash") {
    return "flash";
  }
  if (mode) {
    return mode;
  }
  return supportsThinking ? "pro" : "flash";
}

function reasoningEffortForMode(mode: SidecarInputMode) {
  return mode === "ultra"
    ? "high"
    : mode === "pro"
      ? "medium"
      : mode === "thinking"
        ? "low"
        : "minimal";
}

function promptMessageFiles(message: PromptInputMessage) {
  return message.files.flatMap((file) =>
    file.file instanceof File ? [file.file] : [],
  );
}

export function SidecarPanel({ className }: { className?: string }) {
  const { t } = useI18n();
  const sidecar = useSidecar();
  const { thread: parentThread } = useParentThread();
  const [localSettings] = useLocalSettings();
  const { models, tokenUsageEnabled } = useModels();
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const [creatingThread, setCreatingThread] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const { mutateAsync: deleteThread, isPending: isDeleting } =
    useDeleteThread();
  const [queuedSubmit, setQueuedSubmit] = useState<{
    message: PromptInputMessage;
    references: SidecarReference[];
  } | null>(null);
  const { data: uploadLimits } = useUploadLimits(
    sidecar.sidecarThreadId ?? sidecar.parentThreadId,
  );

  const selectedModel = useMemo(() => {
    if (models.length === 0) {
      return undefined;
    }
    return (
      models.find((model) => model.name === sidecar.context.model_name) ??
      models[0]
    );
  }, [models, sidecar.context.model_name]);

  const supportThinking = selectedModel?.supports_thinking ?? false;

  const {
    thread,
    sendMessage,
    isUploading,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
  } = useThreadStream({
    threadId: sidecar.sidecarThreadId ?? undefined,
    displayThreadId: sidecar.sidecarThreadId ?? undefined,
    context: sidecar.context,
    isMock: sidecar.isMock,
    onStart: (createdThreadId) => {
      sidecar.setSidecarThreadId(createdThreadId);
    },
  });

  const referenceCountLabel = useMemo(() => {
    const count = sidecar.activeReferences.length;
    const template =
      count === 1
        ? t.sidecar.selectedTextFragment
        : t.sidecar.selectedTextFragments;
    return template.replace("{count}", String(count));
  }, [
    sidecar.activeReferences.length,
    t.sidecar.selectedTextFragment,
    t.sidecar.selectedTextFragments,
  ]);

  const hasPendingReferences = sidecar.activeReferences.length > 0;
  const hasSidecarThread = Boolean(sidecar.sidecarThreadId);
  const hasOpenHumanInputCard = useMemo(
    () =>
      hasOpenHumanInputRequest(
        thread.messages,
        (message) => !isHiddenFromUIMessage(message),
      ),
    [thread.messages],
  );
  const tokenUsageInlineMode = tokenUsageEnabled
    ? localSettings.tokenUsage.inlineMode
    : "off";
  const disabled =
    (!hasSidecarThread && !hasPendingReferences) ||
    thread.isLoading ||
    creatingThread ||
    Boolean(queuedSubmit) ||
    isUploading ||
    hasOpenHumanInputCard ||
    (hasSidecarThread && isHistoryLoading) ||
    (sidecar.isMock ?? false) ||
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";

  useEffect(() => {
    if (models.length === 0) {
      return;
    }

    const currentModel = models.find(
      (model) => model.name === sidecar.context.model_name,
    );
    const fallbackModel = currentModel ?? models[0]!;
    const nextModelName = fallbackModel.name;
    const nextMode = getResolvedMode(
      sidecar.context.mode,
      fallbackModel.supports_thinking ?? false,
    );
    const modeChanged = sidecar.context.mode !== nextMode;

    if (sidecar.context.model_name === nextModelName && !modeChanged) {
      return;
    }

    sidecar.setContext({
      ...sidecar.context,
      model_name: nextModelName,
      mode: nextMode,
      reasoning_effort: modeChanged
        ? reasoningEffortForMode(nextMode)
        : sidecar.context.reasoning_effort,
    });
  }, [models, sidecar]);

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

  const handleModelSelect = useCallback(
    (modelName: string) => {
      const model = models.find((candidate) => candidate.name === modelName);
      if (!model) {
        return;
      }
      const nextMode = getResolvedMode(
        sidecar.context.mode,
        model.supports_thinking ?? false,
      );
      const modeChanged = sidecar.context.mode !== nextMode;
      sidecar.setContext({
        ...sidecar.context,
        model_name: modelName,
        mode: nextMode,
        reasoning_effort: modeChanged
          ? reasoningEffortForMode(nextMode)
          : sidecar.context.reasoning_effort,
      });
      setModelDialogOpen(false);
    },
    [models, sidecar],
  );

  const handleModeSelect = useCallback(
    (mode: SidecarInputMode) => {
      const nextMode = getResolvedMode(mode, supportThinking);
      sidecar.setContext({
        ...sidecar.context,
        mode: nextMode,
        reasoning_effort: reasoningEffortForMode(nextMode),
      });
    },
    [sidecar, supportThinking],
  );

  const ensureSidecarThread = useCallback(
    async (references: SidecarReference[]) => {
      if (sidecar.sidecarThreadId) {
        return sidecar.sidecarThreadId;
      }
      const restoredThreadId = await sidecar.restoreSidecarThread();
      if (restoredThreadId) {
        return restoredThreadId;
      }
      if (references.length === 0) {
        throw new Error(t.sidecar.noContext);
      }
      setCreatingThread(true);
      try {
        const created = await createSidecarThread({
          parentThreadId: sidecar.parentThreadId,
          context: references.map((reference) => reference.context),
        });
        sidecar.setSidecarThreadId(created.thread_id);
        return created.thread_id;
      } finally {
        setCreatingThread(false);
      }
    },
    [sidecar, t.sidecar.noContext],
  );

  const submitToSidecarThread = useCallback(
    async (
      threadId: string,
      message: PromptInputMessage,
      references: SidecarReference[],
      onSent?: () => void,
      additionalKwargs?: Record<string, unknown>,
    ) => {
      const contexts = references.map((reference) => reference.context);
      const parentConversation = buildParentConversationContext(
        parentThread.messages,
      );
      const hiddenContextPrompt =
        contexts.length > 0 || parentConversation.length > 0
          ? buildSidecarContextPrompt(contexts, { parentConversation })
          : null;
      await sendMessage(threadId, message, undefined, {
        additionalInputMessages: hiddenContextPrompt
          ? [
              buildHiddenSidecarContextMessage({
                prompt: hiddenContextPrompt,
                parentThreadId: sidecar.parentThreadId,
              }),
            ]
          : [],
        additionalKwargs: {
          sidecar_visible_message: true,
          ...(contexts.length > 0
            ? buildReferenceMessageMetadata(contexts)
            : {}),
          ...additionalKwargs,
        },
        onSent,
      });
    },
    [parentThread.messages, sendMessage, sidecar.parentThreadId],
  );

  const handleSubmitHumanInput = useCallback(
    async (request: HumanInputRequest, response: HumanInputResponse) => {
      if (!sidecar.sidecarThreadId) {
        return false;
      }

      let sent = false;
      const pendingReferences = [...sidecar.activeReferences];
      await submitToSidecarThread(
        sidecar.sidecarThreadId,
        {
          text: buildHumanInputResponseText(request, response),
          files: [],
        },
        pendingReferences,
        () => {
          sent = true;
          if (pendingReferences.length > 0) {
            sidecar.clearActiveReferences();
          }
        },
        {
          hide_from_ui: true,
          human_input_response: response,
        },
      );
      return sent;
    },
    [sidecar, submitToSidecarThread],
  );

  useEffect(() => {
    if (!queuedSubmit || !sidecar.sidecarThreadId || thread.isLoading) {
      return;
    }

    const nextSubmit = queuedSubmit;
    setQueuedSubmit(null);
    void submitToSidecarThread(
      sidecar.sidecarThreadId,
      nextSubmit.message,
      nextSubmit.references,
      // Clear references only once the send genuinely proceeds; a send dropped
      // by the in-flight guard leaves them attached instead of losing them.
      () => {
        if (nextSubmit.references.length > 0) {
          sidecar.clearActiveReferences();
        }
      },
    ).catch((error) => {
      toast.error(
        error instanceof Error ? error.message : t.sidecar.sendFailed,
      );
    });
  }, [
    queuedSubmit,
    sidecar,
    sidecar.sidecarThreadId,
    submitToSidecarThread,
    t.sidecar.sendFailed,
    thread.isLoading,
  ]);

  const handleSubmit = useCallback(
    async (message: PromptInputMessage) => {
      const text = message.text.trim();
      const files = promptMessageFiles(message);
      if ((!text && message.files.length === 0) || disabled) {
        return;
      }
      const uploadValidation = validateUploadLimits([], files, uploadLimits);
      if (uploadValidation.violations.length > 0) {
        reportUploadLimitViolations(uploadValidation.violations);
        return Promise.reject(new Error("Attachment limits exceeded."));
      }

      const pendingReferences = [...sidecar.activeReferences];
      try {
        if (!sidecar.sidecarThreadId) {
          await ensureSidecarThread(pendingReferences);
          setQueuedSubmit({ message, references: pendingReferences });
          return;
        }

        await submitToSidecarThread(
          sidecar.sidecarThreadId,
          message,
          pendingReferences,
          () => {
            if (pendingReferences.length > 0) {
              sidecar.clearActiveReferences();
            }
          },
        );
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : t.sidecar.sendFailed,
        );
      }
    },
    [
      disabled,
      ensureSidecarThread,
      reportUploadLimitViolations,
      sidecar,
      submitToSidecarThread,
      t.sidecar.sendFailed,
      uploadLimits,
    ],
  );

  const discardDraftAndClose = useCallback(() => {
    sidecar.clearActiveReferences();
    sidecar.setSidecarThreadId(null);
    sidecar.close();
  }, [sidecar]);

  const handleDelete = useCallback(async () => {
    const threadId = sidecar.sidecarThreadId;
    // Guard: the trash button only opens this dialog once a thread exists, so a
    // missing id here means the draft was cleared underneath us — just close.
    if (!threadId) {
      discardDraftAndClose();
      setDeleteDialogOpen(false);
      return;
    }
    try {
      await deleteThread({ threadId });
      discardDraftAndClose();
      setDeleteDialogOpen(false);
      toast.success(t.sidecar.deleteSuccess);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.sidecar.deleteFailed,
      );
    }
  }, [
    deleteThread,
    discardDraftAndClose,
    sidecar.sidecarThreadId,
    t.sidecar.deleteFailed,
    t.sidecar.deleteSuccess,
  ]);

  return (
    <div
      className={cn("flex size-full min-h-0 flex-col", className)}
      data-testid="sidecar-panel"
    >
      <header className="border-border/70 flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <MessageSquareTextIcon className="text-muted-foreground size-4" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{t.sidecar.title}</div>
          <div className="text-muted-foreground truncate text-xs">
            {sidecar.activeReferences.length > 0
              ? referenceCountLabel
              : sidecar.sidecarThreadId
                ? t.sidecar.continuing
                : t.sidecar.noContext}
          </div>
        </div>
        {hasSidecarThread ? (
          <Tooltip content={t.sidecar.delete}>
            <Button
              aria-label={t.sidecar.delete}
              className="text-muted-foreground hover:text-destructive"
              data-testid="sidecar-delete-button"
              size="icon-sm"
              variant="ghost"
              onClick={() => setDeleteDialogOpen(true)}
            >
              <Trash2Icon />
            </Button>
          </Tooltip>
        ) : (
          // No conversation yet — nothing to delete, so this just discards the
          // draft and closes the panel. A plain X (no confirm) keeps it light.
          <Tooltip content={t.common.close}>
            <Button
              aria-label={t.common.close}
              className="text-muted-foreground hover:text-foreground"
              data-testid="sidecar-close-button"
              size="icon-sm"
              variant="ghost"
              onClick={() => discardDraftAndClose()}
            >
              <XIcon />
            </Button>
          </Tooltip>
        )}
      </header>

      <div className="min-h-0 flex-1">
        {sidecar.sidecarThreadId ? (
          <MessageList
            className="size-full"
            testId="sidecar-message-list"
            threadId={sidecar.sidecarThreadId}
            thread={thread}
            paddingBottom={MESSAGE_LIST_DEFAULT_PADDING_BOTTOM / 2}
            hasMoreHistory={hasMoreHistory}
            loadMoreHistory={loadMoreHistory}
            isHistoryLoading={isHistoryLoading}
            tokenUsageInlineMode={tokenUsageInlineMode}
            sidecarSurface
            initialScroll="instant"
            resizeScroll="instant"
            onSubmitHumanInput={
              sidecar.isMock || env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
                ? undefined
                : handleSubmitHumanInput
            }
          />
        ) : (
          <ConversationEmptyState
            icon={<MessageSquareTextIcon className="size-5" />}
            title={t.sidecar.emptyTitle}
            description={t.sidecar.emptyDescription}
          />
        )}
      </div>

      <div className="bg-background/95 shrink-0 px-3 pt-3 pb-4 sm:px-4">
        <PromptInputProvider key={sidecar.parentThreadId}>
          <PromptInput
            className="bg-background/85 rounded-2xl backdrop-blur-sm *:data-[slot='input-group']:rounded-2xl"
            disabled={disabled}
            multiple
            onSubmit={handleSubmit}
          >
            <PromptInputHeader className="flex-wrap px-3 pt-3 pb-0 empty:hidden">
              <PromptInputAttachments className="contents p-0">
                {(attachment) => (
                  <div className="max-w-48">
                    <PromptInputAttachment data={attachment} />
                  </div>
                )}
              </PromptInputAttachments>
              {sidecar.activeReferences.length > 0 && (
                <ReferenceAttachmentSummary
                  references={sidecar.activeReferences}
                  testId="sidecar-reference-attachment"
                  onClear={() => sidecar.clearActiveReferences()}
                />
              )}
            </PromptInputHeader>
            <PromptInputBody>
              <PromptInputTextarea
                className="max-h-36 min-h-16 text-sm"
                disabled={disabled}
                placeholder={t.sidecar.placeholder}
              />
            </PromptInputBody>
            <PromptInputFooter className="@container flex flex-nowrap gap-2">
              <PromptInputTools className="min-w-0 flex-1 flex-nowrap overflow-hidden">
                <SidecarAddAttachmentsButton uploadLimits={uploadLimits} />
                <SidecarModeMenu
                  context={sidecar.context}
                  supportThinking={supportThinking}
                  onModeSelect={handleModeSelect}
                />
              </PromptInputTools>
              <PromptInputTools className="min-w-0 justify-end">
                <SidecarModelSelector
                  className="max-w-40 min-w-0 sm:max-w-56 @max-[240px]:hidden"
                  context={sidecar.context}
                  models={models}
                  open={modelDialogOpen}
                  selectedModel={selectedModel}
                  onModelSelect={handleModelSelect}
                  onOpenChange={setModelDialogOpen}
                />
                <Tooltip content={t.sidecar.send}>
                  <PromptInputSubmit
                    className="rounded-full"
                    disabled={disabled}
                    status={
                      thread.isLoading || creatingThread || queuedSubmit
                        ? "submitted"
                        : "ready"
                    }
                    variant="outline"
                  />
                </Tooltip>
              </PromptInputTools>
            </PromptInputFooter>
          </PromptInput>
        </PromptInputProvider>
      </div>

      <Dialog
        open={deleteDialogOpen}
        onOpenChange={(open) => {
          // While the delete is in flight the only way out is the (disabled)
          // Cancel button, so ignore overlay/Esc/close-button dismissals that
          // would otherwise hide the dialog and imply the delete was cancelled.
          if (!open && isDeleting) {
            return;
          }
          setDeleteDialogOpen(open);
        }}
      >
        <DialogContent
          showCloseButton={!isDeleting}
          onEscapeKeyDown={(event) => {
            if (isDeleting) {
              event.preventDefault();
            }
          }}
          onInteractOutside={(event) => {
            if (isDeleting) {
              event.preventDefault();
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>{t.sidecar.delete}</DialogTitle>
            <DialogDescription>{t.sidecar.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              disabled={isDeleting}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              data-testid="sidecar-delete-confirm-button"
              onClick={() => void handleDelete()}
              disabled={isDeleting}
            >
              {isDeleting ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SidecarAddAttachmentsButton({
  uploadLimits,
}: {
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
        className="px-2!"
        data-testid="sidecar-add-attachments-button"
        onClick={() => attachments.openFileDialog()}
      >
        <PaperclipIcon className="size-3" />
      </PromptInputButton>
    </Tooltip>
  );
}

function SidecarModeMenu({
  context,
  supportThinking,
  onModeSelect,
}: {
  context: ThreadStreamOptions["context"];
  supportThinking: boolean;
  onModeSelect: (mode: SidecarInputMode) => void;
}) {
  const { t } = useI18n();
  const mode = getResolvedMode(context.mode, supportThinking);

  return (
    <PromptInputActionMenu>
      <ModeHoverGuide mode={mode}>
        <PromptInputActionMenuTrigger className="max-w-20 min-w-0 gap-1! px-2!">
          <div>
            {mode === "flash" && <ZapIcon className="size-3" />}
            {mode === "thinking" && <LightbulbIcon className="size-3" />}
            {mode === "pro" && <GraduationCapIcon className="size-3" />}
            {mode === "ultra" && (
              <RocketIcon className="size-3 text-[#dabb5e]" />
            )}
          </div>
          <div
            className={cn(
              "truncate text-xs font-normal",
              mode === "ultra" && "golden-text",
            )}
          >
            {(mode === "flash" && t.inputBox.flashMode) ||
              (mode === "thinking" && t.inputBox.reasoningMode) ||
              (mode === "pro" && t.inputBox.proMode) ||
              (mode === "ultra" && t.inputBox.ultraMode)}
          </div>
        </PromptInputActionMenuTrigger>
      </ModeHoverGuide>
      <PromptInputActionMenuContent className="w-80">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-muted-foreground text-xs">
            {t.inputBox.mode}
          </DropdownMenuLabel>
          <PromptInputActionMenuItem
            className={cn(
              mode === "flash"
                ? "text-accent-foreground"
                : "text-muted-foreground/65",
            )}
            onSelect={() => onModeSelect("flash")}
          >
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-1 font-bold">
                <ZapIcon
                  className={cn(
                    "mr-2 size-4",
                    mode === "flash" && "text-accent-foreground",
                  )}
                />
                {t.inputBox.flashMode}
              </div>
              <div className="pl-7 text-xs">
                {t.inputBox.flashModeDescription}
              </div>
            </div>
            {mode === "flash" ? (
              <CheckIcon className="ml-auto size-4" />
            ) : (
              <div className="ml-auto size-4" />
            )}
          </PromptInputActionMenuItem>
          {supportThinking && (
            <PromptInputActionMenuItem
              className={cn(
                mode === "thinking"
                  ? "text-accent-foreground"
                  : "text-muted-foreground/65",
              )}
              onSelect={() => onModeSelect("thinking")}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1 font-bold">
                  <LightbulbIcon
                    className={cn(
                      "mr-2 size-4",
                      mode === "thinking" && "text-accent-foreground",
                    )}
                  />
                  {t.inputBox.reasoningMode}
                </div>
                <div className="pl-7 text-xs">
                  {t.inputBox.reasoningModeDescription}
                </div>
              </div>
              {mode === "thinking" ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </PromptInputActionMenuItem>
          )}
          <PromptInputActionMenuItem
            className={cn(
              mode === "pro"
                ? "text-accent-foreground"
                : "text-muted-foreground/65",
            )}
            onSelect={() => onModeSelect("pro")}
          >
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-1 font-bold">
                <GraduationCapIcon
                  className={cn(
                    "mr-2 size-4",
                    mode === "pro" && "text-accent-foreground",
                  )}
                />
                {t.inputBox.proMode}
              </div>
              <div className="pl-7 text-xs">
                {t.inputBox.proModeDescription}
              </div>
            </div>
            {mode === "pro" ? (
              <CheckIcon className="ml-auto size-4" />
            ) : (
              <div className="ml-auto size-4" />
            )}
          </PromptInputActionMenuItem>
          <PromptInputActionMenuItem
            className={cn(
              mode === "ultra"
                ? "text-accent-foreground"
                : "text-muted-foreground/65",
            )}
            onSelect={() => onModeSelect("ultra")}
          >
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-1 font-bold">
                <RocketIcon
                  className={cn(
                    "mr-2 size-4",
                    mode === "ultra" && "text-[#dabb5e]",
                  )}
                />
                <div className={cn(mode === "ultra" && "golden-text")}>
                  {t.inputBox.ultraMode}
                </div>
              </div>
              <div className="pl-7 text-xs">
                {t.inputBox.ultraModeDescription}
              </div>
            </div>
            {mode === "ultra" ? (
              <CheckIcon className="ml-auto size-4" />
            ) : (
              <div className="ml-auto size-4" />
            )}
          </PromptInputActionMenuItem>
        </DropdownMenuGroup>
      </PromptInputActionMenuContent>
    </PromptInputActionMenu>
  );
}

function SidecarModelSelector({
  className,
  context,
  models,
  open,
  selectedModel,
  onModelSelect,
  onOpenChange,
}: {
  className?: string;
  context: ThreadStreamOptions["context"];
  models: Model[];
  open: boolean;
  selectedModel?: Model;
  onModelSelect: (modelName: string) => void;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();

  if (!selectedModel) {
    return null;
  }

  return (
    <ModelSelector open={open} onOpenChange={onOpenChange}>
      <ModelSelectorTrigger asChild>
        <PromptInputButton className={cn("min-w-0 px-2!", className)}>
          <div className="flex min-w-0 flex-col items-start text-left">
            <ModelSelectorName className="truncate text-xs font-normal">
              {selectedModel.display_name}
            </ModelSelectorName>
          </div>
        </PromptInputButton>
      </ModelSelectorTrigger>
      <ModelSelectorContent>
        <ModelSelectorInput placeholder={t.inputBox.searchModels} />
        <ModelSelectorList>
          {models.map((model) => (
            <ModelSelectorItem
              key={model.name}
              value={model.name}
              onSelect={() => onModelSelect(model.name)}
            >
              <div className="flex min-w-0 flex-1 flex-col">
                <ModelSelectorName>{model.display_name}</ModelSelectorName>
                <span className="text-muted-foreground truncate text-[10px]">
                  {model.model}
                </span>
              </div>
              {model.name === context.model_name ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </ModelSelectorItem>
          ))}
        </ModelSelectorList>
      </ModelSelectorContent>
    </ModelSelector>
  );
}
