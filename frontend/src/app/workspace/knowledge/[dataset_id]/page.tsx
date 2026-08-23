"use client";

import {
  ArrowLeftIcon,
  CheckCircle2Icon,
  ExternalLinkIcon,
  FileTextIcon,
  LoaderCircleIcon,
  Trash2Icon,
  UploadCloudIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { Progress } from "@/components/ui/progress";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  documentRunKind,
  formatKnowledgeFileSize,
  useDeleteKnowledgeDocuments,
  useKnowledgeBaseEnabled,
  useKnowledgeDatasets,
  useKnowledgeDocuments,
  useKnowledgeEvents,
  useParseKnowledgeDocuments,
  useUploadKnowledgeDocuments,
  validateKnowledgeUpload,
  type DocumentRunKind,
  type KnowledgeDocument,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

import { DatasetStatus, SharedKnowledgeBanner } from "../_components";

function replaceCount(template: string, count: number): string {
  return template.replace("{count}", String(count));
}

function formatTimestamp(value: number | undefined, locale: string): string {
  if (!value) return "—";
  const milliseconds = value < 10_000_000_000 ? value * 1000 : value;
  const date = new Date(milliseconds);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function DocumentStatus({ document }: { document: KnowledgeDocument }) {
  const { t } = useI18n();
  const kind = documentRunKind(document.run);
  const labels: Record<DocumentRunKind, string> = {
    unparsed: t.knowledge.status.unparsed,
    parsing: t.knowledge.status.parsing,
    ready: t.knowledge.status.ready,
    failed: t.knowledge.status.failed,
    cancelled: t.knowledge.status.cancelled,
  };
  const variant = kind === "failed" ? "destructive" : "outline";
  return (
    <div className="flex min-w-24 flex-col gap-1.5">
      <Badge
        variant={variant}
        className={cn(
          kind === "ready" &&
            "border-emerald-500/40 text-emerald-700 dark:text-emerald-300",
          kind === "parsing" &&
            "border-blue-500/40 text-blue-700 dark:text-blue-300",
        )}
      >
        {kind === "parsing" && <LoaderCircleIcon className="animate-spin" />}
        {kind === "ready" && <CheckCircle2Icon />}
        {labels[kind]}
      </Badge>
      {kind === "parsing" && typeof document.progress === "number" && (
        <Progress
          className="h-1"
          value={
            document.progress <= 1 ? document.progress * 100 : document.progress
          }
        />
      )}
    </div>
  );
}

export default function KnowledgeDatasetPage() {
  const params = useParams<{ dataset_id: string }>();
  const datasetId = params.dataset_id;
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const { enabled, managementUrl } = useKnowledgeBaseEnabled();
  const datasetsQuery = useKnowledgeDatasets(enabled);
  const documentsQuery = useKnowledgeDocuments(datasetId, enabled);
  const uploadDocuments = useUploadKnowledgeDocuments(datasetId);
  const parseDocuments = useParseKnowledgeDocuments(datasetId);
  const deleteDocuments = useDeleteKnowledgeDocuments(datasetId);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dragActive, setDragActive] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const isAdmin = user?.system_role === "admin";
  const dataset = datasetsQuery.data?.find((item) => item.id === datasetId);
  const documents = useMemo(
    () => documentsQuery.data?.documents ?? [],
    [documentsQuery.data?.documents],
  );

  useKnowledgeEvents(enabled);

  useEffect(() => {
    document.title = `${dataset?.name ?? t.knowledge.title} - ${t.pages.appName}`;
  }, [dataset?.name, t.knowledge.title, t.pages.appName]);

  useEffect(() => {
    const ids = new Set(documents.map((document) => document.id));
    setSelected(
      (current) =>
        new Set([...current].filter((documentId) => ids.has(documentId))),
    );
  }, [documents]);

  const toggleDocument = (documentId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(documentId)) next.delete(documentId);
      else next.add(documentId);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected((current) =>
      current.size === documents.length
        ? new Set()
        : new Set(documents.map((document) => document.id)),
    );
  };

  const uploadErrorMessage = (
    error: ReturnType<typeof validateKnowledgeUpload>,
  ): string | null => {
    if (!error) return null;
    return {
      no_files: t.knowledge.upload.noFiles,
      too_many_files: t.knowledge.upload.tooManyFiles,
      file_too_large: t.knowledge.upload.fileTooLarge,
      request_too_large: t.knowledge.upload.requestTooLarge,
    }[error];
  };

  const handleFiles = async (files: readonly File[]) => {
    const error = validateKnowledgeUpload(files);
    if (error) {
      toast.error(uploadErrorMessage(error));
      return;
    }
    try {
      const uploaded = await uploadDocuments.mutateAsync(files);
      setSelected(new Set(uploaded.map((document) => document.id)));
      if (inputRef.current) inputRef.current.value = "";
    } catch {
      // Mutation owns the sanitized toast error.
    }
  };

  const startParsing = async () => {
    if (!selected.size) return;
    try {
      await parseDocuments.mutateAsync([...selected]);
    } catch {
      // Mutation owns the sanitized toast error.
    }
  };

  const confirmDelete = async () => {
    if (!selected.size) return;
    try {
      await deleteDocuments.mutateAsync([...selected]);
      setSelected(new Set());
      setDeleteOpen(false);
    } catch {
      // Mutation owns the sanitized toast error; keep confirmation open.
    }
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto flex w-full max-w-(--container-width-md) flex-col gap-5 p-4 sm:p-6">
          <Button asChild variant="ghost" size="sm" className="w-fit">
            <Link href="/workspace/knowledge">
              <ArrowLeftIcon />
              {t.knowledge.detail.back}
            </Link>
          </Button>

          <SharedKnowledgeBanner />

          {datasetsQuery.isPending ? (
            <div className="text-muted-foreground py-12 text-center text-sm">
              {t.common.loading}
            </div>
          ) : !dataset ? (
            <Empty className="border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FileTextIcon />
                </EmptyMedia>
                <EmptyTitle>{t.knowledge.detail.notFound}</EmptyTitle>
              </EmptyHeader>
            </Empty>
          ) : (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h1 className="truncate text-2xl font-semibold">
                    {dataset.name}
                  </h1>
                  <p className="text-muted-foreground mt-1 text-sm">
                    {dataset.description?.trim() ? dataset.description : "—"}
                  </p>
                </div>
                <DatasetStatus dataset={dataset} />
              </div>

              <Card>
                <CardHeader>
                  <CardTitle>{t.knowledge.upload.title}</CardTitle>
                  <CardDescription>
                    {t.knowledge.upload.description}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <label
                    className={cn(
                      "flex min-h-40 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-6 text-center transition-colors",
                      dragActive
                        ? "border-primary bg-primary/5"
                        : "border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/30",
                      uploadDocuments.isPending &&
                        "pointer-events-none opacity-60",
                    )}
                    onDragEnter={(event) => {
                      event.preventDefault();
                      setDragActive(true);
                    }}
                    onDragOver={(event) => event.preventDefault()}
                    onDragLeave={(event) => {
                      event.preventDefault();
                      if (event.currentTarget === event.target) {
                        setDragActive(false);
                      }
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      setDragActive(false);
                      void handleFiles(Array.from(event.dataTransfer.files));
                    }}
                  >
                    {uploadDocuments.isPending ? (
                      <LoaderCircleIcon className="text-primary size-9 animate-spin" />
                    ) : (
                      <UploadCloudIcon className="text-muted-foreground size-9" />
                    )}
                    <span className="font-medium">
                      {uploadDocuments.isPending
                        ? t.knowledge.upload.uploading
                        : t.knowledge.upload.dropHere}
                    </span>
                    {!uploadDocuments.isPending && (
                      <span className="text-muted-foreground text-sm">
                        {t.knowledge.upload.browse}
                      </span>
                    )}
                    <input
                      ref={inputRef}
                      type="file"
                      multiple
                      className="sr-only"
                      disabled={uploadDocuments.isPending}
                      onChange={(event) =>
                        void handleFiles(Array.from(event.target.files ?? []))
                      }
                    />
                  </label>
                </CardContent>
              </Card>

              <Card data-testid="knowledge-documents">
                <CardHeader>
                  <CardTitle>{t.knowledge.detail.documents}</CardTitle>
                  <CardDescription>
                    {replaceCount(
                      t.knowledge.dataset.documents,
                      documentsQuery.data?.total ?? 0,
                    )}
                  </CardDescription>
                </CardHeader>
                <CardContent className="grid gap-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-muted-foreground text-sm">
                      {replaceCount(t.knowledge.detail.selected, selected.size)}
                    </span>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!selected.size || parseDocuments.isPending}
                        onClick={() => void startParsing()}
                      >
                        {parseDocuments.isPending && (
                          <LoaderCircleIcon className="animate-spin" />
                        )}
                        {parseDocuments.isPending
                          ? t.knowledge.detail.parsing
                          : t.knowledge.detail.parse}
                      </Button>
                      {isAdmin && (
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={!selected.size}
                          onClick={() => setDeleteOpen(true)}
                        >
                          <Trash2Icon />
                          {t.knowledge.detail.delete}
                        </Button>
                      )}
                    </div>
                  </div>

                  {documentsQuery.isPending ? (
                    <div className="text-muted-foreground py-10 text-center text-sm">
                      {t.common.loading}
                    </div>
                  ) : documentsQuery.isError ? (
                    <Empty className="border">
                      <EmptyHeader>
                        <EmptyTitle>{t.knowledge.loadFailed}</EmptyTitle>
                        <EmptyDescription>
                          {documentsQuery.error.message}
                        </EmptyDescription>
                      </EmptyHeader>
                      <Button
                        variant="outline"
                        onClick={() => void documentsQuery.refetch()}
                      >
                        {t.knowledge.retry}
                      </Button>
                    </Empty>
                  ) : documents.length ? (
                    <div className="overflow-x-auto rounded-lg border">
                      <table className="w-full min-w-180 text-left text-sm">
                        <thead className="bg-muted/50 border-b">
                          <tr>
                            <th className="w-12 p-3">
                              <input
                                type="checkbox"
                                aria-label={t.knowledge.detail.selectAll}
                                checked={
                                  documents.length > 0 &&
                                  selected.size === documents.length
                                }
                                onChange={toggleAll}
                                className="accent-primary size-4"
                              />
                            </th>
                            <th className="p-3 font-medium">
                              {t.knowledge.detail.name}
                            </th>
                            <th className="p-3 font-medium">
                              {t.knowledge.detail.size}
                            </th>
                            <th className="p-3 font-medium">
                              {t.knowledge.detail.chunks}
                            </th>
                            <th className="p-3 font-medium">
                              {t.knowledge.detail.status}
                            </th>
                            <th className="p-3 font-medium">
                              {t.knowledge.detail.updated}
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y">
                          {documents.map((document) => (
                            <tr key={document.id}>
                              <td className="p-3">
                                <input
                                  type="checkbox"
                                  aria-label={document.name}
                                  checked={selected.has(document.id)}
                                  onChange={() => toggleDocument(document.id)}
                                  className="accent-primary size-4"
                                />
                              </td>
                              <td className="max-w-80 p-3 font-medium">
                                <span className="block truncate">
                                  {document.name}
                                </span>
                              </td>
                              <td className="text-muted-foreground p-3">
                                {formatKnowledgeFileSize(document.size)}
                              </td>
                              <td className="text-muted-foreground p-3">
                                {Number(document.chunk_count ?? 0)}
                              </td>
                              <td className="p-3">
                                <DocumentStatus document={document} />
                              </td>
                              <td className="text-muted-foreground p-3">
                                {formatTimestamp(document.update_time, locale)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <Empty className="border">
                      <EmptyHeader>
                        <EmptyMedia variant="icon">
                          <FileTextIcon />
                        </EmptyMedia>
                        <EmptyTitle>
                          {t.knowledge.detail.noDocuments}
                        </EmptyTitle>
                        <EmptyDescription>
                          {t.knowledge.detail.noDocumentsDescription}
                        </EmptyDescription>
                      </EmptyHeader>
                    </Empty>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>{t.knowledge.ragflow.title}</CardTitle>
                  <CardDescription>
                    {t.knowledge.ragflow.description}
                  </CardDescription>
                </CardHeader>
                <CardContent className="grid gap-2">
                  {t.knowledge.ragflow.items.map((item) => (
                    <div
                      key={item}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm"
                    >
                      <span>{item}</span>
                      {managementUrl ? (
                        <Button asChild variant="link" size="sm">
                          <a
                            href={managementUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {t.knowledge.ragflow.open}
                            <ExternalLinkIcon />
                          </a>
                        </Button>
                      ) : (
                        <span className="text-muted-foreground text-xs">
                          {t.knowledge.ragflow.unavailable}
                        </span>
                      )}
                    </div>
                  ))}
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </WorkspaceBody>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.knowledge.detail.deleteTitle}</DialogTitle>
            <DialogDescription>
              {t.knowledge.detail.deleteDescription}
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm font-medium">
            {replaceCount(t.knowledge.detail.selected, selected.size)}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>
              {t.knowledge.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void confirmDelete()}
              disabled={deleteDocuments.isPending}
            >
              {deleteDocuments.isPending
                ? t.knowledge.detail.deleting
                : t.knowledge.detail.deleteConfirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </WorkspaceContainer>
  );
}
