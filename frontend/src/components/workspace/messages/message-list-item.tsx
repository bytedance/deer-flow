import type { Message } from "@langchain/langgraph-sdk";
import { math } from "@streamdown/math";
import { CheckIcon, FileIcon, PencilIcon, RefreshCwIcon, XIcon } from "lucide-react";
import { memo, useCallback, useMemo, useState, type ImgHTMLAttributes } from "react";
import { useParams } from "react-router";

import {
  Message as AIElementMessage,
  MessageContent as AIElementMessageContent,
  MessageResponse as AIElementMessageResponse,
  MessageToolbar,
} from "@/components/ai-elements/message";
import { Badge } from "@/components/ui/badge";
import { resolveArtifactURL } from "@/core/artifacts/utils";
import { useArtifacts } from "@/components/workspace/artifacts";
import {
  extractContentFromMessage,
  extractReasoningContentFromMessage,
  parseUploadedFiles,
  type UploadedFile,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { humanMessagePlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { CopyButton } from "../copy-button";

import { MarkdownContent } from "./markdown-content";

export const MessageListItem = memo(function MessageListItem({
  className,
  message,
  isLoading = false,
  isRegenerating = false,
  pendingFileNames,
  onEdit,
  onRegenerate,
}: {
  className?: string;
  message: Message;
  isLoading?: boolean;
  isRegenerating?: boolean;
  pendingFileNames?: string[];
  onEdit?: (messageId: string, newContent: string) => void;
  onRegenerate?: (messageId: string, content: string) => void;
}) {
  const isHuman = message.type === "human";
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState("");
  const isBusy = isLoading ? true : isRegenerating;

  const handleStartEdit = useCallback(() => {
    const content = extractContentFromMessage(message) ?? "";
    setEditedContent(content);
    setIsEditing(true);
  }, [message]);

  const handleSaveEdit = useCallback(() => {
    if (onEdit && message.id) {
      onEdit(message.id, editedContent);
    }
    setIsEditing(false);
  }, [onEdit, message.id, editedContent]);

  const handleCancelEdit = useCallback(() => {
    setIsEditing(false);
    setEditedContent("");
  }, []);

  const handleRegenerate = useCallback(() => {
    if (onRegenerate && message.id) {
      const content = extractContentFromMessage(message) ?? "";
      onRegenerate(message.id, content);
    }
  }, [onRegenerate, message]);

  if (isEditing && isHuman) {
    return (
      <AIElementMessage
        className={cn("group/conversation-message relative w-full", className)}
        from="user"
      >
        <div className="ml-auto flex w-full flex-col gap-2">
          <textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            className="bg-muted text-foreground font-claude-user-body w-full rounded-lg border border-border p-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
            rows={4}
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={handleCancelEdit}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-all hover:bg-muted"
            >
              <XIcon className="size-3.5" />
              Cancel
            </button>
            <button
              onClick={handleSaveEdit}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-all hover:bg-primary/90"
            >
              <CheckIcon className="size-3.5" />
              Save & Regenerate
            </button>
          </div>
        </div>
      </AIElementMessage>
    );
  }

  return (
    <AIElementMessage
      className={cn("group/conversation-message relative w-full", className)}
      from={isHuman ? "user" : "assistant"}
    >
      <MessageContent
        className={isHuman ? "w-fit" : "w-full"}
        message={message}
        isLoading={isLoading}
        pendingFileNames={isHuman ? pendingFileNames : undefined}
      />
      <MessageToolbar
        className={cn(
          isHuman ? "-bottom-9 justify-end" : "-bottom-8",
          "absolute right-0 left-0 z-20 opacity-0 transition-opacity delay-200 duration-300 group-hover/conversation-message:opacity-100",
        )}
      >
        <div className="flex gap-1">
          {isHuman && onEdit && (
            <button
              onClick={handleStartEdit}
              disabled={isBusy}
              className="inline-flex items-center gap-1 rounded-md bg-background px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              title={
                isBusy
                  ? "Cannot edit while generating"
                  : "Edit message"
              }
            >
              <PencilIcon className="size-3" />
            </button>
          )}
          {isHuman && onRegenerate && (
            <button
              onClick={handleRegenerate}
              disabled={isBusy}
              className="inline-flex items-center gap-1 rounded-md bg-background px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              title={
                isBusy
                  ? "Cannot regenerate while generating"
                  : "Regenerate response"
              }
            >
              <RefreshCwIcon className="size-3" />
            </button>
          )}
          <CopyButton
            clipboardData={
              extractContentFromMessage(message) ??
              extractReasoningContentFromMessage(message) ??
              ""
            }
          />
        </div>
      </MessageToolbar>
    </AIElementMessage>
  );
});

