"use client";

import {
  CheckIcon,
  DownloadIcon,
  LoaderIcon,
  RotateCwIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { prepareArtifactDownload } from "@/core/artifacts/download";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { getFileName } from "@/core/utils/files";

type Props = {
  filepath: string;
  threadId: string;
  isMock?: boolean;
  compact?: boolean;
  label?: string;
};

function DownloadAction({ filepath, threadId, isMock, compact, label }: Props) {
  const { t } = useI18n();
  const [state, setState] = useState<
    "idle" | "preparing" | "failed" | "requested"
  >("idle");
  const request = useRef<AbortController | null>(null);
  const urls = useRef(new Set<string>());
  useEffect(
    () => () => {
      request.current?.abort();
      urls.current.forEach((url) => URL.revokeObjectURL(url));
    },
    [],
  );
  const filename = getFileName(filepath);
  const text =
    state === "preparing"
      ? t.artifactPreview.preparingDownload
      : state === "failed"
        ? t.artifactPreview.retryDownload
        : (label ?? t.common.download);
  const Icon =
    state === "preparing"
      ? LoaderIcon
      : state === "failed"
        ? RotateCwIcon
        : state === "requested"
          ? CheckIcon
          : DownloadIcon;
  return (
    <div className="flex min-w-0 flex-col items-center gap-1">
      <Button
        type="button"
        variant={compact ? "ghost" : "outline"}
        disabled={state === "preparing"}
        aria-label={`${text} ${filename}`}
        title={`${text} ${filename}`}
        onClick={async (event) => {
          event.stopPropagation();
          if (request.current) return;
          const controller = new AbortController();
          request.current = controller;
          setState("preparing");
          try {
            const url = urlOfArtifact({
              filepath,
              threadId,
              download: true,
              isMock,
            });
            const blob = await prepareArtifactDownload(url, controller.signal);
            controller.signal.throwIfAborted();
            const link = document.createElement("a");
            const objectUrl = blob ? URL.createObjectURL(blob) : undefined;
            if (objectUrl) urls.current.add(objectUrl);
            link.href = objectUrl ?? url;
            link.download = filename;
            document.body.append(link);
            link.click();
            link.remove();
            if (objectUrl)
              setTimeout(() => {
                URL.revokeObjectURL(objectUrl);
                urls.current.delete(objectUrl);
              }, 30_000);
            setState("requested");
          } catch {
            if (!controller.signal.aborted) setState("failed");
          } finally {
            if (request.current === controller) request.current = null;
          }
        }}
      >
        <Icon
          className={state === "preparing" ? "size-4 animate-spin" : "size-4"}
        />
        {!compact && text}
      </Button>
      <span
        role="status"
        className={
          compact && state !== "failed"
            ? "sr-only"
            : "text-muted-foreground max-w-36 text-center text-xs"
        }
      >
        {state === "failed"
          ? t.artifactPreview.downloadFailed
          : state === "preparing"
            ? t.artifactPreview.preparingDownload
            : state === "requested"
              ? t.artifactPreview.downloadRequested
              : ""}
      </span>
    </div>
  );
}

export function ArtifactDownloadButton(props: Props) {
  const { user } = useAuth();
  return (
    <DownloadAction
      key={JSON.stringify([
        user?.id,
        props.threadId,
        props.filepath,
        props.isMock,
      ])}
      {...props}
    />
  );
}
