"use client";

import { DownloadIcon, ExternalLinkIcon, LoaderIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useStandaloneArtifactContent } from "@/core/artifacts/hooks";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import { getFileIcon, getFileName } from "@/core/utils/files";

import {
  formatArtifactBytes,
  ArtifactFilePreview,
} from "./artifact-file-preview";

/**
 * Standalone markdown artifact window.
 *
 * The artifacts panel's "open in new window" action used to hand the browser
 * the raw Gateway response, which shows markdown as its own source. This
 * renders it with the same components the panel uses, so the new window is a
 * reader rather than a text dump. Markdown only — HTML and SVG artifacts stay
 * on the Gateway's download path so active content never runs in this origin.
 */
export function ArtifactViewer({
  filepath,
  threadId,
  isMock = false,
}: {
  filepath: string;
  threadId: string;
  isMock?: boolean;
}) {
  const { t } = useI18n();
  const filename = getFileName(filepath);
  const {
    content,
    url,
    truncated,
    previewBytes,
    totalBytes,
    fullContentRequested,
    loadFullContent,
    isLoading,
    error,
  } = useStandaloneArtifactContent({ filepath, threadId, isMock });

  const isLoadingFullContent = fullContentRequested && isLoading;

  return (
    <div className="bg-background flex h-screen flex-col">
      <header className="border-border bg-background/95 sticky top-0 z-10 flex shrink-0 items-center gap-3 border-b px-4 py-3 backdrop-blur">
        <div className="text-muted-foreground shrink-0">
          {getFileIcon(filepath, "size-4")}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium" title={filepath}>
            {filename}
          </div>
          <div className="text-muted-foreground truncate text-xs">
            {filepath}
          </div>
        </div>
        <Button variant="ghost" size="sm" asChild>
          <a
            href={urlOfArtifact({ filepath, threadId, isMock })}
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLinkIcon className="size-4" />
            {t.artifactPreview.viewSource}
          </a>
        </Button>
        <Button variant="outline" size="sm" asChild>
          <a
            href={urlOfArtifact({
              filepath,
              threadId,
              isMock,
              download: true,
            })}
          >
            <DownloadIcon className="size-4" />
            {t.common.download}
          </a>
        </Button>
      </header>

      {truncated && (
        <div className="border-border bg-muted/40 flex shrink-0 items-center justify-between gap-3 border-b px-4 py-2 text-sm">
          <span className="text-muted-foreground">
            {t.artifactPreview.limited(
              formatArtifactBytes(previewBytes) ?? "1 MiB",
              formatArtifactBytes(totalBytes),
            )}
          </span>
          <Button size="sm" variant="outline" onClick={loadFullContent}>
            {t.artifactPreview.loadFullFile}
          </Button>
        </div>
      )}
      {isLoadingFullContent && (
        <div className="border-border text-muted-foreground flex shrink-0 items-center gap-2 border-b px-4 py-2 text-sm">
          <LoaderIcon className="size-4 animate-spin" />
          {t.artifactPreview.loadingFullFile}
        </div>
      )}

      <main className="mx-auto min-h-0 w-full max-w-4xl flex-1 overflow-hidden">
        {error ? (
          <p className="text-muted-foreground p-6 text-sm">
            {t.artifactPreview.previewFailed}
          </p>
        ) : content === undefined ? (
          <div className="text-muted-foreground flex items-center gap-2 p-6 text-sm">
            <LoaderIcon className="size-4 animate-spin" />
            {t.common.loading}
          </div>
        ) : (
          <ArtifactFilePreview
            content={content}
            language="markdown"
            scrollKey={filepath}
            url={url}
          />
        )}
      </main>
    </div>
  );
}