/**
 * Custom image component that handles artifact URLs
 */
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

function MessageContent_({
  className,
  message,
  isLoading = false,
  pendingFileNames,
}: {
  className?: string;
  message: Message;
  isLoading?: boolean;
  pendingFileNames?: string[];
}) {
  const rehypePlugins = useRehypeSplitWordsIntoSpans(isLoading);
  const isHuman = message.type === "human";
  const { threadId: thread_id } = useParams<{ threadId: string }>();
  const components = useMemo(
    () => ({
      img: (props: ImgHTMLAttributes<HTMLImageElement>) => (
        <MessageImage {...props} threadId={thread_id ?? ""} maxWidth="90%" />
      ),
    }),
    [thread_id],
  );

  const rawContent = extractContentFromMessage(message);
  const reasoningContent = extractReasoningContentFromMessage(message);
  const { contentToParse, uploadedFiles } = useMemo(() => {
    if (!isLoading && reasoningContent && !rawContent) {
      return {
        contentToParse: reasoningContent,
        uploadedFiles: [] as UploadedFile[],
      };
    }
    if (isHuman && rawContent) {
      const { files, cleanContent: contentWithoutFiles } =
        parseUploadedFiles(rawContent);
      return { contentToParse: contentWithoutFiles, uploadedFiles: files };
    }
    return {
      contentToParse: rawContent ?? "",
      uploadedFiles: [] as UploadedFile[],
    };
  }, [isLoading, rawContent, reasoningContent, isHuman]);

  // Show backend-parsed files if available, otherwise show pending file names
  const hasParsedFiles = uploadedFiles.length > 0;
  const filesList =
    hasParsedFiles && thread_id ? (
      <UploadedFilesList files={uploadedFiles} threadId={thread_id} />
    ) : pendingFileNames && pendingFileNames.length > 0 && thread_id ? (
      <PendingFilesList fileNames={pendingFileNames} threadId={thread_id} />
    ) : null;

  if (isHuman) {
    const messageResponse = contentToParse ? (
      <AIElementMessageResponse
        remarkPlugins={humanMessagePlugins.remarkPlugins}
        rehypePlugins={humanMessagePlugins.rehypePlugins}
        components={components}
      >
        {contentToParse}
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
        content={contentToParse}
        isLoading={isLoading}
        rehypePlugins={[...rehypePlugins, math.rehypePlugin]}
        className="my-3"
        components={components}
      />
    </AIElementMessageContent>
  );
}

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
  return FILE_TYPE_MAP[ext] ?? (ext ? ext.toUpperCase() : "FILE");
}

function isImageFile(filename: string): boolean {
  return IMAGE_EXTENSIONS.includes(getFileExt(filename));
}

/**
 * Uploaded files list component
 */
function UploadedFilesList({
  files,
  threadId,
}: {
  files: UploadedFile[];
  threadId: string;
}) {
  if (files.length === 0) return null;

  return (
    <div className="mb-2 flex flex-wrap justify-end gap-2">
      {files.map((file, index) => (
        <UploadedFileCard
          key={`${file.path}-${index}`}
          file={file}
          threadId={threadId}
        />
      ))}
    </div>
  );
}

