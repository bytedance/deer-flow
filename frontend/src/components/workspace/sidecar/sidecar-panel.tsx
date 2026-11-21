"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useQueryClient } from "@tanstack/react-query";
import {
  MessageSquareTextIcon,
  PaperclipIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { toast } from "sonner";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import {
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
  isArtifactRewriteClarification,
  type ArtifactSelectionEdit,
} from "@/core/artifacts/selection";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildHumanInputResponseText,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { useModels } from "@/core/models/hooks";
import {
  getResolvedMode,
  reasoningEffortForMode,
  resolveReasoningEffort,
} from "@/core/models/reasoning";
import type { Model } from "@/core/models/types";
import { useLocalSettings } from "@/core/settings";
import {
  buildParentConversationContext,
  buildReferenceMessageMetadata,
  buildSidecarContextPrompt,
  isSameSidecarContext,
} from "@/core/sidecar";
import { createSidecarThread } from "@/core/sidecar/api";
import {
  useDeleteThread,
  useThreadStream,
  type ThreadStreamOptions,
} from "@/core/threads/hooks";
import { useThreadInputMode } from "@/core/threads/use-thread-input-mode";
import {
  formatUploadSize,
  useUploadLimits,
  validateUploadLimits,
  type UploadLimits,
  type UploadLimitViolation,
} from "@/core/uploads";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { ComposerPromptInput } from "../composer-prompt-input";
import { InputModeMenu } from "../input-mode-menu";
import { MessageList, MESSAGE_LIST_DEFAULT_PADDING_BOTTOM } from "../messages";
import { useThread as useParentThread } from "../messages/context";
import {
  ModelPicker,
  ModelPickerContent,
  ModelPickerTrigger,
} from "../model-picker-content";
import { Tooltip } from "../tooltip";

import { ArtifactRewriteReview } from "./artifact-rewrite-review";
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

function promptMessageFiles(message: PromptInputMessage) {
  return message.files.flatMap((file) =>
    file.file instanceof File ? [file.file] : [],
  );
}

export function SidecarPanel({ className }: { className?: string }) {
  const { t } = useI18n();
  const { user } = useAuth();
  const canDeleteThreads = hasPermission(user, PERMISSIONS.THREADS_DELETE);
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
    artifactEdit: ArtifactSelectionEdit | null;
    onSent: () => void;
    // Settles the composer's submit with the queued send's outcome.
    resolve: () => void;
    reject: (error: unknown) => void;
  } | null>(null);
  const selectedModel = useMemo(() => {
    if (models.length === 0) {
      return undefined;
    }
    return (
      models.find((model) => model.name === sidecar.context.model_name) ??
      models[0]
    );
  }, [models, sidecar.context.model_name]);

  const queryClient = useQueryClient();
  const {
    mode,
    context,
    pending: modePending,
    changeMode,
    prepareThread,
    threadMetadata,
    retryMode,
  } = useThreadInputMode({
    threadId: sidecar.sidecarThreadId,
    preferred: sidecar.context,
    isMock: sidecar.isMock,
    restoring: sidecar.restoring,
    userId: user?.id,
  });
  const textOnly = mode === "chat";
  const filesBlocked = textOnly || modePending;
  const { data: uploadLimits } = useUploadLimits(
    filesBlocked ? "" : (sidecar.sidecarThreadId ?? sidecar.parentThreadId),
  );

  const {
    thread,
    sendMessage,
    isUploading,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
    approvalRequests,
    hasPendingApproval,
    submitHitlApproval,
    waitingForInputRunIds,
  } = useThreadStream({
    threadId: sidecar.sidecarThreadId ?? undefined,
    displayThreadId: sidecar.sidecarThreadId ?? undefined,
    context,
    isMock: sidecar.isMock,
    onStart: (createdThreadId) => {
      sidecar.setSidecarThreadId(createdThreadId);
    },
    restInterrupts: threadMetadata.data?.interrupts,
    restInterruptsLoading: threadMetadata.isLoading,
    restInterruptsError: threadMetadata.isError,
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
  const tokenUsageInlineMode = tokenUsageEnabled
    ? localSettings.tokenUsage.inlineMode
    : "off";
  const disabled =
    modePending ||
    (!hasSidecarThread && !hasPendingReferences) ||
    thread.isLoading ||
    creatingThread ||
    Boolean(queuedSubmit) ||
    isUploading ||
    (hasSidecarThread && isHistoryLoading) ||
    (sidecar.isMock ?? false) ||
    hasPendingApproval ||
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";

  useEffect(() => {
    if (models.length === 0) {
      return;
    }

    const currentModel = models.find(
      (model) => model.name === context.model_name,
    );
    const fallbackModel = currentModel ?? models[0]!;
    const nextModelName = fallbackModel.name;
    const nextMode = getResolvedMode(context.mode, fallbackModel);
    const modeChanged = context.mode !== nextMode;
    const nextEffort = modeChanged
      ? reasoningEffortForMode(nextMode, fallbackModel)
      : resolveReasoningEffort(fallbackModel, context.reasoning_effort);

    if (
      context.model_name === nextModelName &&
      !modeChanged &&
      nextEffort === context.reasoning_effort
    ) {
      return;
    }

    changeMode(
      nextMode,
      () =>
        sidecar.setContext({
          ...context,
          model_name: nextModelName,
          mode: nextMode,
          reasoning_effort: nextEffort,
        }),
      true,
    );
  }, [changeMode, context, models, sidecar]);

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
      const nextMode = getResolvedMode(context.mode, model);
      const modeChanged = context.mode !== nextMode;
      changeMode(nextMode, () =>
        sidecar.setContext({
          ...context,
          model_name: modelName,
          mode: nextMode,
          reasoning_effort: modeChanged
            ? reasoningEffortForMode(nextMode, model)
            : resolveReasoningEffort(model, context.reasoning_effort),
        }),
      );
      setModelDialogOpen(false);
    },
    [changeMode, context, models, sidecar],
  );

  const handleModeSelect = useCallback(
    (mode: SidecarInputMode) => {
      const nextMode = getResolvedMode(mode, selectedModel);
      changeMode(nextMode, () =>
        sidecar.setContext({
          ...context,
          mode: nextMode,
          reasoning_effort: reasoningEffortForMode(nextMode, selectedModel),
        }),
      );
    },
    [changeMode, context, sidecar, selectedModel],
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
          mode,
          context: references.map((reference) => reference.context),
        });
        queryClient.setQueryData(
          ["thread", "metadata", created.thread_id, false],
          created,
        );
        sidecar.setSidecarThreadId(created.thread_id);
        return created.thread_id;
      } finally {
        setCreatingThread(false);
      }
    },
    [mode, queryClient, sidecar, t.sidecar.noContext],
  );

  const submitToSidecarThread = useCallback(
    async (
      threadId: string,
      message: PromptInputMessage,
      references: SidecarReference[],
      artifactEdit: ArtifactSelectionEdit | null,
      onSent?: () => void,
      answer?: HumanInputResponse,
    ) => {
      if ((answer || textOnly) && message.files.length)
        throw new Error(t.inputBox.chatTextOnly);
      if (!answer) await prepareThread();
      const referencedContexts = references.map(
        (reference) => reference.context,
      );
      const contexts = artifactEdit
        ? [
            artifactEdit.context,
            ...referencedContexts.filter(
              (context) => !isSameSidecarContext(context, artifactEdit.context),
            ),
          ]
        : referencedContexts;
      const parentConversation = buildParentConversationContext(
        parentThread.messages,
      );
      let hiddenContextPrompt =
        contexts.length > 0 || parentConversation.length > 0
          ? buildSidecarContextPrompt(contexts, { parentConversation })
          : null;
      if (artifactEdit) {
        hiddenContextPrompt = `${hiddenContextPrompt ?? ""}\n\nRewrite only the first referenced passage (the artifact selection) according to the user's request. Other references provide context. Return the replacement text itself, without explanations or an enclosing code fence. Preserve surrounding Markdown structure when relevant. The user will review the replacement and apply it to the original file's draft; do not write or recreate that file in this side chat.`;
      }
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
          ...(artifactEdit ? { artifact_selection_edit: artifactEdit.id } : {}),
          ...(contexts.length > 0
            ? buildReferenceMessageMetadata(contexts)
            : {}),
          ...(answer
            ? { hide_from_ui: true, human_input_response: answer }
            : {}),
        },
        onSent,
      });
    },
    [
      parentThread.messages,
      prepareThread,
      sendMessage,
      sidecar.parentThreadId,
      t.inputBox.chatTextOnly,
      textOnly,
    ],
  );

  const handleSubmitHumanInput = useCallback(
    async (request: HumanInputRequest, response: HumanInputResponse) => {
      if (!sidecar.sidecarThreadId) {
        return false;
      }

      let sent = false;
      const pendingReferences = [...sidecar.activeReferences];
      const edit = sidecar.artifactEdit;
      await submitToSidecarThread(
        sidecar.sidecarThreadId,
        {
          text: buildHumanInputResponseText(request, response),
          files: [],
        },
        pendingReferences,
        edit &&
          isArtifactRewriteClarification(
            thread.messages,
            edit.id,
            request.request_id,
          )
          ? edit
          : null,
        () => {
          sent = true;
          if (pendingReferences.length > 0) {
            sidecar.clearActiveReferences();
          }
        },
        response,
      );
      return sent;
    },
    [sidecar, submitToSidecarThread, thread.messages],
  );

  const handleSubmitApproval = useCallback(
    (
      request: (typeof approvalRequests)[number],
      responses: Parameters<typeof submitHitlApproval>[2],
    ) =>
      sidecar.sidecarThreadId
        ? submitHitlApproval(sidecar.sidecarThreadId, request, responses)
        : false,
    [sidecar.sidecarThreadId, submitHitlApproval],
  );

  useEffect(() => {
    if (
      !queuedSubmit ||
      !sidecar.sidecarThreadId ||
      modePending ||
      thread.isLoading
    ) {
      return;
    }

    const nextSubmit = queuedSubmit;
    setQueuedSubmit(null);
    void submitToSidecarThread(
      sidecar.sidecarThreadId,
      nextSubmit.message,
      nextSubmit.references,
      nextSubmit.artifactEdit,
      nextSubmit.onSent,
    ).then(nextSubmit.resolve, nextSubmit.reject);
  }, [
    queuedSubmit,
    modePending,
    sidecar,
    sidecar.sidecarThreadId,
    submitToSidecarThread,
    thread.isLoading,
  ]);

  const handleSubmit = useCallback(
    async (message: PromptInputMessage, event: FormEvent<HTMLFormElement>) => {
      const text = message.text.trim();
      const files = promptMessageFiles(message);
      if (modePending) throw new Error("thread-mode-changed");
      if ((!text && message.files.length === 0) || disabled) {
        return;
      }
      const uploadValidation = validateUploadLimits([], files, uploadLimits);
      if (uploadValidation.violations.length > 0) {
        reportUploadLimitViolations(uploadValidation.violations);
        return Promise.reject(new Error("Attachment limits exceeded."));
      }

      const pendingReferences = [...sidecar.activeReferences];
      const edit = sidecar.artifactEdit;
      const submitter = (event.nativeEvent as SubmitEvent).submitter;
      const artifactEdit =
        submitter?.getAttribute("value") === "rewrite" ? edit : null;
      const onSent = () => {
        if (pendingReferences.length > 0) sidecar.clearActiveReferences();
        if (edit && !artifactEdit) sidecar.clearArtifactEdit(edit.id);
      };
      try {
        if (!sidecar.sidecarThreadId) {
          await ensureSidecarThread(pendingReferences);
          // The first send waits for the new thread to reach the stream hook.
          // Settle with that send so the composer clears only once it is sent.
          await new Promise<void>((resolve, reject) => {
            setQueuedSubmit({
              message,
              references: pendingReferences,
              artifactEdit,
              onSent,
              resolve,
              reject,
            });
          });
          return;
        }

        await submitToSidecarThread(
          sidecar.sidecarThreadId,
          message,
          pendingReferences,
          artifactEdit,
          onSent,
        );
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : t.sidecar.sendFailed,
        );
        // Reject so PromptInput keeps the draft and attachments for a retry.
        throw error;
      }
    },
    [
      disabled,
      ensureSidecarThread,
      modePending,
      reportUploadLimitViolations,
      sidecar,
      submitToSidecarThread,
      t.sidecar.sendFailed,
      uploadLimits,
    ],
  );

  const clearSelectedReferences = useCallback(() => {
    sidecar.clearArtifactEdit();
    sidecar.clearActiveReferences();
  }, [sidecar]);

  const discardDraftAndClose = useCallback(() => {
    clearSelectedReferences();
    sidecar.setSidecarThreadId(null);
    sidecar.close();
  }, [clearSelectedReferences, sidecar]);

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
        {hasSidecarThread && canDeleteThreads && (
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
        )}
        <Tooltip content={t.common.close}>
          <Button
            aria-label={t.common.close}
            className="text-muted-foreground hover:text-foreground"
            data-testid="sidecar-close-button"
            size="icon-sm"
            variant="ghost"
            onClick={() =>
              hasSidecarThread ? sidecar.close() : discardDraftAndClose()
            }
          >
            <XIcon />
          </Button>
        </Tooltip>
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
            approvalRequests={approvalRequests}
            approvalMetadataLoading={
              hasPendingApproval && approvalRequests.length === 0
            }
            approvalMetadataError={
              hasPendingApproval &&
              approvalRequests.length === 0 &&
              threadMetadata.isError
            }
            onReloadApprovalMetadata={() => threadMetadata.refetch()}
            waitingForInputRunIds={waitingForInputRunIds}
            onSubmitApproval={handleSubmitApproval}
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

      {sidecar.artifactEdit && (
        <ArtifactRewriteReview
          key={sidecar.artifactEdit.id}
          edit={sidecar.artifactEdit}
          messages={thread.messages}
          disabled={disabled || !!thread.error || parentThread.isLoading}
          onCancel={() => sidecar.clearArtifactEdit()}
        />
      )}
      <div className="bg-background/95 shrink-0 px-3 pt-3 pb-4 sm:px-4">
        <PromptInputProvider key={sidecar.parentThreadId}>
          <ComposerPromptInput
            filesBlocked={filesBlocked}
            textOnly={textOnly}
            className="bg-background/85 rounded-2xl backdrop-blur-sm *:data-[slot='input-group']:rounded-2xl"
            disabled={disabled}
            multiple
            onSubmit={handleSubmit}
          >
            <PromptInputHeader className="flex-wrap px-3 pt-3 pb-0 empty:hidden">
              {!filesBlocked && (
                <PromptInputAttachments className="contents p-0">
                  {(attachment) => (
                    <div className="max-w-48">
                      <PromptInputAttachment data={attachment} />
                    </div>
                  )}
                </PromptInputAttachments>
              )}
              {sidecar.activeReferences.length > 0 && (
                <ReferenceAttachmentSummary
                  references={sidecar.activeReferences}
                  testId="sidecar-reference-attachment"
                  onClear={clearSelectedReferences}
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
                {!filesBlocked && (
                  <SidecarAddAttachmentsButton uploadLimits={uploadLimits} />
                )}
                <InputModeMenu
                  className="max-w-20"
                  disabled={
                    modePending ||
                    creatingThread ||
                    !!queuedSubmit ||
                    isUploading
                  }
                  runActive={thread.isLoading}
                  onRetry={retryMode}
                  mode={mode}
                  model={selectedModel}
                  onSelect={handleModeSelect}
                />
              </PromptInputTools>
              <PromptInputTools className="min-w-0 justify-end">
                <SidecarModelSelector
                  className="max-w-40 min-w-0 sm:max-w-56 @max-[240px]:hidden"
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
                {sidecar.artifactEdit && (
                  <Button
                    type="submit"
                    value="rewrite"
                    size="sm"
                    disabled={disabled}
                  >
                    {t.artifactSelection.rewrite}
                  </Button>
                )}
              </PromptInputTools>
            </PromptInputFooter>
          </ComposerPromptInput>
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

function SidecarModelSelector({
  className,
  models,
  open,
  selectedModel,
  onModelSelect,
  onOpenChange,
}: {
  className?: string;
  models: Model[];
  open: boolean;
  selectedModel?: Model;
  onModelSelect: (modelName: string) => void;
  onOpenChange: (open: boolean) => void;
}) {
  if (!selectedModel) {
    return null;
  }

  return (
    <ModelPicker open={open} onOpenChange={onOpenChange}>
      <ModelPickerTrigger asChild>
        <PromptInputButton className={cn("min-w-0 px-2!", className)}>
          <div className="flex min-w-0 flex-col text-left">
            <span className="flex-1 truncate text-left text-xs font-normal">
              {selectedModel.display_name}
            </span>
          </div>
        </PromptInputButton>
      </ModelPickerTrigger>
      <ModelPickerContent
        open={open}
        models={models}
        selectedModelName={selectedModel.name}
        onModelSelect={onModelSelect}
      />
    </ModelPicker>
  );
}
