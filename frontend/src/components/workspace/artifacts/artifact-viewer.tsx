"use client";

import { DownloadIcon, ExternalLinkIcon, LoaderIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useStandaloneArtifactContent } from "@/core/artifacts/hooks";
import { getTabularDelimiter } from "@/core/artifacts/preview";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { resolveStoredArtifactLanguage } from "@/core/artifacts/viewer";
import { AuthProvider, type User } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { getFileIcon, getFileName } from "@/core/utils/files";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  useWorkspaceLifetime,
} from "@/core/workspaces/context";

import {
  formatArtifactBytes,
  ArtifactFilePreview,
} from "./artifact-file-preview";

/** Shared standalone reader for Markdown and bounded CSV/TSV previews. */
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
  const lifetime = useWorkspaceLifetime();
  const workspaceId = lifetime?.scope.workspaceId;
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
            href={urlOfArtifact({ filepath, threadId, isMock, workspaceId })}
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
              workspaceId,
            })}
          >
            <DownloadIcon className="size-4" />
            {t.common.download}
          </a>
        </Button>
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
            truncated={truncated}
            url={url}
          />
        )}
      </main>
    </div>
  );
}

function ArtifactWorkspaceStatus() {
  const context = useWorkspaceContext();
  const { t } = useI18n();
  const pending = context?.state.status === "loading";
  return (
    <main
      role={pending ? "status" : "alert"}
      className="flex h-screen items-center justify-center p-6"
    >
      <p className="text-muted-foreground text-sm">
        {pending ? t.artifactPreview.loading : t.artifactPreview.unavailable}
      </p>
    </main>
  );
}

/** `enabled` has already been confirmed by the server page, never the URL. */
export function WorkspaceArtifactViewer({
  initialUser,
  workspaceId,
  ...target
}: {
  initialUser: User;
  workspaceId?: string;
  filepath: string;
  threadId: string;
  isMock?: boolean;
}) {
  return (
    <AuthProvider key={initialUser.id} initialUser={initialUser}>
      <WorkspaceProvider enabled initialWorkspaceId={workspaceId}>
        <WorkspaceReadyBoundary fallback={<ArtifactWorkspaceStatus />}>
          <ArtifactViewer {...target} />
        </WorkspaceReadyBoundary>
      </WorkspaceProvider>
    </AuthProvider>
  );
}
