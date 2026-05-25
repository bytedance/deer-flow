"use client";

import {
  FileTextIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import {
  useCreateDocument,
  useDeleteDocument,
  useDocumentIndexStatus,
  useDocuments,
  useReindexDocument,
  useSearchKnowledgeBase,
  useUpdateDocument,
  useUploadDocument,
} from "@/core/knowledge-base";
import type { KnowledgeBase, KnowledgeBaseDocument, SearchResultItem } from "@/core/knowledge-base";

import { KbIndexHealthCard } from "./kb-index-health-card";

interface KBDocumentsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  knowledgeBase: KnowledgeBase;
}

function isDocumentIndexing(status: string): boolean {
  return status === "pending" || status === "indexing";
}

function getDocumentStatusMeta(
  doc: KnowledgeBaseDocument,
  t: ReturnType<typeof useI18n>["t"],
): { label: string; variant: "secondary" | "destructive"; title?: string } | null {
  if (isDocumentIndexing(doc.index_status)) {
    return {
      label: t.knowledgeBase.statusIndexing,
      variant: "secondary",
    };
  }
  if (doc.index_status === "failed") {
    return {
      label: t.knowledgeBase.statusError,
      variant: "destructive",
      title: doc.index_error ?? t.knowledgeBase.statusError,
    };
  }
  return null;
}

export function KBDocumentsDialog({
  open,
  onOpenChange,
  knowledgeBase,
}: KBDocumentsDialogProps) {
  const { t } = useI18n();
  const { documents, isLoading } = useDocuments(knowledgeBase.id, {
    enabled: open,
  });
  const [showAddForm, setShowAddForm] = useState(false);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {knowledgeBase.name} — {t.knowledgeBase.documents}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <KbIndexHealthCard kbId={knowledgeBase.id} />

          <div className="flex items-center justify-between">
            <span className="text-muted-foreground text-sm">
              {documents.length} {t.knowledgeBase.documentCount}
            </span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowAddForm(true)}
            >
              <PlusIcon className="mr-1.5 h-3.5 w-3.5" />
              {t.knowledgeBase.addDocument}
            </Button>
          </div>

          {showAddForm && (
            <AddDocumentForm
              kbId={knowledgeBase.id}
              onDone={() => setShowAddForm(false)}
            />
          )}

          {isLoading ? (
            <div className="text-muted-foreground flex h-20 items-center justify-center text-sm">
              {t.common.loading}
            </div>
          ) : documents.length === 0 && !showAddForm ? (
            <div className="text-muted-foreground flex h-20 items-center justify-center text-sm">
              {t.knowledgeBase.emptyDescription}
            </div>
          ) : (
            <div className="flex max-h-80 flex-col gap-2 overflow-y-auto">
              {documents.map((doc) => (
                <DocumentRow
                  key={doc.id}
                  doc={doc}
                  kbId={knowledgeBase.id}
                />
              ))}
            </div>
          )}

          <SearchPreview kbId={knowledgeBase.id} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
