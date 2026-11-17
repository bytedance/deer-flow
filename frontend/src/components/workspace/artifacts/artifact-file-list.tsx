import { useQuery } from "@tanstack/react-query";
import { DownloadIcon, LoaderIcon, PackageIcon } from "lucide-react";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { FileName } from "@/components/workspace/file-name";
import { FileTypeIcon } from "@/components/workspace/file-type-icon";
import {
  ArtifactRequestError,
  downloadArtifactArchive,
  getArtifactArchiveManifest,
  MAX_ARTIFACT_ARCHIVE_FILES,
} from "@/core/artifacts/api";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { installSkill, SkillRequestError } from "@/core/skills/api";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { getFileExtensionDisplayName, getFileName } from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { ArtifactDownloadButton } from "./artifact-download-button";
import { useArtifacts } from "./context";

export function ArtifactFileList({
  archiveDownloadsEnabled = true,
  className,
  files,
  runId,
  threadId,
}: {
  archiveDownloadsEnabled?: boolean;
  className?: string;
  files: string[];
  runId?: string;
  threadId: string;
}) {
  const { t } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const { select: selectArtifact, setOpen } = useArtifacts();
  const [downloadingArchive, setDownloadingArchive] = useState(false);
  const [installingFile, setInstallingFile] = useState<string | null>(null);
  const staticWebsiteOnly = isStaticWebsiteOnly();
  const { data: archiveManifest } = useQuery({
    queryKey: ["artifact-archive-manifest", threadId, runId],
    queryFn: () => getArtifactArchiveManifest({ threadId, runId: runId! }),
    enabled:
      archiveDownloadsEnabled && runId !== undefined && !staticWebsiteOnly,
    retry: false,
    staleTime: Infinity,
  });
  const archiveCount = archiveManifest?.fileCount;

  const handleClick = useCallback(
    (filepath: string) => {
      selectArtifact(filepath);
      setOpen(true);
    },
    [selectArtifact, setOpen],
  );

  const handleInstallSkill = useCallback(
    async (e: React.MouseEvent, filepath: string) => {
      e.stopPropagation();
      e.preventDefault();

      if (installingFile) return;

      setInstallingFile(filepath);
      try {
        const result = await installSkill({
          thread_id: threadId,
          path: filepath,
        });
        if (result.success) {
          toast.success(result.message);
        } else {
          toast.error(result.message || "Failed to install skill");
        }
      } catch (error) {
        console.error("Failed to install skill:", error);
        if (error instanceof SkillRequestError && error.isAdminRequired) {
          toast.error(t.settings.skills.installAdminRequired);
        } else {
          toast.error("Failed to install skill");
        }
      } finally {
        setInstallingFile(null);
      }
    },
    [threadId, installingFile, t],
  );

  const handleDownloadArchive = useCallback(async () => {
    if (!runId || downloadingArchive) return;

    setDownloadingArchive(true);
    let objectUrl: string | undefined;
    try {
      const { blob, filename } = await downloadArtifactArchive({
        threadId,
        runId,
      });
      objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
    } catch (error) {
      console.error("Failed to download artifact archive:", error);
      toast.error(
        error instanceof ArtifactRequestError
          ? error.message
          : t.artifactArchive.downloadFailed,
      );
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setDownloadingArchive(false);
    }
  }, [downloadingArchive, runId, t, threadId]);

  const canDownloadArchive =
    archiveDownloadsEnabled &&
    archiveCount !== undefined &&
    archiveCount > 1 &&
    archiveCount <= MAX_ARTIFACT_ARCHIVE_FILES &&
    !staticWebsiteOnly;

  return (
    <div className={cn("flex w-full flex-col gap-4", className)}>
      {canDownloadArchive && (
        <div className="flex flex-col items-start gap-1">
          <Button
            variant="outline"
            disabled={downloadingArchive}
            onClick={handleDownloadArchive}
          >
            {downloadingArchive ? (
              <LoaderIcon className="size-4 animate-spin" />
            ) : (
              <DownloadIcon className="size-4" />
            )}
            {t.artifactArchive.downloadCurrent(archiveCount)}
          </Button>
          <p className="text-muted-foreground text-xs">
            {t.artifactArchive.currentVersionNotice}
          </p>
        </div>
      )}
      <ul className="grid w-full grid-cols-[repeat(auto-fit,minmax(min(100%,18rem),1fr))] gap-2">
        {files.map((file) => (
          <li
            key={file}
            className="bg-card hover:bg-accent/40 flex min-w-0 items-center gap-1 rounded-xl border p-1.5 transition-colors"
          >
            <button
              type="button"
              aria-label={`${getFileName(file)} ${getFileExtensionDisplayName(file)}`}
              onClick={() => handleClick(file)}
              className="focus-visible:ring-ring flex min-w-0 flex-1 items-center gap-3 rounded-lg p-2 text-left outline-none focus-visible:ring-2"
            >
              <FileTypeIcon filename={file} />
              <span className="min-w-0 flex-1 space-y-1">
                <FileName
                  filename={getFileName(file)}
                  className="text-sm font-medium"
                />
                <span className="text-muted-foreground block text-xs">
                  {getFileExtensionDisplayName(file)}
                </span>
              </span>
            </button>
            <div className="flex shrink-0 items-center">
              {file.endsWith(".skill") && isAdmin && (
                <Button
                  variant="ghost"
                  disabled={installingFile === file}
                  onClick={(e) => handleInstallSkill(e, file)}
                >
                  {installingFile === file ? (
                    <LoaderIcon className="size-4 animate-spin" />
                  ) : (
                    <PackageIcon className="size-4" />
                  )}
                  {t.common.install}
                </Button>
              )}
              <ArtifactDownloadButton
                filepath={file}
                threadId={threadId}
                compact
              />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
