"use client";

import {
  Archive,
  FileText,
  LoaderIcon,
  Paperclip,
  Trash2,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  ArtifactFilePreview,
  formatArtifactBytes,
} from "@/components/workspace/artifacts/artifact-file-preview";
import { getTabularDelimiter } from "@/core/artifacts/preview";
import {
  resolveArtifactOpenURL,
  resolveStoredArtifactLanguage,
} from "@/core/artifacts/viewer";
import { useI18n } from "@/core/i18n/hooks";
import {
  fetchProjectDocumentPreview,
  PROJECTS_CONFIG_DEFAULT,
  urlOfProjectDocumentContent,
  useAttachProjectDocument,
  useDeleteProjectDocument,
  useInfiniteProjectDocuments,
  useProjectsConfig,
  useInfiniteProjectThreadFiles,
  usePromoteThreadFile,
  useUploadProjectDocument,
  type Project,
  type ProjectDocument,
  type ProjectDocumentPreview,
  type ProjectThread,
  type ProjectThreadFile,
  type ProjectThreadFileGroup,
} from "@/core/projects";
import { stageProjectAttachment } from "@/core/projects/composer-attach";
import { useInfiniteThreads } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";
import {
  isThreadArchived,
  pathOfThread,
  titleOfThread,
} from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { getFileIcon } from "@/core/utils/files";
import { env } from "@/env";
import { cn } from "@/lib/utils";

function errorToastMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * Documents tab (spec §9): the curated shelf (upload + drag-drop, rows with
 * provenance, preview/download/attach/trash) above a divider, then the
 * read-only conversation-files browser grouped by thread. Archived projects
 * keep every read affordance and lose every mutation (§8.4).
 */
export function ProjectDocumentsSection({
  project,
  threads,
}: {
  project: Project;
  threads: ProjectThread[];
}) {
  const { t } = useI18n();
  const isArchived = project.status === "archived";
  return (
    <section className="flex flex-col gap-6">
      {isArchived && (
        <div
          role="status"
          className="text-muted-foreground flex items-center gap-2 rounded-md border border-dashed p-3 text-sm"
          data-testid="project-documents-archived-banner"
        >
          <Archive className="size-4 shrink-0" />
          {t.projects.archivedDocumentsBanner}
        </div>
      )}
      <ProjectDocumentShelf project={project} threads={threads} />
      <Separator />
      <ProjectConversationFiles project={project} />
    </section>
  );
}