/**
 * Single uploaded file card component — clickable to open in artifact panel
 */
function UploadedFileCard({
  file,
  threadId,
}: {
  file: UploadedFile;
  threadId: string;
}) {
  const { select: selectArtifact, setOpen } = useArtifacts();

  const isImage = isImageFile(file.filename);
  const fileUrl = resolveArtifactURL(file.path, threadId);

  const handleClick = () => {
    selectArtifact(file.path);
    setOpen(true);
  };

  if (isImage) {
    return (
      <button
        type="button"
        onClick={handleClick}
        className="group border-border/40 relative block cursor-pointer overflow-hidden rounded-lg border transition-shadow hover:shadow-md hover:ring-2 hover:ring-primary/30"
      >
        <img
          src={fileUrl}
          alt={file.filename}
          className="h-32 w-auto max-w-[240px] object-cover transition-transform group-hover:scale-105"
        />
        <div className="bg-black/60 absolute inset-x-0 bottom-0 px-2 py-1 text-left opacity-0 transition-opacity group-hover:opacity-100">
          <span className="truncate text-[11px] font-medium text-white">{file.filename}</span>
        </div>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className="bg-background border-border/40 flex max-w-[200px] min-w-[120px] cursor-pointer flex-col gap-1 rounded-lg border p-3 text-left shadow-sm transition-all hover:shadow-md hover:ring-2 hover:ring-primary/30"
    >
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
        <span className="text-muted-foreground text-[10px]">{file.size}</span>
      </div>
    </button>
  );
}

/**
 * Pending files list — shown before backend returns <uploaded_files> tag
 */
function PendingFilesList({
  fileNames,
  threadId,
}: {
  fileNames: string[];
  threadId: string;
}) {
  if (fileNames.length === 0) return null;

  return (
    <div className="mb-2 flex flex-wrap justify-end gap-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
      {fileNames.map((name) => (
        <PendingFileCard key={name} filename={name} threadId={threadId} />
      ))}
    </div>
  );
}

/**
 * Single pending file card — clickable to open in artifact panel
 */
function PendingFileCard({
  filename,
  threadId,
}: {
  filename: string;
  threadId: string;
}) {
  const { select: selectArtifact, setOpen } = useArtifacts();
  const filePath = `/mnt/user-data/uploads/${filename}`;
  const isImage = isImageFile(filename);

  const handleClick = () => {
    selectArtifact(filePath);
    setOpen(true);
  };

  if (isImage) {
    const fileUrl = resolveArtifactURL(filePath, threadId);
    return (
      <button
        type="button"
        onClick={handleClick}
        className="group border-border/40 relative block cursor-pointer overflow-hidden rounded-lg border transition-shadow hover:shadow-md hover:ring-2 hover:ring-primary/30"
      >
        <img
          src={fileUrl}
          alt={filename}
          className="h-32 w-auto max-w-[240px] object-cover transition-transform group-hover:scale-105"
        />
        <div className="bg-black/60 absolute inset-x-0 bottom-0 px-2 py-1 text-left opacity-0 transition-opacity group-hover:opacity-100">
          <span className="truncate text-[11px] font-medium text-white">{filename}</span>
        </div>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className="bg-background border-border/40 flex max-w-[200px] min-w-[120px] cursor-pointer flex-col gap-1 rounded-lg border p-3 text-left shadow-sm transition-all hover:shadow-md hover:ring-2 hover:ring-primary/30"
    >
      <div className="flex items-start gap-2">
        <FileIcon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
        <span
          className="text-foreground truncate text-sm font-medium"
          title={filename}
        >
          {filename}
        </span>
      </div>
      <Badge
        variant="secondary"
        className="rounded px-1.5 py-0.5 text-[10px] font-normal"
      >
        {getFileTypeLabel(filename)}
      </Badge>
    </button>
  );
}

const MessageContent = memo(MessageContent_);
