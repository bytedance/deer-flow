"use client";

import {
  CheckIcon,
  LoaderIcon,
  RotateCwIcon,
  SquareIcon,
  XIcon,
} from "lucide-react";
import { useSyncExternalStore } from "react";

import {
  PromptInputHoverCard,
  PromptInputHoverCardContent,
  usePromptInputAttachments,
  type PromptInputAttachmentProps,
} from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { HoverCardTrigger } from "@/components/ui/hover-card";
import { useI18n } from "@/core/i18n/hooks";
import type { AttachmentUploadSession } from "@/core/uploads/attachment-upload-session";
import { formatUploadSize } from "@/core/uploads/file-validation";
import { getFileExtensionDisplayName } from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { FileName } from "./file-name";
import { FileTypeIcon } from "./file-type-icon";

const noSubscribe = () => () => undefined;
const emptySnapshot = () => 0;

export function InputAttachment({
  data,
  className,
  uploadSession,
  ...props
}: PromptInputAttachmentProps & { uploadSession?: AttachmentUploadSession }) {
  const attachments = usePromptInputAttachments();
  const { t } = useI18n();
  useSyncExternalStore(
    uploadSession?.subscribe ?? noSubscribe,
    uploadSession?.snapshot ?? emptySnapshot,
    emptySnapshot,
  );
  const status = uploadSession?.status(data) ?? "pending";
  const uploadError = uploadSession?.error(data);

  const filename = data.filename ?? "";

  const mediaType =
    data.mediaType?.startsWith("image/") && data.url ? "image" : "file";
  const isImage = mediaType === "image";

  const attachmentLabel =
    filename || (isImage ? t.uploads.image : t.uploads.attachment);

  return (
    <PromptInputHoverCard>
      <HoverCardTrigger asChild>
        <div
          className={cn(
            "group border-border bg-background hover:bg-accent relative flex h-14 max-w-full items-center gap-2 rounded-xl border py-1 pr-1 pl-2.5 text-sm transition-colors select-none sm:max-w-72",
            className,
          )}
          key={data.id}
          {...props}
        >
          <div className="relative size-6 shrink-0">
            <div className="absolute inset-0 flex items-center justify-center overflow-hidden rounded">
              {isImage ? (
                <img
                  alt=""
                  className="size-5 object-cover"
                  height={20}
                  src={data.url}
                  width={20}
                />
              ) : (
                <FileTypeIcon filename={filename} compact />
              )}
            </div>
          </div>

          <span className="min-w-0 flex-1">
            <FileName
              filename={attachmentLabel}
              className="text-xs font-medium"
            />
            <span className="text-muted-foreground block text-[10px]">
              {getFileExtensionDisplayName(filename)}
              {data.file && ` · ${formatUploadSize(data.file.size)}`}
            </span>
            {uploadSession && (
              <span
                role="status"
                className={cn(
                  "flex items-center gap-1 text-[10px]",
                  status === "failed"
                    ? "text-destructive"
                    : "text-muted-foreground",
                )}
              >
                {status === "uploading" && (
                  <LoaderIcon className="size-3 animate-spin" />
                )}
                {status === "uploaded" && <CheckIcon className="size-3" />}
                {t.uploads.status[status]}
              </span>
            )}
          </span>
          {status === "uploading" && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-10 shrink-0"
              aria-label={`${t.uploads.cancelUpload}: ${attachmentLabel}`}
              onClick={(e) => {
                e.stopPropagation();
                uploadSession?.cancel(data);
              }}
            >
              <SquareIcon className="size-3.5" />
            </Button>
          )}
          {(status === "failed" || status === "cancelled") && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-10 shrink-0"
              aria-label={`${t.uploads.retryUpload}: ${attachmentLabel}`}
              onClick={(e) => {
                e.stopPropagation();
                void uploadSession?.retry(data);
              }}
            >
              <RotateCwIcon className="size-3.5" />
            </Button>
          )}
          <Button
            aria-label={t.uploads.removeAttachment(attachmentLabel)}
            title={t.uploads.removeAttachment(attachmentLabel)}
            className="text-muted-foreground size-10 shrink-0 cursor-pointer rounded-lg p-0 [&>svg]:size-3.5"
            onClick={(e) => {
              e.stopPropagation();
              uploadSession?.cancel(data);
              attachments.remove(data.id);
            }}
            type="button"
            variant="ghost"
          >
            <XIcon />
          </Button>
        </div>
      </HoverCardTrigger>
      <PromptInputHoverCardContent className="max-w-[calc(100vw-2rem)] p-2">
        <div className="w-auto space-y-3">
          {isImage && (
            <div className="flex max-h-96 w-96 max-w-full items-center justify-center overflow-hidden rounded-md border">
              <img
                alt={attachmentLabel}
                className="max-h-full max-w-full object-contain"
                height={384}
                src={data.url}
                width={448}
              />
            </div>
          )}
          <div className="flex items-center gap-2.5">
            <div className="min-w-0 flex-1 space-y-1 px-0.5">
              <h4 className="text-sm leading-snug font-semibold break-all">
                {attachmentLabel}
              </h4>
              {data.mediaType && (
                <p className="text-muted-foreground truncate font-mono text-xs">
                  {data.mediaType}
                </p>
              )}
            </div>
          </div>
          {uploadError && (
            <p className="text-destructive max-w-72 text-xs break-words">
              {uploadError}
            </p>
          )}
        </div>
      </PromptInputHoverCardContent>
    </PromptInputHoverCard>
  );
}
