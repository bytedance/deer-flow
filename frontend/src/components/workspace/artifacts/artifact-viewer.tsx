"use client";

import { ExternalLinkIcon, LoaderIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useStandaloneArtifactContent } from "@/core/artifacts/hooks";
import { getTabularDelimiter } from "@/core/artifacts/preview";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { resolveStoredArtifactLanguage } from "@/core/artifacts/viewer";
import { useI18n } from "@/core/i18n/hooks";
import { checkCodeFile, getFileIcon, getFileName } from "@/core/utils/files";

import { FileTypeIcon } from "../file-type-icon";

import { ArtifactDownloadButton } from "./artifact-download-button";
import {
  formatArtifactBytes,
  ArtifactDownloadFallback,
  ArtifactFilePreview,
} from "./artifact-file-preview";
import { PluginArtifactPreview } from "./plugin-artifact-preview";

type ViewerProps = { filepath: string; threadId: string; isMock?: boolean };

export function ArtifactViewer(props: ViewerProps) {
  if (
    checkCodeFile(props.filepath).isCodeFile ||
    props.filepath.endsWith(".skill")
  )
    return <TextArtifactViewer {...props} />;
  return (
    <div className="bg-background flex h-screen flex-col">
      <header className="border-border flex shrink-0 items-center gap-3 border-b px-4 py-3">
        <FileTypeIcon filename={props.filepath} compact />
        <span className="min-w-0 flex-1 truncate font-medium">
          {getFileName(props.filepath)}
        </span>
        <ArtifactDownloadButton {...props} />
      </header>
      <main className="min-h-0 flex-1">
        {props.isMock ? (
          <ArtifactDownloadFallback {...props} />
        ) : (
          <PluginArtifactPreview {...props} />
        )}
      </main>
    </div>
  );
}

/** Shared standalone reader for Markdown and bounded CSV/TSV previews. */
function TextArtifactViewer({
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
  const language = resolveStoredArtifactLanguage(filepath) ?? "text";
  const isTabular = getTabularDelimiter(language) !== null;
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
        <ArtifactDownloadButton
          filepath={filepath}
          threadId={threadId}
          isMock={isMock}
        />
      </header>

      {truncated && !isTabular && (
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

      <main
        className={`mx-auto min-h-0 w-full flex-1 overflow-hidden ${isTabular ? "" : "max-w-4xl"}`}
      >
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
            language={language}
            scrollKey={`${threadId}:${filepath}`}
            artifact={{ filepath, threadId, isMock }}
            truncated={truncated}
            url={url}
          />
        )}
      </main>
    </div>
  );
}