function AddDocumentForm({
  kbId,
  onDone,
}: {
  kbId: string;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"text" | "upload">("text");
  const createDoc = useCreateDocument(kbId);
  const uploadDoc = useUploadDocument(kbId);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Track the just-uploaded document for index progress polling
  const [trackingDocId, setTrackingDocId] = useState<string | null>(null);
  const indexStatus = useDocumentIndexStatus(kbId, trackingDocId, {
    enabled: trackingDocId !== null,
  });

  async function handleTextSubmit() {
    if (!title.trim() || !content.trim()) return;
    try {
      await createDoc.mutateAsync({
        title: title.trim(),
        content: content.trim(),
      });
      onDone();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleFileSubmit() {
    if (!file) return;
    try {
      const doc = await uploadDoc.mutateAsync({
        file,
        title: title.trim() || undefined,
      });
      setTrackingDocId(doc.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  // When index status resolves to terminal, act accordingly
  const status = indexStatus.data?.index_status;
  const isTerminal = status === "indexed" || status === "failed";

  // Show upload progress tracker after successful upload
  if (trackingDocId) {
    const isIndexing = status === "pending" || status === "indexing";
    return (
      <div className="bg-muted/50 flex flex-col gap-3 rounded-lg border p-4">
        <div className="flex items-center gap-2">
          <FileTextIcon className="text-muted-foreground h-4 w-4" />
          <span className="text-sm font-medium truncate">
            {title || file?.name || trackingDocId}
          </span>
        </div>

        {isIndexing && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <RefreshCwIcon className="h-3.5 w-3.5 animate-spin" />
            <span>{t.knowledgeBase.indexingInProgress}</span>
          </div>
        )}

        {status === "indexed" && (
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">
              {indexStatus.data?.chunk_count ?? 0} {t.knowledgeBase.chunks}
            </Badge>
            <span className="text-sm text-muted-foreground">{t.knowledgeBase.indexComplete}</span>
          </div>
        )}

        {status === "failed" && (
          <div className="flex flex-col gap-2">
            <div className="text-destructive text-sm font-medium">
              {t.knowledgeBase.indexFailed}
            </div>
            {indexStatus.data?.index_error && (
              <p className="text-destructive/80 text-xs">{indexStatus.data.index_error}</p>
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setTrackingDocId(null);
                }}
              >
                {t.common.cancel}
              </Button>
            </div>
          </div>
        )}

        {isTerminal && (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={onDone}>
              {t.common.close}
            </Button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="bg-muted/50 flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex gap-2">
        <Button
          size="sm"
          variant={mode === "text" ? "default" : "outline"}
          onClick={() => setMode("text")}
        >
          <FileTextIcon className="mr-1.5 h-3.5 w-3.5" />
          {t.knowledgeBase.textInput}
        </Button>
        <Button
          size="sm"
          variant={mode === "upload" ? "default" : "outline"}
          onClick={() => setMode("upload")}
        >
          <UploadIcon className="mr-1.5 h-3.5 w-3.5" />
          {t.knowledgeBase.fileUpload}
        </Button>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="doc-title" className="text-sm font-medium">
          {t.knowledgeBase.documentTitle}
        </label>
        <Input
          id="doc-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t.knowledgeBase.documentTitlePlaceholder}
        />
      </div>

      {mode === "text" ? (
        <div className="flex flex-col gap-2">
          <label htmlFor="doc-content" className="text-sm font-medium">
            {t.knowledgeBase.documentContent}
          </label>
          <Textarea
            id="doc-content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={t.knowledgeBase.documentContentPlaceholder}
            rows={5}
          />
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <label htmlFor="doc-file" className="text-sm font-medium">
            {t.knowledgeBase.uploadFile}
          </label>
          <div
            className="flex cursor-pointer items-center gap-2 rounded-md border border-dashed p-4"
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
            }}
            role="button"
            tabIndex={0}
          >
            <UploadIcon className="text-muted-foreground h-5 w-5" />
            <span className="text-muted-foreground text-sm">
              {file ? file.name : t.knowledgeBase.uploadFilePlaceholder}
            </span>
          </div>
          <input
            ref={fileInputRef}
            id="doc-file"
            type="file"
            className="hidden"
            accept=".pdf,.doc,.docx,.md,.txt"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={onDone}>
          {t.common.cancel}
        </Button>
        {mode === "text" ? (
          <Button
            size="sm"
            onClick={handleTextSubmit}
            disabled={createDoc.isPending || !title.trim() || !content.trim()}
          >
            {createDoc.isPending ? t.knowledgeBase.creating : t.knowledgeBase.create}
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={handleFileSubmit}
            disabled={uploadDoc.isPending || !file}
          >
            {uploadDoc.isPending ? t.knowledgeBase.uploading : t.knowledgeBase.uploadFile}
          </Button>
        )}
      </div>
    </div>
  );
}

function DocumentRow({ doc, kbId }: { doc: KnowledgeBaseDocument; kbId: string }) {
  const { t } = useI18n();
  const deleteMutation = useDeleteDocument(kbId);
  const reindexMutation = useReindexDocument(kbId);
  const [editing, setEditing] = useState(false);
  const statusMeta = getDocumentStatusMeta(doc, t);
  const indexing = isDocumentIndexing(doc.index_status);
  const isFailed = doc.index_status === "failed";

  async function handleDelete() {
    if (!confirm(t.knowledgeBase.deleteDocumentConfirm)) return;
    try {
      await deleteMutation.mutateAsync(doc.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleReindex() {
    try {
      await reindexMutation.mutateAsync(doc.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  if (editing) {
    return (
      <EditDocumentForm
        kbId={kbId}
        doc={doc}
        onDone={() => setEditing(false)}
      />
    );
  }

  return (
    <div className="flex items-start justify-between gap-3 rounded-md border px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <FileTextIcon className="text-muted-foreground h-4 w-4 shrink-0" />
          <span className="truncate text-sm font-medium">{doc.title}</span>
          {statusMeta ? (
            <Badge
              variant={statusMeta.variant}
              className="shrink-0 text-xs"
              title={statusMeta.title}
            >
              {statusMeta.label}
            </Badge>
          ) : null}
          <Badge variant="outline" className="shrink-0 text-xs">
            {doc.chunk_count} {t.knowledgeBase.chunks}
          </Badge>
        </div>
        {isFailed && doc.index_error ? (
          <div className="mt-1.5 pl-6">
            <p className="text-destructive text-xs font-medium">
              {t.knowledgeBase.indexFailed}
            </p>
            <p
              className="text-destructive/70 mt-0.5 text-xs"
              title={doc.index_error}
            >
              {doc.index_error}
            </p>
            <Button
              size="sm"
              variant="outline"
              className="text-xs mt-1.5 h-7"
              onClick={handleReindex}
              disabled={reindexMutation.isPending}
            >
              <RefreshCwIcon
                className={`mr-1 h-3 w-3 ${reindexMutation.isPending ? "animate-spin" : ""}`}
              />
              {t.knowledgeBase.reindex}
            </Button>
          </div>
        ) : null}
      </div>
      <div className="flex shrink-0 gap-1">
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          onClick={() => setEditing(true)}
          title={t.knowledgeBase.editDocument}
        >
          <PencilIcon className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          onClick={handleReindex}
          disabled={reindexMutation.isPending || indexing}
          title={indexing ? t.knowledgeBase.reindexing : t.knowledgeBase.reindex}
        >
          <RefreshCwIcon
            className={`h-3.5 w-3.5 ${reindexMutation.isPending || indexing ? "animate-spin" : ""}`}
          />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="text-destructive hover:text-destructive h-7 w-7"
          onClick={handleDelete}
          disabled={deleteMutation.isPending}
          title={t.knowledgeBase.deleteDocument}
        >
          <Trash2Icon className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

function EditDocumentForm({
  kbId,
  doc,
  onDone,
}: {
  kbId: string;
  doc: KnowledgeBaseDocument;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const updateDoc = useUpdateDocument(kbId);
  const [title, setTitle] = useState(doc.title);
  const [content, setContent] = useState(doc.content ?? "");

  async function handleSubmit() {
    if (!title.trim()) return;
    try {
      await updateDoc.mutateAsync({
        docId: doc.id,
        request: {
          title: title.trim(),
          content: content.trim() || undefined,
        },
      });
      onDone();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="bg-muted/50 flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-col gap-2">
        <label htmlFor={`edit-title-${doc.id}`} className="text-sm font-medium">
          {t.knowledgeBase.documentTitle}
        </label>
        <Input
          id={`edit-title-${doc.id}`}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t.knowledgeBase.documentTitlePlaceholder}
        />
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={`edit-content-${doc.id}`} className="text-sm font-medium">
          {t.knowledgeBase.documentContent}
        </label>
        <Textarea
          id={`edit-content-${doc.id}`}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={t.knowledgeBase.documentContentPlaceholder}
          rows={5}
        />
      </div>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={onDone}>
          {t.common.cancel}
        </Button>
        <Button
          size="sm"
          onClick={handleSubmit}
          disabled={updateDoc.isPending || !title.trim()}
        >
          {updateDoc.isPending ? t.knowledgeBase.saving : t.knowledgeBase.save}
        </Button>
      </div>
    </div>
  );
}

function SearchPreview({ kbId }: { kbId: string }) {
  const { t } = useI18n();
  const searchMutation = useSearchKnowledgeBase(kbId);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultItem[]>([]);

  async function handleSearch() {
    if (!query.trim()) return;
    try {
      const res = await searchMutation.mutateAsync({ query: query.trim() });
      setResults(res.results);
    } catch {
      setResults([]);
    }
  }

  return (
    <div className="border-t pt-4">
      <div className="flex items-center gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t.knowledgeBase.searchPlaceholder}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleSearch();
          }}
        />
        <Button
          size="sm"
          onClick={handleSearch}
          disabled={searchMutation.isPending || !query.trim()}
        >
          <SearchIcon className="mr-1.5 h-3.5 w-3.5" />
          {searchMutation.isPending
            ? t.knowledgeBase.searching
            : t.knowledgeBase.searchButton}
        </Button>
      </div>
      {results.length > 0 && (
        <div className="mt-3 flex max-h-48 flex-col gap-2 overflow-y-auto">
          <span className="text-muted-foreground text-xs font-medium">
            {t.knowledgeBase.searchResults} ({results.length})
          </span>
          {results.map((item) => (
            <div
              key={item.chunk_id}
              className="rounded-md border px-3 py-2 text-xs"
            >
              <div className="text-muted-foreground mb-1 flex items-center justify-between">
                <span className="truncate">
                  {(item.metadata as Record<string, string>).title ?? item.chunk_id}
                </span>
                <Badge variant="outline" className="ml-2 shrink-0">
                  {item.score.toFixed(3)}
                </Badge>
              </div>
              <p className="line-clamp-3 whitespace-pre-wrap">{item.content}</p>
            </div>
          ))}
        </div>
      )}
      {searchMutation.isSuccess && results.length === 0 && (
        <p className="text-muted-foreground mt-2 text-center text-xs">
          {t.knowledgeBase.noResults}
        </p>
      )}
    </div>
  );
}
