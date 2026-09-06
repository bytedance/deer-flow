"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ChevronDownIcon,
  DatabaseIcon,
  Loader2Icon,
  SearchIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildKnowledgeScopeSnapshot,
  cloneKnowledgeScopeSelection,
  countKnowledgeScopeSelection,
  listRetrievalCatalogDatasets,
  listRetrievalCatalogDocuments,
  type KnowledgeScopeDatasetSelection,
  type KnowledgeScopeSelection,
  type RetrievalCatalogItem,
} from "@/core/knowledge";
import { cn } from "@/lib/utils";

import { Tooltip } from "./tooltip";

const PAGE_SIZE = 100;

function replaceDataset(
  selection: KnowledgeScopeSelection,
  dataset: KnowledgeScopeDatasetSelection,
): KnowledgeScopeSelection {
  if (selection.mode !== "selected") return selection;
  const current = selection.datasets.findIndex(
    (item) => item.id === dataset.id,
  );
  const datasets = [...selection.datasets];
  if (current >= 0) datasets[current] = dataset;
  else datasets.push(dataset);
  return { mode: "selected", datasets };
}

function DocumentSelector({
  agentName,
  dataset,
  disabled,
  onChange,
}: {
  agentName: string;
  dataset: KnowledgeScopeDatasetSelection;
  disabled: boolean;
  onChange: (dataset: KnowledgeScopeDatasetSelection) => void;
}) {
  const { t } = useI18n();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const query = useQuery({
    queryKey: [
      "knowledge",
      "retrieval-catalog",
      agentName,
      dataset.id,
      page,
      search,
    ],
    queryFn: () =>
      listRetrievalCatalogDocuments({
        agentName,
        datasetId: dataset.id,
        page,
        pageSize: PAGE_SIZE,
        search,
      }),
    retry: false,
  });
  const selectedIds = new Set(
    dataset.documents.mode === "selected"
      ? dataset.documents.items.map((item) => item.id)
      : [],
  );

  const toggleDocument = (document: RetrievalCatalogItem, checked: boolean) => {
    if (!document.selectable) return;
    const current =
      dataset.documents.mode === "selected" ? dataset.documents.items : [];
    onChange({
      ...dataset,
      documents: {
        mode: "selected",
        items: checked
          ? [...current.filter((item) => item.id !== document.id), document]
          : current.filter((item) => item.id !== document.id),
      },
    });
  };

  return (
    <div className="bg-muted/40 mt-2 space-y-3 rounded-md p-3">
      <div className="flex gap-4 text-xs">
        <label className="flex items-center gap-2">
          <input
            checked={dataset.documents.mode === "all"}
            disabled={disabled}
            name={`documents-${dataset.id}`}
            type="radio"
            onChange={() =>
              onChange({ ...dataset, documents: { mode: "all" } })
            }
          />
          {t.knowledge.scope.allDocuments}
        </label>
        <label className="flex items-center gap-2">
          <input
            checked={dataset.documents.mode === "selected"}
            disabled={disabled}
            name={`documents-${dataset.id}`}
            type="radio"
            onChange={() =>
              onChange({
                ...dataset,
                documents: { mode: "selected", items: [] },
              })
            }
          />
          {t.knowledge.scope.selectedDocuments}
        </label>
      </div>
      {dataset.documents.mode === "selected" && (
        <>
          <div className="relative">
            <SearchIcon className="text-muted-foreground absolute top-2.5 left-2.5 size-4" />
            <Input
              className="h-9 pl-8"
              placeholder={t.knowledge.scope.searchDocuments}
              value={search}
              onChange={(event) => {
                setSearch(event.currentTarget.value);
                setPage(1);
              }}
            />
          </div>
          {query.isPending ? (
            <Loader2Icon className="text-muted-foreground mx-auto size-4 animate-spin" />
          ) : query.isError ? (
            <p className="text-destructive text-xs">
              {t.knowledge.scope.loadFailed}
            </p>
          ) : (
            <div className="space-y-1">
              {query.data?.items.map((document) => (
                <label
                  className={cn(
                    "flex items-center gap-2 rounded px-2 py-1.5 text-xs",
                    document.selectable
                      ? "hover:bg-muted"
                      : "text-muted-foreground",
                  )}
                  key={document.id}
                >
                  <input
                    aria-label={document.name}
                    checked={selectedIds.has(document.id)}
                    disabled={disabled || !document.selectable}
                    type="checkbox"
                    onChange={(event) =>
                      toggleDocument(document, event.currentTarget.checked)
                    }
                  />
                  <span className="min-w-0 truncate">{document.name}</span>
                  {!document.selectable && (
                    <span className="ml-auto shrink-0">
                      {t.knowledge.scope.notSearchable}
                    </span>
                  )}
                </label>
              ))}
              <CatalogPagination
                page={page}
                pageSize={PAGE_SIZE}
                total={query.data?.total ?? 0}
                onPageChange={setPage}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CatalogPagination({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  const { t } = useI18n();
  if (total <= pageSize) return null;
  return (
    <div className="flex items-center justify-end gap-2 pt-2">
      <Button
        disabled={page <= 1}
        size="sm"
        variant="outline"
        onClick={() => onPageChange(page - 1)}
      >
        {t.knowledge.scope.previous}
      </Button>
      <span className="text-muted-foreground text-xs">{page}</span>
      <Button
        disabled={page * pageSize >= total}
        size="sm"
        variant="outline"
        onClick={() => onPageChange(page + 1)}
      >
        {t.knowledge.scope.next}
      </Button>
    </div>
  );
}

export function KnowledgeScopeSelector({
  agentName,
  selection,
  disabled = false,
  unavailableReason,
  onChange,
}: {
  agentName: string;
  selection: KnowledgeScopeSelection;
  disabled?: boolean;
  unavailableReason?: string;
  onChange: (selection: KnowledgeScopeSelection) => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(() =>
    cloneKnowledgeScopeSelection(selection),
  );
  const [expandedDatasetId, setExpandedDatasetId] = useState<string | null>(
    null,
  );
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const query = useQuery({
    queryKey: ["knowledge", "retrieval-catalog", agentName, page, search],
    queryFn: () =>
      listRetrievalCatalogDatasets({
        agentName,
        page,
        pageSize: PAGE_SIZE,
        search,
      }),
    enabled: open && draft.mode === "selected" && !unavailableReason,
    retry: false,
  });

  useEffect(() => {
    if (open) setDraft(cloneKnowledgeScopeSelection(selection));
  }, [open, selection]);

  const counts = countKnowledgeScopeSelection(selection);
  const label =
    selection.mode === "all"
      ? t.knowledge.scope.buttonAll
      : selection.mode === "disabled"
        ? t.knowledge.scope.buttonDisabled
        : counts.documents > 0
          ? t.knowledge.scope.buttonDatasetsAndDocuments(
              counts.datasets,
              counts.documents,
            )
          : t.knowledge.scope.buttonDatasets(counts.datasets);
  const draftInvalid =
    draft.mode === "selected" &&
    (draft.datasets.length === 0 ||
      draft.datasets.some(
        (dataset) =>
          dataset.documents.mode === "selected" &&
          dataset.documents.items.length === 0,
      ));
  const draftExceedsLimits = useMemo(() => {
    if (draftInvalid) return false;
    try {
      buildKnowledgeScopeSnapshot(draft);
      return false;
    } catch {
      return true;
    }
  }, [draft, draftInvalid]);

  const selectedDatasets = useMemo(
    () =>
      draft.mode === "selected"
        ? new Map(draft.datasets.map((item) => [item.id, item]))
        : new Map(),
    [draft],
  );

  const toggleDataset = (dataset: RetrievalCatalogItem, checked: boolean) => {
    if (draft.mode !== "selected" || !dataset.selectable) return;
    setDraft({
      mode: "selected",
      datasets: checked
        ? [
            ...draft.datasets.filter((item) => item.id !== dataset.id),
            { ...dataset, documents: { mode: "all" } },
          ]
        : draft.datasets.filter((item) => item.id !== dataset.id),
    });
    if (!checked && expandedDatasetId === dataset.id)
      setExpandedDatasetId(null);
  };

  const trigger = (
    <Button
      aria-label={label}
      className="h-8 max-w-48 gap-1.5 px-2 text-xs"
      data-testid="knowledge-scope-trigger"
      disabled={disabled || Boolean(unavailableReason)}
      type="button"
      variant="ghost"
      onClick={() => setOpen(true)}
    >
      <DatabaseIcon className="size-3" />
      <span className="truncate">{label}</span>
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {unavailableReason ? (
        <Tooltip content={unavailableReason}>{trigger}</Tooltip>
      ) : (
        trigger
      )}
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t.knowledge.scope.title}</DialogTitle>
          <DialogDescription>{t.knowledge.scope.description}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-4 text-sm">
          {(["all", "selected", "disabled"] as const).map((mode) => (
            <label className="flex items-center gap-2" key={mode}>
              <input
                checked={draft.mode === mode}
                disabled={disabled}
                name="knowledge-scope-mode"
                type="radio"
                onChange={() =>
                  setDraft(
                    mode === "selected" ? { mode, datasets: [] } : { mode },
                  )
                }
              />
              {mode === "all"
                ? t.knowledge.scope.allDatasets
                : mode === "selected"
                  ? t.knowledge.scope.selectedDatasets
                  : t.knowledge.scope.disabled}
            </label>
          ))}
        </div>
        {draft.mode === "selected" && (
          <div className="flex min-h-0 flex-1 flex-col gap-3">
            <div className="relative">
              <SearchIcon className="text-muted-foreground absolute top-2.5 left-2.5 size-4" />
              <Input
                className="h-9 pl-8"
                placeholder={t.knowledge.scope.searchDatasets}
                value={search}
                onChange={(event) => {
                  setSearch(event.currentTarget.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="text-muted-foreground text-xs">
              {t.knowledge.scope.selectedCount(draft.datasets.length)}
            </div>
            <ScrollArea className="min-h-48 flex-1 pr-3">
              {query.isPending ? (
                <Loader2Icon className="text-muted-foreground mx-auto mt-8 size-5 animate-spin" />
              ) : query.isError ? (
                <p className="text-destructive p-3 text-sm">
                  {t.knowledge.scope.loadFailed}
                </p>
              ) : (
                <div className="space-y-2">
                  {query.data?.items.map((dataset) => {
                    const selected = selectedDatasets.get(dataset.id);
                    const expanded = expandedDatasetId === dataset.id;
                    return (
                      <div className="rounded-md border p-2" key={dataset.id}>
                        <div className="flex items-center gap-2">
                          <input
                            aria-label={dataset.name}
                            checked={Boolean(selected)}
                            disabled={disabled || !dataset.selectable}
                            type="checkbox"
                            onChange={(event) =>
                              toggleDataset(
                                dataset,
                                event.currentTarget.checked,
                              )
                            }
                          />
                          <span
                            className={cn(
                              "min-w-0 flex-1 truncate text-sm",
                              !dataset.selectable && "text-muted-foreground",
                            )}
                          >
                            {dataset.name}
                          </span>
                          {!dataset.selectable && (
                            <span className="text-muted-foreground text-xs">
                              {t.knowledge.scope.notSearchable}
                            </span>
                          )}
                          {selected && (
                            <Button
                              aria-expanded={expanded}
                              size="sm"
                              type="button"
                              variant="ghost"
                              onClick={() =>
                                setExpandedDatasetId(
                                  expanded ? null : dataset.id,
                                )
                              }
                            >
                              {t.knowledge.scope.files}
                              <ChevronDownIcon
                                className={cn(
                                  "size-3 transition-transform",
                                  expanded && "rotate-180",
                                )}
                              />
                            </Button>
                          )}
                        </div>
                        {selected && expanded && (
                          <DocumentSelector
                            agentName={agentName}
                            dataset={selected}
                            disabled={disabled}
                            onChange={(next) =>
                              setDraft((current) =>
                                replaceDataset(current, next),
                              )
                            }
                          />
                        )}
                      </div>
                    );
                  })}
                  <CatalogPagination
                    page={page}
                    pageSize={PAGE_SIZE}
                    total={query.data?.total ?? 0}
                    onPageChange={setPage}
                  />
                </div>
              )}
            </ScrollArea>
          </div>
        )}
        <div className="text-muted-foreground space-y-1 text-xs">
          <p>{t.knowledge.scope.pageOnlyNotice}</p>
          <p>{t.knowledge.scope.sharedNotice}</p>
          {draftExceedsLimits && (
            <p className="text-destructive">
              {t.knowledge.scope.selectionInvalid}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => setOpen(false)}
          >
            {t.common.cancel}
          </Button>
          <Button
            disabled={disabled || draftInvalid || draftExceedsLimits}
            type="button"
            onClick={() => {
              onChange(cloneKnowledgeScopeSelection(draft));
              setOpen(false);
            }}
          >
            {t.knowledge.scope.apply}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
