import type { Message } from "@langchain/langgraph-sdk";
import {
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  FileIcon,
  Loader2Icon,
  PencilIcon,
  RotateCcwIcon,
  XIcon,
} from "lucide-react";
import { memo, useEffect, useMemo, useState, type ImgHTMLAttributes } from "react";
import rehypeKatex from "rehype-katex";

import { Loader } from "@/components/ai-elements/loader";
import {
  Message as AIElementMessage,
  MessageContent as AIElementMessageContent,
  MessageResponse as AIElementMessageResponse,
  MessageToolbar,
} from "@/components/ai-elements/message";
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import { Task, TaskTrigger } from "@/components/ai-elements/task";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { resolveArtifactURL } from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import {
  extractContentFromMessage,
  extractReasoningContentFromMessage,
  isEditableHumanMessage,
  isRegeneratableMessage,
  parseUploadedFiles,
  resolveThreadIdForMessageActions,
  stripUploadedFilesTag,
  type FileInMessage,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { humanMessagePlugins } from "@/core/streamdown";
import type { AssistantVersion } from "@/core/threads";
import { cn } from "@/lib/utils";

import { CopyButton } from "../copy-button";
import { Tooltip } from "../tooltip";

import { useThread } from "./context";
import { MarkdownContent } from "./markdown-content";

function resolveMessageFiles(message: Message, rawContent: string) {
  const files = message.additional_kwargs?.files;
  if (!Array.isArray(files) || files.length === 0) {
    if (rawContent.includes("<uploaded_files>")) {
      return parseUploadedFiles(rawContent);
    }
    return null;
  }
  return files as FileInMessage[];
}

function getEditableMessageText(message: Message) {
  return stripUploadedFilesTag(extractContentFromMessage(message));
}

export function MessageListItem({
  className,
  threadId,
  message,
  isLoading,
}: {
  className?: string;
  threadId: string;
  message: Message;
  isLoading?: boolean;
}) {
  const { t } = useI18n();
  const actionThreadId = resolveThreadIdForMessageActions(threadId);
  const {
    thread,
    editHumanMessage,
    regenerateTurn,
    selectAssistantVersion,
    isThreadStreaming,
  } = useThread();
  const isHuman = message.type === "human";
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(() => getEditableMessageText(message));

  useEffect(() => {
    if (!isEditing) {
      setDraft(getEditableMessageText(message));
    }
  }, [isEditing, message]);

  const assistantVersions = useMemo<AssistantVersion[]>(() => {
    if (!message.id || message.type !== "ai") {
      return [];
    }
    return thread.values.assistant_versions?.[message.id] ?? [];
  }, [message.id, message.type, thread.values.assistant_versions]);

  const activeVersionIndex = useMemo(() => {
    if (!message.id || assistantVersions.length === 0) {
      return 0;
    }
    const activeVersionId = thread.values.active_version_map?.[message.id];
    const index = assistantVersions.findIndex(
      (version) => version.id === activeVersionId,
    );
    return index >= 0 ? index : assistantVersions.length - 1;
  }, [assistantVersions, message.id, thread.values.active_version_map]);

  const canEdit = isEditableHumanMessage(message) && !isThreadStreaming && !isLoading;
  const canRegenerate =
    !isThreadStreaming &&
    !isLoading &&
    !!message.id &&
    isRegeneratableMessage(thread.messages, message.id);
  const isSaveDisabled = !draft.trim() || draft.trim() === getEditableMessageText(message).trim();

  const handleSave = async () => {
    if (!message.id) {
      return;
    }
    try {
      await editHumanMessage(actionThreadId, message.id, draft);
      setIsEditing(false);
    } catch {
      // The hook already shows a toast.
    }
  };

  const handleRegenerate = () => {
    if (!message.id) {
      return;
    }
    void regenerateTurn(actionThreadId, message.id).catch(() => undefined);
  };

  const handleSelectVersion = (offset: number) => {
    if (!message.id || assistantVersions.length <= 1) {
      return;
    }
    const nextIndex =
      (activeVersionIndex + offset + assistantVersions.length) %
      assistantVersions.length;
    const nextVersion = assistantVersions[nextIndex];
    if (!nextVersion) {
      return;
    }
    void selectAssistantVersion(actionThreadId, message.id, nextVersion.id).catch(
      () => undefined,
    );
  };

  return (
    <AIElementMessage
      className={cn("group/conversation-message relative w-full", className)}
      from={isHuman ? "user" : "assistant"}
    >
      <MessageContent
        className={isHuman ? "w-fit" : "w-full"}
        threadId={threadId}
        message={message}
        isLoading={isLoading}
        isEditing={isEditing}
        draft={draft}
        onDraftChange={setDraft}
        onCancelEdit={() => {
          setDraft(getEditableMessageText(message));
          setIsEditing(false);
        }}
        onSaveEdit={handleSave}
        isSaveDisabled={isSaveDisabled}
        assistantVersionState={
          !isHuman && assistantVersions.length > 1
            ? {
                activeIndex: activeVersionIndex,
                total: assistantVersions.length,
                onPrevious: () => handleSelectVersion(-1),
                onNext: () => handleSelectVersion(1),
                disabled: Boolean(isThreadStreaming || isLoading),
              }
            : undefined
        }
      />
      {!isLoading && !isEditing && (
        <MessageToolbar
          className={cn(
            isHuman ? "-bottom-9 justify-end" : "-bottom-8",
            "absolute right-0 left-0 z-20 opacity-0 transition-opacity delay-200 duration-300 group-hover/conversation-message:opacity-100",
          )}
        >
          <div className="flex gap-1">
            <CopyButton
              clipboardData={
                extractContentFromMessage(message) ??
                extractReasoningContentFromMessage(message) ??
                ""
              }
            />
            {isHuman && (
              <Tooltip content={t.messageActions.edit}>
                <Button
                  size="icon-sm"
                  type="button"
                  variant="ghost"
                  disabled={!canEdit}
                  onClick={() => setIsEditing(true)}
                >
                  <PencilIcon size={12} />
                </Button>
              </Tooltip>
            )}
            <Tooltip content={t.messageActions.regenerate}>
              <Button
                size="icon-sm"
                type="button"
                variant="ghost"
                disabled={!canRegenerate}
                onClick={handleRegenerate}
              >
                <RotateCcwIcon size={12} />
              </Button>
            </Tooltip>
          </div>
        </MessageToolbar>
      )}
    </AIElementMessage>
  );
}

function MessageImage({
  src,
  alt,
  threadId,
  maxWidth = "90%",
  ...props
}: React.ImgHTMLAttributes<HTMLImageElement> & {
  threadId: string;
  maxWidth?: string;
}) {
  if (!src) return null;

  const imgClassName = cn("overflow-hidden rounded-lg", `max-w-[${maxWidth}]`);

  if (typeof src !== "string") {
    return <img className={imgClassName} src={src} alt={alt} {...props} />;
  }

  const url = src.startsWith("/mnt/") ? resolveArtifactURL(src, threadId) : src;

  return (
    <a href={url} target="_blank" rel="noopener noreferrer">
      <img className={imgClassName} src={url} alt={alt} {...props} />
    </a>
  );
}

function BaseMessageContent({
  className,
  threadId,
  message,
  isLoading = false,
}: {
  className?: string;
  threadId: string;
  message: Message;
  isLoading?: boolean;
}) {
  const rehypePlugins = useRehypeSplitWordsIntoSpans(isLoading);
  const isHuman = message.type === "human";
  const components = useMemo(
    () => ({
      img: (props: ImgHTMLAttributes<HTMLImageElement>) => (
        <MessageImage {...props} threadId={threadId} maxWidth="90%" />
      ),
    }),
    [threadId],
  );

  const rawContent = extractContentFromMessage(message);
  const reasoningContent = extractReasoningContentFromMessage(message);

  const files = useMemo(
    () => resolveMessageFiles(message, rawContent),
    [message, rawContent],
  );

  const contentToDisplay = useMemo(() => {
    if (isHuman) {
      return rawContent ? stripUploadedFilesTag(rawContent) : "";
    }
    return rawContent ?? "";
  }, [rawContent, isHuman]);

  const filesList =
    files && files.length > 0 && threadId ? (
      <RichFilesList files={files} threadId={threadId} />
    ) : null;

  if (message.additional_kwargs?.element === "task") {
    return (
      <AIElementMessageContent className={className}>
        <Task defaultOpen={false}>
          <TaskTrigger title="">
            <div className="text-muted-foreground flex w-full cursor-default items-center gap-2 text-sm select-none">
              <Loader className="size-4" />
              <span>{contentToDisplay}</span>
            </div>
          </TaskTrigger>
        </Task>
      </AIElementMessageContent>
    );
  }

  if (!isHuman && reasoningContent && !rawContent) {
    return (
      <AIElementMessageContent className={className}>
        <Reasoning isStreaming={isLoading}>
          <ReasoningTrigger />
          <ReasoningContent>{reasoningContent}</ReasoningContent>
        </Reasoning>
      </AIElementMessageContent>
    );
  }

  if (isHuman) {
    const messageResponse = contentToDisplay ? (
      <AIElementMessageResponse
        remarkPlugins={humanMessagePlugins.remarkPlugins}
        rehypePlugins={humanMessagePlugins.rehypePlugins}
        components={components}
      >
        {contentToDisplay}
      </AIElementMessageResponse>
    ) : null;
    return (
      <div className={cn("ml-auto flex flex-col gap-2", className)}>
        {filesList}
        {messageResponse && (
          <AIElementMessageContent className="w-fit">
            {messageResponse}
          </AIElementMessageContent>
        )}
      </div>
    );
  }

  return (
    <AIElementMessageContent className={className}>
      {filesList}
      <MarkdownContent
        content={contentToDisplay}
        isLoading={isLoading}
        rehypePlugins={[...rehypePlugins, [rehypeKatex, { output: "html" }]]}
        className="my-3"
        components={components}
      />
    </AIElementMessageContent>
  );
}

function MessageContent_({
  className,
  threadId,
  message,
  isLoading = false,
  isEditing = false,
  draft = "",
  onDraftChange,
  onCancelEdit,
  onSaveEdit,
  isSaveDisabled = false,
  assistantVersionState,
}: {
  className?: string;
  threadId: string;
  message: Message;
  isLoading?: boolean;
  isEditing?: boolean;
  draft?: string;
  onDraftChange?: (value: string) => void;
  onCancelEdit?: () => void;
  onSaveEdit?: () => void;
  isSaveDisabled?: boolean;
  assistantVersionState?: {
    activeIndex: number;
    total: number;
    onPrevious: () => void;
    onNext: () => void;
    disabled: boolean;
  };
}) {
  const { t } = useI18n();
  const rawContent = extractContentFromMessage(message);
  const files = useMemo(
    () => resolveMessageFiles(message, rawContent),
    [message, rawContent],
  );

  if (message.type === "human" && isEditing) {
    return (
      <div className={cn("ml-auto flex w-full max-w-(--container-width-sm) flex-col gap-2", className)}>
        {files && files.length > 0 && threadId ? (
          <RichFilesList files={files} threadId={threadId} />
        ) : null}
        <AIElementMessageContent className="w-fit min-w-80 max-w-full">
          <div className="flex flex-col gap-3">
            <Textarea
              value={draft}
              onChange={(event) => onDraftChange?.(event.target.value)}
              className="min-h-28 resize-y"
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={onCancelEdit}>
                <XIcon size={14} />
                {t.common.cancel}
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={onSaveEdit}
                disabled={isSaveDisabled}
              >
                <CheckIcon size={14} />
                {t.common.save}
              </Button>
            </div>
          </div>
        </AIElementMessageContent>
      </div>
    );
  }

  return (
    <div className="w-full">
      <BaseMessageContent
        className={className}
        threadId={threadId}
        message={message}
        isLoading={isLoading}
      />
      {message.type === "ai" && assistantVersionState && assistantVersionState.total > 1 && (
        <div className="text-muted-foreground mt-2 flex items-center justify-end gap-1 text-xs">
          <Tooltip content={t.messageActions.previousVersion}>
            <Button
              size="icon-sm"
              type="button"
              variant="ghost"
              disabled={assistantVersionState.disabled}
              onClick={assistantVersionState.onPrevious}
            >
              <ChevronLeftIcon size={14} />
            </Button>
          </Tooltip>
          <span className="min-w-20 text-center">
            {t.common.version} {assistantVersionState.activeIndex + 1}/
            {assistantVersionState.total}
          </span>
          <Tooltip content={t.messageActions.nextVersion}>
            <Button
              size="icon-sm"
              type="button"
              variant="ghost"
              disabled={assistantVersionState.disabled}
              onClick={assistantVersionState.onNext}
            >
              <ChevronRightIcon size={14} />
            </Button>
          </Tooltip>
        </div>
      )}
    </div>
  );
}

const MessageContent = memo(MessageContent_);

/**
 * Get file extension and check helpers
 */
const getFileExt = (filename: string) =>
  filename.split(".").pop()?.toLowerCase() ?? "";

const FILE_TYPE_MAP: Record<string, string> = {
  json: "JSON",
  csv: "CSV",
  txt: "TXT",
  md: "Markdown",
  py: "Python",
  js: "JavaScript",
  ts: "TypeScript",
  tsx: "TSX",
  jsx: "JSX",
  html: "HTML",
  css: "CSS",
  xml: "XML",
  yaml: "YAML",
  yml: "YAML",
  pdf: "PDF",
  png: "PNG",
  jpg: "JPG",
  jpeg: "JPEG",
  gif: "GIF",
  svg: "SVG",
  zip: "ZIP",
  tar: "TAR",
  gz: "GZ",
};

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"];

function getFileTypeLabel(filename: string): string {
  const ext = getFileExt(filename);
  return FILE_TYPE_MAP[ext] ?? (ext.toUpperCase() || "FILE");
}

function isImageFile(filename: string): boolean {
  return IMAGE_EXTENSIONS.includes(getFileExt(filename));
}

/**
 * Format bytes to human-readable size string
 */
function formatBytes(bytes: number): string {
  if (bytes === 0) return "—";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

/**
 * List of files from additional_kwargs.files (with optional upload status)
 */
function RichFilesList({
  files,
  threadId,
}: {
  files: FileInMessage[];
  threadId: string;
}) {
  if (files.length === 0) return null;
  return (
    <div className="mb-2 flex flex-wrap justify-end gap-2">
      {files.map((file, index) => (
        <RichFileCard
          key={`${file.filename}-${index}`}
          file={file}
          threadId={threadId}
        />
      ))}
    </div>
  );
}

/**
 * Single file card that handles FileInMessage (supports uploading state)
 */
function RichFileCard({
  file,
  threadId,
}: {
  file: FileInMessage;
  threadId: string;
}) {
  const { t } = useI18n();
  const isUploading = file.status === "uploading";
  const isImage = isImageFile(file.filename);

  if (isUploading) {
    return (
      <div className="bg-background border-border/40 flex max-w-50 min-w-30 flex-col gap-1 rounded-lg border p-3 opacity-60 shadow-sm">
        <div className="flex items-start gap-2">
          <Loader2Icon className="text-muted-foreground mt-0.5 size-4 shrink-0 animate-spin" />
          <span
            className="text-foreground truncate text-sm font-medium"
            title={file.filename}
          >
            {file.filename}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <Badge
            variant="secondary"
            className="rounded px-1.5 py-0.5 text-[10px] font-normal"
          >
            {getFileTypeLabel(file.filename)}
          </Badge>
          <span className="text-muted-foreground text-[10px]">
            {t.uploads.uploading}
          </span>
        </div>
      </div>
    );
  }

  if (!file.path) return null;

  const fileUrl = resolveArtifactURL(file.path, threadId);

  if (isImage) {
    return (
      <a
        href={fileUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="group border-border/40 relative block overflow-hidden rounded-lg border"
      >
        <img
          src={fileUrl}
          alt={file.filename}
          className="h-32 w-auto max-w-60 object-cover transition-transform group-hover:scale-105"
        />
      </a>
    );
  }

  return (
    <div className="bg-background border-border/40 flex max-w-50 min-w-30 flex-col gap-1 rounded-lg border p-3 shadow-sm">
      <div className="flex items-start gap-2">
        <FileIcon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
        <span
          className="text-foreground truncate text-sm font-medium"
          title={file.filename}
        >
          {file.filename}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <Badge
          variant="secondary"
          className="rounded px-1.5 py-0.5 text-[10px] font-normal"
        >
          {getFileTypeLabel(file.filename)}
        </Badge>
        <span className="text-muted-foreground text-[10px]">
          {formatBytes(file.size)}
        </span>
      </div>
    </div>
  );
}