function ProjectDocumentShelf({
  project,
  threads,
}: {
  project: Project;
  threads: ProjectThread[];
}) {
  const { t } = useI18n();
  const router = useRouter();
  const isArchived = project.status === "archived";
  const documentsQuery = useInfiniteProjectDocuments(project.id);
  const projectsConfigQuery = useProjectsConfig();
  const trashRetentionDays =
    projectsConfigQuery.data?.trash_retention_days ??
    PROJECTS_CONFIG_DEFAULT.trash_retention_days;
  const uploadDocument = useUploadProjectDocument(project.id);
  const deleteDocument = useDeleteProjectDocument(project.id);
  const attachDocument = useAttachProjectDocument(project.id);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<ProjectDocument | null>(null);
  const [attachDoc, setAttachDoc] = useState<ProjectDocument | null>(null);
  const [trashDoc, setTrashDoc] = useState<ProjectDocument | null>(null);

  const documents =
    documentsQuery.data?.pages.flatMap((page) => page.documents) ?? [];
  const documentsTotal = documentsQuery.data?.pages.at(-1)?.total ?? 0;
  const threadNameById = new Map(
    threads.map((thread) => [
      thread.thread_id,
      thread.display_name?.trim() ? thread.display_name : t.projects.untitled,
    ]),
  );

  // One file per request (§17.2); the loop serializes multi-file drops.
  const uploadFiles = async (files: File[]) => {
    if (files.length === 0 || isArchived) {
      return;
    }
    setIsUploading(true);
    try {
      for (const file of files) {
        try {
          await uploadDocument.mutateAsync({ file });
        } catch (error) {
          toast.error(
            errorToastMessage(error, t.projects.uploadDocumentFailed),
          );
        }
      }
    } finally {
      setIsUploading(false);
    }
  };

  const handleConfirmTrash = () => {
    if (!trashDoc) {
      return;
    }
    deleteDocument.mutate(trashDoc.id, {
      onSuccess: () => setTrashDoc(null),
      onError: (error) => {
        toast.error(errorToastMessage(error, t.projects.deleteDocumentFailed));
      },
    });
  };

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-lg",
        isDragging && "outline-primary outline-2 outline-dashed",
      )}
      onDragOver={
        isArchived
          ? undefined
          : (event) => {
              event.preventDefault();
              setIsDragging(true);
            }
      }
      onDragLeave={isArchived ? undefined : () => setIsDragging(false)}
      onDrop={
        isArchived
          ? undefined
          : (event) => {
              event.preventDefault();
              setIsDragging(false);
              void uploadFiles(Array.from(event.dataTransfer.files));
            }
      }
      data-testid="project-documents-shelf"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col">
          <h2 className="text-muted-foreground text-sm font-medium">
            {t.projects.documentsShelf}
          </h2>
          {!isArchived && (
            <p className="text-muted-foreground text-xs">
              {t.projects.documentsShelfHint}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" asChild>
            <Link href="/workspace/trash">
              <Trash2 className="size-4" />
              {t.projects.viewTrash}
            </Link>
          </Button>
          {!isArchived && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                data-testid="project-documents-upload-input"
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  event.target.value = "";
                  void uploadFiles(files);
                }}
              />
              <Button
                variant="outline"
                size="sm"
                disabled={isUploading}
                onClick={() => fileInputRef.current?.click()}
              >
                {isUploading ? (
                  <LoaderIcon className="size-4 animate-spin" />
                ) : (
                  <Upload className="size-4" />
                )}
                {isUploading
                  ? t.projects.uploadingDocuments
                  : t.projects.uploadDocuments}
              </Button>
            </>
          )}
        </div>
      </div>

      {documentsQuery.isError ? (
        <div role="alert" className="p-4 text-center text-sm">
          <p>{t.projects.documentsLoadFailed}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void documentsQuery.refetch()}
          >
            {t.trash.retry}
          </Button>
        </div>
      ) : !documentsQuery.isLoading && documents.length === 0 ? (
        <Empty className="border py-12">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FileText />
            </EmptyMedia>
            <EmptyTitle>{t.projects.documentsEmptyTitle}</EmptyTitle>
            <EmptyDescription>{t.projects.documentsEmptyHint}</EmptyDescription>
            <EmptyDescription>
              {t.projects.interimMemoryNotice}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <ul className="flex w-full flex-col gap-2">
          {documents.map((document) => (
            <ProjectDocumentRow
              key={document.id}
              project={project}
              document={document}
              isArchived={isArchived}
              provenance={
                document.source_thread_id
                  ? t.projects.documentFromThread(
                      threadNameById.get(document.source_thread_id) ??
                        t.projects.untitled,
                      document.source_kind === "output"
                        ? t.projects.documentKindOutput
                        : t.projects.documentKindUpload,
                    )
                  : null
              }
              onPreview={() => setPreviewDoc(document)}
              onAttach={() => setAttachDoc(document)}
              onTrash={() => setTrashDoc(document)}
            />
          ))}
        </ul>
      )}

      {!documentsQuery.isError && documents.length > 0 && (
        <div className="flex flex-col items-center gap-1">
          <p className="text-muted-foreground text-xs">
            {t.common.showingOf(documents.length, documentsTotal)}
          </p>
          {documentsQuery.hasNextPage && (
            <Button
              variant="ghost"
              size="sm"
              className="text-xs"
              disabled={documentsQuery.isFetchingNextPage}
              onClick={() => void documentsQuery.fetchNextPage()}
              data-testid="project-documents-load-more"
            >
              {documentsQuery.isFetchingNextPage
                ? t.chats.loadingMore
                : t.common.loadMore}
            </Button>
          )}
        </div>
      )}
      <DocumentPreviewDialog
        project={project}
        document={previewDoc}
        onClose={() => setPreviewDoc(null)}
      />
      <AttachToThreadDialog
        document={attachDoc}
        isPending={attachDocument.isPending}
        onClose={() => setAttachDoc(null)}
        onAttach={(thread) => {
          if (!attachDoc) {
            return;
          }
          attachDocument.mutate(
            { documentId: attachDoc.id, threadId: thread.thread_id },
            {
              onSuccess: (result) => {
                // The server-side ingestion completed, so the composer of
                // the target thread receives a *completed* attachment (§9).
                stageProjectAttachment(thread.thread_id, result);
                toast.success(t.projects.attachedToThread(result.filename));
                setAttachDoc(null);
                router.push(pathOfThread(thread));
              },
              onError: (error) => {
                toast.error(errorToastMessage(error, t.projects.attachFailed));
              },
            },
          );
        }}
      />
      <Dialog
        open={trashDoc !== null}
        onOpenChange={(open) => !open && setTrashDoc(null)}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.projects.moveDocumentToTrashTitle}</DialogTitle>
            <DialogDescription>
              {trashDoc &&
                t.projects.moveDocumentToTrashConfirm(
                  trashDoc.name,
                  trashRetentionDays,
                )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTrashDoc(null)}>
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              disabled={deleteDocument.isPending}
              onClick={handleConfirmTrash}
            >
              {t.projects.moveDocumentToTrash}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ProjectDocumentRow({
  project,
  document,
  isArchived,
  provenance,
  onPreview,
  onAttach,
  onTrash,
}: {
  project: Project;
  document: ProjectDocument;
  isArchived: boolean;
  provenance: string | null;
  onPreview: () => void;
  onAttach: () => void;
  onTrash: () => void;
}) {
  const { t } = useI18n();
  if (document.content_missing) {
    // §11: the list response's server-side integrity flag is authoritative —
    // a row whose bytes are gone renders as content missing at list render,
    // with move-to-trash as its only document action in active projects.
    return (
      <li className="flex items-center gap-3 rounded-md border p-3">
        {getFileIcon(document.name, "size-5 shrink-0")}
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="truncate text-sm">{document.name}</span>
          <Badge variant="destructive" data-testid="content-missing-badge">
            {t.projects.contentMissing}
          </Badge>
        </div>
        {!isArchived && (
          <Button variant="ghost" size="sm" onClick={onTrash}>
            <Trash2 className="size-4" />
            {t.projects.moveDocumentToTrash}
          </Button>
        )}
      </li>
    );
  }
  return (
    <li className="flex items-center gap-3 rounded-md border p-3">
      {getFileIcon(document.name, "size-5 shrink-0")}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium">{document.name}</span>
          {provenance && (
            <Badge variant="secondary" className="shrink-0">
              {provenance}
            </Badge>
          )}
        </div>
        <div className="text-muted-foreground text-xs">
          {formatArtifactBytes(document.size_bytes)}
          {" · "}
          {formatTimeAgo(document.updated_at)}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button variant="ghost" size="sm" onClick={onPreview}>
          {t.common.preview}
        </Button>
        <Button variant="ghost" size="sm" asChild>
          <a
            href={urlOfProjectDocumentContent(project.id, document.id, {
              download: true,
            })}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t.common.download}
          </a>
        </Button>
        <Button variant="ghost" size="sm" onClick={onAttach}>
          <Paperclip className="size-4" />
          {t.projects.attachToThread}
        </Button>
        {!isArchived && (
          <Button variant="ghost" size="sm" onClick={onTrash}>
            <Trash2 className="size-4" />
            {t.projects.moveDocumentToTrash}
          </Button>
        )}
      </div>
    </li>
  );
}

