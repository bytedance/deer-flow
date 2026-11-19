"use client";

import { LoaderIcon, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { formatArtifactBytes } from "@/components/workspace/artifacts/artifact-file-preview";
import { useI18n } from "@/core/i18n/hooks";
import {
  PROJECTS_CONFIG_DEFAULT,
  useProjects,
  useProjectsConfig,
} from "@/core/projects";
import {
  RestoreConflictError,
  TrashNotFoundError,
  useEmptyTrash,
  useInfiniteTrashDocuments,
  usePurgeDocument,
  useRestoreDocument,
  type TrashDocument,
} from "@/core/trash";
import { getFileIcon } from "@/core/utils/files";

function errorToastMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** Remaining whole days of the retention window (spec §8.3); the effective
 * window comes from ``GET /api/projects/config`` — expired rows are swept
 * server-side. */
function retentionDaysLeft(trashedAt: string, retentionDays: number): number {
  const expiresAt = new Date(trashedAt).getTime() + retentionDays * 86_400_000;
  return Math.max(0, Math.ceil((expiresAt - Date.now()) / 86_400_000));
}

/**
 * Trash view (spec §9): trashed shelf documents with their origin project
 * and remaining retention, per-entry Restore / Delete-permanently behind an
 * irreversible confirmation, and "Empty trash" with its own confirmation.
 */
export function TrashView() {
  const { t } = useI18n();
  const trashQuery = useInfiniteTrashDocuments();
  const configQuery = useProjectsConfig();
  const retentionDays =
    configQuery.data?.trash_retention_days ??
    PROJECTS_CONFIG_DEFAULT.trash_retention_days;
  const documents =
    trashQuery.data?.pages.flatMap((page) => page.documents) ?? [];
  const documentsTotal = trashQuery.data?.pages.at(-1)?.total ?? 0;
  const [purgeTarget, setPurgeTarget] = useState<TrashDocument | null>(null);
  const [emptyConfirmOpen, setEmptyConfirmOpen] = useState(false);
  const emptyTrash = useEmptyTrash();

  return (
    <div className="mx-auto flex w-full max-w-(--container-width-md) flex-col gap-6 p-6 pt-8">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">{t.trash.title}</h1>
        {documents.length > 0 && (
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setEmptyConfirmOpen(true)}
            data-testid="trash-empty-button"
          >
            <Trash2 className="size-4" />
            {t.trash.emptyTrash}
          </Button>
        )}
      </div>

      {trashQuery.isError ? (
        <div role="alert" className="p-4 text-center text-sm">
          <p>{t.trash.loadFailed}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void trashQuery.refetch()}
          >
            {t.trash.retry}
          </Button>
        </div>
      ) : trashQuery.isLoading ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <LoaderIcon className="size-4 animate-spin" />
          {t.common.loading}
        </div>
      ) : documents.length === 0 ? (
        <Empty className="border py-16">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Trash2 />
            </EmptyMedia>
            <EmptyTitle>{t.trash.title}</EmptyTitle>
            <EmptyDescription>{t.trash.empty}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <>
          <ul className="flex w-full flex-col gap-2">
            {documents.map((document) => (
              <TrashDocumentRow
                key={document.id}
                document={document}
                retentionDays={retentionDays}
                onPurge={() => setPurgeTarget(document)}
              />
            ))}
          </ul>
          <div className="flex flex-col items-center gap-1">
            <p className="text-muted-foreground text-xs">
              {t.common.showingOf(documents.length, documentsTotal)}
            </p>
            {trashQuery.hasNextPage && (
              <Button
                variant="ghost"
                size="sm"
                className="text-xs"
                disabled={trashQuery.isFetchingNextPage}
                onClick={() => void trashQuery.fetchNextPage()}
                data-testid="trash-load-more"
              >
                {trashQuery.isFetchingNextPage
                  ? t.chats.loadingMore
                  : t.common.loadMore}
              </Button>
            )}
          </div>
        </>
      )}

      <Dialog
        open={purgeTarget !== null}
        onOpenChange={(open) => !open && setPurgeTarget(null)}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.trash.deletePermanentlyTitle}</DialogTitle>
            <DialogDescription>
              {purgeTarget &&
                t.trash.deletePermanentlyConfirm(purgeTarget.name)}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPurgeTarget(null)}>
              {t.common.cancel}
            </Button>
            <PurgeConfirmButton
              target={purgeTarget}
              onDone={() => setPurgeTarget(null)}
            />
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={emptyConfirmOpen} onOpenChange={setEmptyConfirmOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.trash.emptyTrashTitle}</DialogTitle>
            <DialogDescription>
              {t.trash.emptyTrashConfirm(documentsTotal)}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEmptyConfirmOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              disabled={emptyTrash.isPending}
              onClick={() =>
                emptyTrash.mutate(undefined, {
                  onSuccess: () => setEmptyConfirmOpen(false),
                  onError: (error) => {
                    toast.error(
                      errorToastMessage(error, t.trash.emptyTrashFailed),
                    );
                  },
                })
              }
            >
              {t.trash.emptyTrash}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PurgeConfirmButton({
  target,
  onDone,
}: {
  target: TrashDocument | null;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const purgeDocument = usePurgeDocument();
  return (
    <Button
      variant="destructive"
      disabled={purgeDocument.isPending || target === null}
      onClick={() => {
        if (!target) {
          return;
        }
        purgeDocument.mutate(target.id, {
          onSuccess: onDone,
          onError: (error) => {
            toast.error(errorToastMessage(error, t.trash.purgeFailed));
          },
        });
      }}
    >
      {t.trash.deletePermanently}
    </Button>
  );
}

function TrashDocumentRow({
  document,
  retentionDays,
  onPurge,
}: {
  document: TrashDocument;
  retentionDays: number;
  onPurge: () => void;
}) {
  const { t } = useI18n();
  const restoreDocument = useRestoreDocument();
  // Set when a targetless restore 404s: the origin project is gone or
  // archived, so the row offers the active-project picker (§8.2, §11).
  const [pickerOpen, setPickerOpen] = useState(false);

  const restore = (projectId?: string) => {
    restoreDocument.mutate(
      { documentId: document.id, projectId },
      {
        onSuccess: (result) => {
          toast.success(
            result.outcome === "merged"
              ? t.trash.restoreMergedToast(result.document.name)
              : t.trash.restoredToast(result.document.name),
          );
          setPickerOpen(false);
        },
        onError: (error) => {
          if (error instanceof RestoreConflictError) {
            // 409 content_missing: the bytes are gone; the row stays.
            toast.error(t.trash.restoreConflict);
            return;
          }
          if (error instanceof TrashNotFoundError && projectId === undefined) {
            setPickerOpen(true);
            return;
          }
          toast.error(errorToastMessage(error, t.trash.restoreFailed));
        },
      },
    );
  };

  return (
    <li className="flex items-center gap-3 rounded-md border p-3">
      {getFileIcon(document.name, "size-5 shrink-0")}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-sm font-medium">{document.name}</span>
        <span className="text-muted-foreground text-xs">
          {t.trash.originProject(
            document.trash_origin?.project_name ?? t.trash.unknownProject,
          )}
          {" · "}
          {formatArtifactBytes(document.size_bytes)}
          {" · "}
          {t.trash.retentionLeft(
            retentionDaysLeft(document.trashed_at, retentionDays),
          )}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={restoreDocument.isPending}
          onClick={() => restore()}
        >
          <RotateCcw className="size-4" />
          {t.trash.restore}
        </Button>
        <Button variant="ghost" size="sm" onClick={onPurge}>
          <Trash2 className="size-4" />
          {t.trash.deletePermanently}
        </Button>
      </div>

      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.trash.restorePickProjectTitle}</DialogTitle>
            <DialogDescription>
              {t.trash.restorePickProjectHint}
            </DialogDescription>
          </DialogHeader>
          <RestoreProjectPicker
            isPending={restoreDocument.isPending}
            onPick={(projectId) => restore(projectId)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setPickerOpen(false)}>
              {t.common.cancel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}

function RestoreProjectPicker({
  isPending,
  onPick,
}: {
  isPending: boolean;
  onPick: (projectId: string) => void;
}) {
  const { t } = useI18n();
  const projectsQuery = useProjects("active");
  const projects = projectsQuery.data ?? [];
  if (projectsQuery.isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 p-2 text-sm">
        <LoaderIcon className="size-4 animate-spin" />
        {t.common.loading}
      </div>
    );
  }
  if (projects.length === 0) {
    return (
      <p className="text-muted-foreground p-2 text-sm">{t.projects.empty}</p>
    );
  }
  return (
    <div className="flex max-h-80 flex-col gap-1 overflow-auto">
      {projects.map((project) => (
        <Button
          key={project.id}
          variant="ghost"
          className="justify-start"
          disabled={isPending}
          onClick={() => onPick(project.id)}
        >
          <span className="truncate">{project.name}</span>
        </Button>
      ))}
    </div>
  );
}
