"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  CheckCircle2,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  UploadCloud,
} from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  createDataset,
  KnowledgeError,
  parseDocument,
  uploadDocument,
  type Dataset,
  type KnowledgeDocument,
} from "@/core/knowledge-base/api";
import {
  useKnowledgeDatasets,
  useKnowledgeDocuments,
} from "@/core/knowledge-base/hooks";
import { knowledgeMessages } from "@/core/knowledge-base/messages";
import { cn } from "@/lib/utils";

type Copy = (typeof knowledgeMessages)["en-US"];
function errorText(error: unknown, copy: Copy) {
  const code = error instanceof KnowledgeError ? error.code : "request_failed";
  return (
    copy.errors[code as keyof typeof copy.errors] ?? copy.errors.request_failed
  );
}

export default function KnowledgeBasePage() {
  const { locale } = useI18n();
  const copy = knowledgeMessages[locale];
  const datasets = useKnowledgeDatasets();
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const selected =
    datasets.data?.datasets.find((item) => item.id === selectedId) ??
    datasets.data?.datasets[0];

  async function create() {
    if (saving || !name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const dataset = await createDataset(name.trim());
      await datasets.refetch();
      setSelectedId(dataset.id);
      setName("");
      setCreating(false);
    } catch (failure) {
      setError(failure);
    } finally {
      setSaving(false);
    }
  }

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-y-auto">
        <div className="w-full max-w-6xl space-y-6 px-4 py-6 sm:px-8 sm:py-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <h1 className="text-2xl font-semibold">{copy.title}</h1>
              <p className="text-muted-foreground max-w-prose text-sm">
                {copy.description}
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={datasets.isFetching || busy || saving}
                onClick={() => {
                  void datasets.refetch();
                }}
              >
                <RefreshCw className="size-4" />
                {copy.refresh}
              </Button>
              {datasets.data?.can_create && (
                <Button
                  disabled={busy || saving}
                  onClick={() => setCreating(!creating)}
                >
                  <Plus className="size-4" />
                  {copy.create}
                </Button>
              )}
            </div>
          </div>
          {datasets.isLoading && (
            <div aria-label={copy.loading} className="space-y-3">
              <Skeleton className="h-10 w-72" />
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-48 w-full" />
            </div>
          )}
          {datasets.error && (
            <p
              role="alert"
              className="bg-destructive/10 text-destructive rounded-lg p-4 text-sm"
            >
              {errorText(datasets.error, copy)}
            </p>
          )}
          {creating && datasets.data?.can_create && (
            <form
              className="flex flex-wrap items-end gap-3 rounded-lg border p-4"
              onSubmit={(event) => {
                event.preventDefault();
                void create();
              }}
            >
              <div className="min-w-48 flex-1 space-y-2">
                <label htmlFor="knowledge-name" className="text-sm font-medium">
                  {copy.name}
                </label>
                <Input
                  id="knowledge-name"
                  value={name}
                  maxLength={128}
                  placeholder={copy.namePlaceholder}
                  onChange={(event) => setName(event.target.value)}
                  disabled={saving}
                  autoFocus
                />
              </div>
              <Button type="submit" disabled={saving || !name.trim()}>
                {saving && (
                  <Loader2 className="size-4 motion-safe:animate-spin" />
                )}
                {copy.save}
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={saving}
                onClick={() => {
                  setCreating(false);
                  setError(null);
                }}
              >
                {copy.cancel}
              </Button>
              {error != null && (
                <p role="alert" className="text-destructive w-full text-sm">
                  {errorText(error, copy)}
                </p>
              )}
            </form>
          )}
          {datasets.data && !datasets.error && (
            <>
              <div className="text-muted-foreground flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
                <span className="flex items-center gap-1.5">
                  <CheckCircle2 className="size-3.5 text-green-700 dark:text-green-400" />
                  {copy.connected}
                </span>
                <span>{copy.shared}</span>
              </div>
              {selected ? (
                <>
                  <div className="max-w-md space-y-2">
                    <label
                      className="text-sm font-medium"
                      htmlFor="knowledge-dataset"
                    >
                      {copy.choose}
                    </label>
                    <select
                      id="knowledge-dataset"
                      value={selected.id}
                      disabled={busy || saving}
                      onChange={(event) => setSelectedId(event.target.value)}
                      className="bg-background border-input focus-visible:ring-ring h-10 w-full rounded-md border px-3 text-sm focus-visible:ring-2 disabled:opacity-50"
                    >
                      {datasets.data.datasets.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <DatasetDocuments
                    key={selected.id}
                    dataset={selected}
                    canUpload={datasets.data.can_upload}
                    maxBytes={datasets.data.max_file_bytes}
                    copy={copy}
                    onBusy={setBusy}
                  />
                </>
              ) : (
                <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-16 text-center">
                  <BookOpen className="text-muted-foreground size-9" />
                  <h2 className="text-lg font-medium">{copy.emptyTitle}</h2>
                  <p className="text-muted-foreground text-sm">
                    {datasets.data.can_create ? copy.empty : copy.emptyReadonly}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

type UploadEntry = {
  name: string;
  state: "uploading" | "uploaded" | "parsePending" | "uploadFailed";
  detail?: string;
};
function DatasetDocuments({
  dataset,
  canUpload,
  maxBytes,
  copy,
  onBusy,
}: {
  dataset: Dataset;
  canUpload: boolean;
  maxBytes: number;
  copy: Copy;
  onBusy: (value: boolean) => void;
}) {
  const [page, setPage] = useState(1);
  const documents = useKnowledgeDocuments(dataset.id, page);
  const queryClient = useQueryClient();
  const [uploads, setUploads] = useState<UploadEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [parsing, setParsing] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const locked = useRef(false);
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["knowledge-base"] });
  };
  async function upload(files: File[]) {
    if (locked.current || !canUpload || files.length === 0) return;
    locked.current = true;
    setBusy(true);
    onBusy(true);
    setDragging(false);
    setActionError(null);
    setNotice("");
    setUploads(files.map((file) => ({ name: file.name, state: "uploading" })));
    try {
      for (const [index, file] of files.entries()) {
        let result: UploadEntry;
        try {
          if (file.size > maxBytes)
            throw new KnowledgeError("upload_too_large");
          if (file.size === 0) throw new KnowledgeError("invalid_upload");
          const response = await uploadDocument(dataset.id, file);
          result = {
            name: file.name,
            state: response.parsing_started ? "uploaded" : "parsePending",
          };
        } catch (failure) {
          result = {
            name: file.name,
            state: "uploadFailed",
            detail: errorText(failure, copy),
          };
        }
        setUploads((items) =>
          items.map((item, i) => (i === index ? result : item)),
        );
      }
      setPage(1);
      await refresh();
    } finally {
      locked.current = false;
      setBusy(false);
      onBusy(false);
      if (input.current) input.current.value = "";
    }
  }
  async function parse(doc: KnowledgeDocument) {
    if (locked.current) return;
    locked.current = true;
    setParsing(doc.id);
    onBusy(true);
    setActionError(null);
    setNotice("");
    try {
      await parseDocument(dataset.id, doc.id);
      setNotice(copy.parsingStarted);
      await refresh();
    } catch (failure) {
      setActionError(failure);
    } finally {
      locked.current = false;
      setParsing(null);
      onBusy(false);
    }
  }
  const disabled = busy || parsing !== null;
  return (
    <div className="space-y-5">
      {canUpload ? (
        <div
          onDragOver={(event) => {
            event.preventDefault();
            if (!disabled) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            if (!disabled) void upload(Array.from(event.dataTransfer.files));
          }}
          className={cn(
            "rounded-xl border border-dashed px-5 py-7 text-center transition-colors",
            dragging && "border-primary bg-primary/5",
          )}
        >
          <UploadCloud className="text-muted-foreground mx-auto mb-3 size-7" />
          <p className="mb-3 text-sm font-medium">
            {busy ? copy.uploading : copy.uploadHint}
          </p>
          <Button
            disabled={disabled}
            variant="outline"
            onClick={() => input.current?.click()}
          >
            {busy && <Loader2 className="size-4 motion-safe:animate-spin" />}
            {copy.upload}
          </Button>
          <input
            ref={input}
            type="file"
            multiple
            className="hidden"
            aria-label={copy.upload}
            disabled={disabled}
            onChange={(event) => {
              void upload(Array.from(event.target.files ?? []));
            }}
          />
          <p className="text-muted-foreground mx-auto mt-3 max-w-prose text-xs leading-relaxed">
            {copy.uploadLimit}
          </p>
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">{copy.readonly}</p>
      )}
      {uploads.length > 0 && (
        <div className="space-y-2 rounded-lg border p-4" aria-live="polite">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">{copy.upload}</span>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => setUploads([])}
            >
              {copy.clear}
            </Button>
          </div>
          {uploads.map((entry, index) => (
            <div
              key={index}
              className="flex flex-wrap justify-between gap-x-4 gap-y-1 text-sm"
            >
              <span className="min-w-0 break-all">{entry.name}</span>
              <span
                className={cn(
                  "text-muted-foreground",
                  entry.state === "uploadFailed" && "text-destructive",
                )}
              >
                {entry.detail ?? copy[entry.state]}
              </span>
            </div>
          ))}
        </div>
      )}
      {actionError != null && (
        <p role="alert" className="text-destructive text-sm">
          {errorText(actionError, copy)}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">
          {copy.documents}
          <span className="text-muted-foreground ml-2 font-normal">
            {documents.data?.total ?? "—"}
          </span>
        </h2>
        <Button
          variant="ghost"
          size="sm"
          disabled={documents.isFetching || disabled}
          onClick={() => {
            void documents.refetch();
          }}
        >
          <RefreshCw className="size-4" />
          {copy.refresh}
        </Button>
      </div>
      {documents.error && (
        <p role="alert" className="text-destructive text-sm">
          {errorText(documents.error, copy)}
        </p>
      )}
      {documents.isLoading && <Skeleton className="h-40 w-full" />}
      {documents.data?.documents.length === 0 && (
        <div className="rounded-lg border px-5 py-12 text-center">
          <FileText className="text-muted-foreground mx-auto mb-3 size-7" />
          <h3 className="font-medium">{copy.noDocuments}</h3>
          <p className="text-muted-foreground mx-auto mt-2 max-w-prose text-sm">
            {copy.noDocumentsHint}
          </p>
        </div>
      )}
      {!!documents.data?.documents.length && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                {[
                  copy.filename,
                  copy.size,
                  copy.statusLabel,
                  copy.chunks,
                  ...(canUpload ? [copy.actions] : []),
                ].map((heading) => (
                  <th key={heading} className="px-4 py-3 font-medium">
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {documents.data.documents.map((doc) => (
                <tr key={doc.id}>
                  <td className="max-w-72 px-4 py-4 break-words">{doc.name}</td>
                  <td className="text-muted-foreground px-4 py-4 whitespace-nowrap">
                    {doc.size < 1024
                      ? `${doc.size} B`
                      : doc.size < 1024 * 1024
                        ? `${(doc.size / 1024).toFixed(1)} KiB`
                        : `${(doc.size / 1024 / 1024).toFixed(1)} MiB`}
                  </td>
                  <td className="px-4 py-4">
                    <span
                      className={cn(
                        "bg-muted inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs whitespace-nowrap",
                        doc.status === "ready" &&
                          "bg-green-500/10 text-green-800 dark:text-green-300",
                        doc.status === "failed" &&
                          "bg-destructive/10 text-destructive",
                      )}
                    >
                      {doc.status === "parsing" && (
                        <Loader2 className="size-3 motion-safe:animate-spin" />
                      )}
                      {copy.statuses[doc.status]}
                      {doc.status === "parsing" &&
                        ` ${Math.round(doc.progress * 100)}%`}
                    </span>
                    {doc.status === "failed" && (
                      <p className="text-muted-foreground mt-2 max-w-56 text-xs">
                        {copy.failedHint}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-4 tabular-nums">{doc.chunk_count}</td>
                  {canUpload && (
                    <td className="px-4 py-4">
                      {["pending", "failed", "cancelled"].includes(
                        doc.status,
                      ) && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={disabled}
                          onClick={() => {
                            void parse(doc);
                          }}
                        >
                          {parsing === doc.id && (
                            <Loader2 className="size-3 motion-safe:animate-spin" />
                          )}
                          {doc.status === "pending"
                            ? copy.parse
                            : copy.retryParse}
                        </Button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!!documents.data && (documents.data.total > 20 || page > 1) && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span className="text-muted-foreground">
            {copy.page} {page} · {documents.data.total} {copy.total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || disabled}
              onClick={() => setPage(page - 1)}
            >
              {copy.previous}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page * 20 >= documents.data.total || disabled}
              onClick={() => setPage(page + 1)}
            >
              {copy.next}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