function DocumentPreviewDialog({
  project,
  document,
  onClose,
}: {
  project: Project;
  document: ProjectDocument | null;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [preview, setPreview] = useState<ProjectDocumentPreview | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!document) {
      return;
    }
    let cancelled = false;
    setPreview(null);
    setFailed(false);
    fetchProjectDocumentPreview(project.id, document.id)
      .then((result) => {
        if (!cancelled) {
          setPreview(result);
        }
      })
      .catch(() => {
        // Any failure — including a 409 ``content_missing`` — surfaces as
        // the in-dialog error. The row's missing badge comes from the list
        // response's server-side ``content_missing`` flag, not from a
        // preview probe.
        if (!cancelled) {
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [project.id, document]);

  const language = document
    ? (resolveStoredArtifactLanguage(document.name) ?? "text")
    : "text";
  const previewable =
    language === "markdown" ||
    language === "html" ||
    getTabularDelimiter(language) !== null;
  const contentUrl = document
    ? urlOfProjectDocumentContent(project.id, document.id)
    : "";
  const downloadUrl = document
    ? urlOfProjectDocumentContent(project.id, document.id, { download: true })
    : "";

  return (
    <Dialog
      open={document !== null}
      onOpenChange={(open) => !open && onClose()}
    >
      <DialogContent className="flex h-[70vh] flex-col sm:max-w-[720px]">
        <DialogHeader>
          <DialogTitle className="truncate">{document?.name ?? ""}</DialogTitle>
        </DialogHeader>
        {preview?.kind === "text" && preview.truncated && (
          <div
            className="border-border bg-muted/40 flex shrink-0 items-center justify-between gap-3 rounded-md border px-4 py-2 text-sm"
            data-testid="project-document-preview-truncated"
          >
            <span className="text-muted-foreground">
              {t.artifactPreview.limited(
                formatArtifactBytes(preview.previewBytes) ?? "1 MiB",
                formatArtifactBytes(preview.totalBytes),
              )}
            </span>
            <Button size="sm" variant="outline" asChild>
              <a href={contentUrl} target="_blank" rel="noopener noreferrer">
                {t.artifactPreview.loadFullFile}
              </a>
            </Button>
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-auto rounded-md border">
          {failed ? (
            <div className="text-muted-foreground p-4 text-sm">
              {t.projects.documentsLoadFailed}
            </div>
          ) : preview === null ? (
            <div className="text-muted-foreground flex items-center gap-2 p-4 text-sm">
              <LoaderIcon className="size-4 animate-spin" />
              {t.common.loading}
            </div>
          ) : preview.kind === "binary" ? (
            // Browser-viewable binary (image/audio/video): the sandboxed
            // iframe loads the content URL itself, the bytes are never
            // text-decoded.
            <iframe
              className="size-full border-0"
              sandbox=""
              src={contentUrl}
              title={document?.name ?? ""}
              data-testid="project-document-preview-frame"
            />
          ) : preview.kind === "pdf" ? (
            <div className="flex size-full flex-col">
              <div className="flex shrink-0 items-center justify-end gap-1 border-b px-2 py-1">
                <Button variant="ghost" size="sm" asChild>
                  <a
                    href={contentUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="project-document-preview-open-tab"
                  >
                    {t.common.openInNewWindow}
                  </a>
                </Button>
                <Button variant="ghost" size="sm" asChild>
                  <a
                    href={downloadUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t.common.download}
                  </a>
                </Button>
              </div>
              {/* PDFs render WITHOUT the sandbox attribute: Chromium blocks
                  its built-in PDF viewer inside ``sandbox=""``. Safe because
                  the endpoint declares ``application/pdf`` and sends
                  ``X-Content-Type-Options: nosniff``, so the bytes cannot be
                  reinterpreted as active markup, and the PDFium viewer
                  exposes no same-origin script surface. Same mechanism as
                  the artifact detail view. */}
              <iframe
                className="min-h-0 flex-1 border-0"
                src={contentUrl}
                title={document?.name ?? ""}
                data-testid="project-document-preview-frame"
              />
            </div>
          ) : preview.kind === "unsupported" ? (
            <div className="flex size-full items-center justify-center p-6">
              <div className="flex max-w-sm flex-col items-center gap-4 text-center">
                <div className="text-muted-foreground">
                  {document && getFileIcon(document.name, "size-12")}
                </div>
                <p className="text-muted-foreground text-sm">
                  {t.projects.previewUnsupported}
                </p>
                <Button asChild>
                  <a
                    href={downloadUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t.common.download}
                  </a>
                </Button>
              </div>
            </div>
          ) : previewable ? (
            <ArtifactFilePreview
              content={preview.content}
              language={language}
              scrollKey={document?.id ?? ""}
              truncated={preview.truncated}
            />
          ) : (
            <pre className="p-4 text-xs whitespace-pre-wrap">
              {preview.content}
            </pre>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function AttachToThreadDialog({
  document,
  isPending,
  onClose,
  onAttach,
}: {
  document: ProjectDocument | null;
  isPending: boolean;
  onClose: () => void;
  onAttach: (thread: AgentThread) => void;
}) {
  const { t } = useI18n();
  // Server-side archived filtering plus offset paging (the threads API
  // honors ``archived`` and ``limit``/``offset``): archived chats never
  // occupy a slot, and each page keeps loading raw rows until it fills or
  // the backend is exhausted.
  const threadsQuery = useInfiniteThreads({
    archived:
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? undefined : false,
  });
  const writableThreads = (threadsQuery.data?.pages ?? [])
    .flatMap((page) => page)
    .filter((thread) => !isThreadArchived(thread));
  return (
    <Dialog
      open={document !== null}
      onOpenChange={(open) => !open && onClose()}
    >
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{t.projects.attachDialogTitle}</DialogTitle>
          <DialogDescription>{t.projects.attachDialogHint}</DialogDescription>
        </DialogHeader>
        <div className="flex max-h-80 flex-col gap-1 overflow-auto">
          {threadsQuery.isLoading ? (
            <div className="text-muted-foreground flex items-center gap-2 p-2 text-sm">
              <LoaderIcon className="size-4 animate-spin" />
              {t.common.loading}
            </div>
          ) : writableThreads.length === 0 ? (
            <p className="text-muted-foreground p-2 text-sm">
              {t.projects.attachNoThreads}
            </p>
          ) : (
            writableThreads.map((thread) => (
              <Button
                key={thread.thread_id}
                variant="ghost"
                className="justify-start"
                disabled={isPending}
                onClick={() => onAttach(thread)}
              >
                <span className="truncate">{titleOfThread(thread)}</span>
              </Button>
            ))
          )}
          {threadsQuery.hasNextPage && (
            <Button
              variant="ghost"
              size="sm"
              className="self-center text-xs"
              disabled={threadsQuery.isFetchingNextPage}
              onClick={() => void threadsQuery.fetchNextPage()}
              data-testid="attach-thread-load-more"
            >
              {threadsQuery.isFetchingNextPage
                ? t.chats.loadingMore
                : t.common.loadMore}
            </Button>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t.common.cancel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProjectConversationFiles({ project }: { project: Project }) {
  const { t } = useI18n();
  const isArchived = project.status === "archived";
  // The API's maximum per-thread file cap: minimizes truncation frequency.
  // When a thread still exceeds it, the group renders a notice linking to
  // the thread's own views instead of silently hiding the omitted files.
  // The infinite query keeps every loaded page subscribed, so invalidation
  // or window-focus refetch refreshes them all — a member thread moved or
  // deleted between pages can never leave a stale group behind or duplicate
  // groups across a shifted page boundary.
  const threadFilesQuery = useInfiniteProjectThreadFiles(project.id, {
    file_limit: 200,
  });

  const groups =
    threadFilesQuery.data?.pages.flatMap((page) => page.groups) ?? [];

  return (
    <div className="flex flex-col gap-3" data-testid="project-thread-files">
      <h2 className="text-muted-foreground text-sm font-medium">
        {t.projects.conversationFiles}
      </h2>
      {threadFilesQuery.isError ? (
        <div role="alert" className="p-4 text-center text-sm">
          <p>{t.projects.threadFilesLoadFailed}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void threadFilesQuery.refetch()}
          >
            {t.trash.retry}
          </Button>
        </div>
      ) : !threadFilesQuery.isLoading && groups.length === 0 ? (
        <p className="text-muted-foreground p-4 text-sm">
          {t.projects.conversationFilesEmpty}
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {groups.map((group) => (
            <ConversationFileGroup
              key={group.thread_id}
              project={project}
              group={group}
              isArchived={isArchived}
            />
          ))}
        </div>
      )}
      {threadFilesQuery.hasNextPage && (
        <Button
          variant="ghost"
          size="sm"
          className="self-center text-xs"
          disabled={threadFilesQuery.isFetchingNextPage}
          onClick={() => void threadFilesQuery.fetchNextPage()}
          data-testid="project-thread-files-load-more"
        >
          {threadFilesQuery.isFetchingNextPage
            ? t.chats.loadingMore
            : t.common.loadMore}
        </Button>
      )}
    </div>
  );
}

function ConversationFileGroup({
  project,
  group,
  isArchived,
}: {
  project: Project;
  group: ProjectThreadFileGroup;
  isArchived: boolean;
}) {
  const { t } = useI18n();
  const promoteFile = usePromoteThreadFile(project.id);
  const [saveTarget, setSaveTarget] = useState<ProjectThreadFile | null>(null);
  const [shelfName, setShelfName] = useState("");

  const openSaveDialog = (file: ProjectThreadFile) => {
    setSaveTarget(file);
    setShelfName(file.name);
  };

  const handleSave = () => {
    if (!saveTarget) {
      return;
    }
    const trimmed = shelfName.trim();
    promoteFile.mutate(
      {
        thread_id: group.thread_id,
        kind: saveTarget.kind,
        name: saveTarget.name,
        ...(trimmed && trimmed !== saveTarget.name
          ? { shelf_name: trimmed }
          : {}),
      },
      {
        onSuccess: (result) => {
          toast.success(t.projects.savedToProject(result.document.name));
          setSaveTarget(null);
        },
        onError: (error) => {
          toast.error(errorToastMessage(error, t.projects.saveToProjectFailed));
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="text-sm font-medium">{group.display_name}</div>
      <ul className="flex w-full flex-col gap-1">
        {group.files.map((file) => {
          const previewUrl = resolveArtifactOpenURL({
            filepath: `/mnt/user-data/${file.kind === "upload" ? "uploads" : "outputs"}/${file.name}`,
            threadId: group.thread_id,
          });
          return (
            <li
              key={`${file.kind}:${file.name}`}
              className="flex items-center gap-3 rounded-md border p-2"
            >
              {getFileIcon(file.name, "size-5 shrink-0")}
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm">{file.name}</span>
                <span className="text-muted-foreground text-xs">
                  {formatArtifactBytes(file.size_bytes)}
                  {" · "}
                  {formatTimeAgo(file.modified_at)}
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button variant="ghost" size="sm" asChild>
                  <a
                    href={previewUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t.common.preview}
                  </a>
                </Button>
                {!isArchived && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => openSaveDialog(file)}
                  >
                    {t.projects.saveToProject}
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {group.truncated && (
        // The API caps each thread at file_limit files (uploads first, then
        // outputs) and there is no per-thread file paging — the omitted files
        // stay reachable through the thread's own chat/artifacts views.
        <p
          className="text-muted-foreground flex flex-wrap items-center gap-1.5 text-xs"
          data-testid="thread-files-truncated"
        >
          {t.projects.threadFilesTruncated(group.files.length)}
          <Link
            href={pathOfThread(group.thread_id)}
            className="underline underline-offset-4"
          >
            {t.projects.threadFilesBrowseInThread}
          </Link>
        </p>
      )}

      <Dialog
        open={saveTarget !== null}
        onOpenChange={(open) => !open && setSaveTarget(null)}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.projects.saveToProject}</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-2 py-2">
            <label
              htmlFor={`shelf-name-${group.thread_id}`}
              className="text-muted-foreground text-xs"
            >
              {t.projects.shelfNameLabel}
            </label>
            <Input
              id={`shelf-name-${group.thread_id}`}
              value={shelfName}
              onChange={(event) => setShelfName(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSaveTarget(null)}>
              {t.common.cancel}
            </Button>
            <Button
              disabled={!shelfName.trim() || promoteFile.isPending}
              onClick={handleSave}
            >
              {t.projects.saveToProject}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
