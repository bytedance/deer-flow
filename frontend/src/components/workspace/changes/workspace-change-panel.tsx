"use client";

import {
  ExternalLinkIcon,
  FileDiffIcon,
  FileMinusIcon,
  FilePenLineIcon,
  FilePlusIcon,
} from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { resolveArtifactURL } from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import { useWorkspaceChanges } from "@/core/workspace-changes/hooks";
import {
  getChangedFileCount,
  getWorkspaceChangeLineClass,
  sortWorkspaceChanges,
} from "@/core/workspace-changes/summary";
import type {
  DiffUnavailableReason,
  WorkspaceChangeStatus,
  WorkspaceChangeSummary,
  WorkspaceFileChange,
} from "@/core/workspace-changes/types";
import { cn } from "@/lib/utils";

export function WorkspaceChangePanel({
  threadId,
  runId,
  fallbackSummary,
  open,
}: {
  threadId: string;
  runId: string;
  fallbackSummary: WorkspaceChangeSummary;
  open: boolean;
}) {
  const { t } = useI18n();
  const { data, isLoading } = useWorkspaceChanges({
    threadId,
    runId,
    includeFiles: true,
    enabled: open,
  });
  const changes = data ?? {
    available: true,
    version: 1,
    summary: fallbackSummary,
    files: [],
    limits: {},
  };
  const fileCount = getChangedFileCount(changes.summary);
  const files = sortWorkspaceChanges(changes.files);

  return (
    <SheetContent className="w-[min(92vw,900px)] gap-0 p-0 sm:max-w-[900px]">
      <SheetHeader className="border-border border-b px-5 py-4">
        <SheetTitle className="flex items-center gap-2 text-base">
          <FileDiffIcon className="text-muted-foreground size-4" />
          {t.workspaceChanges.title}
        </SheetTitle>
        <SheetDescription>
          {t.workspaceChanges.badge(
            fileCount,
            changes.summary.additions,
            changes.summary.deletions,
          )}
          {changes.summary.truncated
            ? ` · ${t.workspaceChanges.truncatedSummary}`
            : ""}
        </SheetDescription>
      </SheetHeader>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {isLoading && (
          <p className="text-muted-foreground text-sm">
            {t.workspaceChanges.loading}
          </p>
        )}
        {!isLoading && files.length === 0 && (
          <p className="text-muted-foreground text-sm">
            {t.workspaceChanges.noChanges}
          </p>
        )}
        <div className="flex flex-col gap-3">
          {files.map((file) => (
            <WorkspaceChangeFile
              key={`${file.status}:${file.path}`}
              file={file}
              threadId={threadId}
            />
          ))}
        </div>
      </div>
    </SheetContent>
  );
}

function WorkspaceChangeFile({
  file,
  threadId,
}: {
  file: WorkspaceFileChange;
  threadId: string;
}) {
  const { t } = useI18n();
  const hasDiff = file.diff.length > 0;
  const openUrl = resolveArtifactURL(file.path, threadId);
  const canOpenFile = file.status !== "deleted" && !file.sensitive;

  return (
    <Collapsible defaultOpen={hasDiff}>
      <div className="border-border/70 bg-background rounded-lg border">
        <CollapsibleTrigger className="flex w-full items-start justify-between gap-3 px-3 py-2 text-left">
          <div className="flex min-w-0 items-start gap-2">
            <StatusIcon status={file.status} />
            <div className="min-w-0">
              <div className="text-foreground truncate font-mono text-xs">
                {file.path}
              </div>
              <div className="text-muted-foreground mt-1 flex items-center gap-2 text-xs">
                <span>{statusLabel(file.status, t)}</span>
                {(file.additions > 0 || file.deletions > 0) && (
                  <span>
                    <span className="text-emerald-500">+{file.additions}</span>{" "}
                    <span className="text-red-500">-{file.deletions}</span>
                  </span>
                )}
              </div>
            </div>
          </div>
          {canOpenFile && (
            <a
              href={openUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted-foreground hover:text-foreground rounded-md p-1 transition-colors"
              title={t.workspaceChanges.openFile}
              onClick={(event) => event.stopPropagation()}
            >
              <ExternalLinkIcon className="size-3.5" />
            </a>
          )}
        </CollapsibleTrigger>
        <CollapsibleContent>
          {hasDiff ? (
            <WorkspaceDiff diff={file.diff} />
          ) : (
            <div className="border-border/70 text-muted-foreground border-t px-3 py-3 text-xs">
              {unavailableLabel(file.diff_unavailable_reason, t)}
            </div>
          )}
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

function WorkspaceDiff({ diff }: { diff: string }) {
  return (
    <pre className="border-border/70 bg-muted/30 max-h-[520px] overflow-auto border-t p-0 font-mono text-xs leading-5">
      {diff.split("\n").map((line, index) => (
        <div
          key={`${index}:${line}`}
          className={cn(
            "min-w-max px-3 whitespace-pre",
            diffLineClassName(line),
          )}
        >
          {line || " "}
        </div>
      ))}
    </pre>
  );
}

function StatusIcon({ status }: { status: WorkspaceChangeStatus }) {
  const className = "mt-0.5 size-4 shrink-0";
  if (status === "created") {
    return <FilePlusIcon className={cn(className, "text-emerald-500")} />;
  }
  if (status === "deleted") {
    return <FileMinusIcon className={cn(className, "text-red-500")} />;
  }
  return <FilePenLineIcon className={cn(className, "text-sky-500")} />;
}

function statusLabel(
  status: WorkspaceChangeStatus,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (status === "created") {
    return t.workspaceChanges.created;
  }
  if (status === "deleted") {
    return t.workspaceChanges.deleted;
  }
  return t.workspaceChanges.modified;
}

function unavailableLabel(
  reason: DiffUnavailableReason | null,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (reason === "binary") {
    return t.workspaceChanges.binaryUnavailable;
  }
  if (reason === "large") {
    return t.workspaceChanges.largeUnavailable;
  }
  if (reason === "sensitive") {
    return t.workspaceChanges.sensitiveUnavailable;
  }
  if (reason === "truncated") {
    return t.workspaceChanges.truncatedUnavailable;
  }
  return t.workspaceChanges.diffUnavailable;
}

function diffLineClassName(line: string) {
  const lineClass = getWorkspaceChangeLineClass(line);
  if (lineClass === "addition") {
    return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  }
  if (lineClass === "deletion") {
    return "bg-red-500/10 text-red-700 dark:text-red-300";
  }
  if (lineClass === "hunk") {
    return "bg-sky-500/10 text-sky-700 dark:text-sky-300";
  }
  if (lineClass === "meta") {
    return "text-muted-foreground";
  }
  return "text-foreground";
}
