"use client";

import { PenLineIcon, PlusIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useId, useState } from "react";
import { toast } from "sonner";
import { Streamdown } from "streamdown";

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
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useI18n } from "@/core/i18n/hooks";
import {
  useClearMemory,
  useCreateMemoryFact,
  useDeleteMemoryFact,
  useMemory,
  useUpdateMemoryFact,
} from "@/core/memory/hooks";
import type {
  MemoryFactInput,
  MemoryFactPatchInput,
  UserMemory,
} from "@/core/memory/types";
import { streamdownPlugins } from "@/core/streamdown/plugins";
import { pathOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

import { SettingsSection } from "./settings-section";

type MemoryViewFilter = "all" | "facts" | "summaries";
type MemoryFact = UserMemory["facts"][number];

type MemorySection = {
  title: string;
  summary: string;
  updatedAt?: string;
};

type MemorySectionGroup = {
  title: string;
  sections: MemorySection[];
};

type FactFormState = {
  content: string;
  category: string;
  confidence: string;
};

const DEFAULT_FACT_FORM_STATE: FactFormState = {
  content: "",
  category: "context",
  confidence: "0.8",
};

function confidenceToLevelKey(confidence: unknown): {
  key: "veryHigh" | "high" | "normal" | "unknown";
  value?: number;
} {
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) {
    return { key: "unknown" };
  }

  const value = Math.min(1, Math.max(0, confidence));
  if (value >= 0.85) return { key: "veryHigh", value };
  if (value >= 0.65) return { key: "high", value };
  return { key: "normal", value };
}

function formatMemorySection(
  section: MemorySection,
  t: ReturnType<typeof useI18n>["t"],
): string {
  const content =
    section.summary.trim() ||
    `<span class="text-muted-foreground">${t.settings.memory.markdown.empty}</span>`;
  return [
    `### ${section.title}`,
    content,
    "",
    section.updatedAt &&
      `> ${t.settings.memory.markdown.updatedAt}: \`${formatTimeAgo(section.updatedAt)}\``,
  ]
    .filter(Boolean)
    .join("\n");
}

function buildMemorySectionGroups(
  memory: UserMemory,
  t: ReturnType<typeof useI18n>["t"],
): MemorySectionGroup[] {
  return [
    {
      title: t.settings.memory.markdown.userContext,
      sections: [
        {
          title: t.settings.memory.markdown.work,
          summary: memory.user.workContext.summary,
          updatedAt: memory.user.workContext.updatedAt,
        },
        {
          title: t.settings.memory.markdown.personal,
          summary: memory.user.personalContext.summary,
          updatedAt: memory.user.personalContext.updatedAt,
        },
        {
          title: t.settings.memory.markdown.topOfMind,
          summary: memory.user.topOfMind.summary,
          updatedAt: memory.user.topOfMind.updatedAt,
        },
      ],
    },
    {
      title: t.settings.memory.markdown.historyBackground,
      sections: [
        {
          title: t.settings.memory.markdown.recentMonths,
          summary: memory.history.recentMonths.summary,
          updatedAt: memory.history.recentMonths.updatedAt,
        },
        {
          title: t.settings.memory.markdown.earlierContext,
          summary: memory.history.earlierContext.summary,
          updatedAt: memory.history.earlierContext.updatedAt,
        },
        {
          title: t.settings.memory.markdown.longTermBackground,
          summary: memory.history.longTermBackground.summary,
          updatedAt: memory.history.longTermBackground.updatedAt,
        },
      ],
    },
  ];
}

function summariesToMarkdown(
  memory: UserMemory,
  sectionGroups: MemorySectionGroup[],
  t: ReturnType<typeof useI18n>["t"],
) {
  const parts: string[] = [];

  parts.push(`## ${t.settings.memory.markdown.overview}`);
  parts.push(
    `- **${t.common.lastUpdated}**: \`${formatTimeAgo(memory.lastUpdated)}\``,
  );

  for (const group of sectionGroups) {
    parts.push(`\n## ${group.title}`);
    for (const section of group.sections) {
      parts.push(formatMemorySection(section, t));
    }
  }

  const markdown = parts.join("\n\n");
  const lines = markdown.split("\n");
  const out: string[] = [];
  let i = 0;
  for (const line of lines) {
    i++;
    if (i !== 1 && line.startsWith("## ")) {
      if (out.length === 0 || out[out.length - 1] !== "---") {
        out.push("---");
      }
    }
    out.push(line);
  }

  return out.join("\n");
}

function isMemorySummaryEmpty(memory: UserMemory) {
  return (
    memory.user.workContext.summary.trim() === "" &&
    memory.user.personalContext.summary.trim() === "" &&
    memory.user.topOfMind.summary.trim() === "" &&
    memory.history.recentMonths.summary.trim() === "" &&
    memory.history.earlierContext.summary.trim() === "" &&
    memory.history.longTermBackground.summary.trim() === ""
  );
}

function truncateFactPreview(content: string, maxLength = 140) {
  const normalized = content.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  const ellipsis = "...";
  if (maxLength <= ellipsis.length) {
    return normalized.slice(0, maxLength);
  }
  return `${normalized.slice(0, maxLength - ellipsis.length)}${ellipsis}`;
}

function upperFirst(str: string) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

export function MemorySettingsPage() {
  const { t } = useI18n();
  const { memory, isLoading, error } = useMemory();
  const clearMemory = useClearMemory();
  const createMemoryFact = useCreateMemoryFact();
  const deleteMemoryFact = useDeleteMemoryFact();
  const updateMemoryFact = useUpdateMemoryFact();
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [factToDelete, setFactToDelete] = useState<MemoryFact | null>(null);
  const [factToEdit, setFactToEdit] = useState<MemoryFact | null>(null);
  const [factEditorOpen, setFactEditorOpen] = useState(false);
  const [factForm, setFactForm] = useState<FactFormState>(
    DEFAULT_FACT_FORM_STATE,
  );
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<MemoryViewFilter>("all");
  const deferredQuery = useDeferredValue(query);
  const normalizedQuery = deferredQuery.trim().toLowerCase();
  const factContentInputId = useId();
  const factCategoryInputId = useId();
  const factConfidenceInputId = useId();
  const factConfidenceHintId = useId();

  const clearAllLabel = t.settings.memory.clearAll ?? "Clear all memory";
  const clearAllConfirmTitle =
    t.settings.memory.clearAllConfirmTitle ?? "Clear all memory?";
  const clearAllConfirmDescription =
    t.settings.memory.clearAllConfirmDescription ??
    "This will remove all saved summaries and facts. This action cannot be undone.";
  const clearAllSuccess =
    t.settings.memory.clearAllSuccess ?? "All memory cleared";
  const factDeleteConfirmTitle =
    t.settings.memory.factDeleteConfirmTitle ?? "Delete this fact?";
  const factDeleteConfirmDescription =
    t.settings.memory.factDeleteConfirmDescription ??
    "This fact will be removed from memory immediately. This action cannot be undone.";
  const factDeleteSuccess =
    t.settings.memory.factDeleteSuccess ?? "Fact deleted";
  const addFactLabel = t.settings.memory.addFact;
  const addFactTitle = t.settings.memory.addFactTitle;
  const editFactTitle = t.settings.memory.editFactTitle;
  const addFactSuccess = t.settings.memory.addFactSuccess;
  const editFactSuccess = t.settings.memory.editFactSuccess;
  const factContentLabel = t.settings.memory.factContentLabel;
  const factCategoryLabel = t.settings.memory.factCategoryLabel;
  const factConfidenceLabel = t.settings.memory.factConfidenceLabel;
  const factContentPlaceholder = t.settings.memory.factContentPlaceholder;
  const factCategoryPlaceholder = t.settings.memory.factCategoryPlaceholder;
  const factConfidenceHint = t.settings.memory.factConfidenceHint;
  const factSave = t.settings.memory.factSave;
  const factValidationContent = t.settings.memory.factValidationContent;
  const factValidationConfidence = t.settings.memory.factValidationConfidence;
  const manualFactSource = t.settings.memory.manualFactSource;
  const noFacts = t.settings.memory.noFacts ?? "No saved facts yet.";
  const summaryReadOnly = t.settings.memory.summaryReadOnly;
  const memoryFullyEmpty =
    t.settings.memory.memoryFullyEmpty ?? "No memory saved yet.";
  const factPreviewLabel =
    t.settings.memory.factPreviewLabel ?? "Fact to delete";
  const searchPlaceholder =
    t.settings.memory.searchPlaceholder ?? "Search memory";
  const filterAll = t.settings.memory.filterAll ?? "All";
  const filterFacts = t.settings.memory.filterFacts ?? "Facts";
  const filterSummaries = t.settings.memory.filterSummaries ?? "Summaries";
  const noMatches = t.settings.memory.noMatches ?? "No matching memory found";

  const sectionGroups = memory ? buildMemorySectionGroups(memory, t) : [];
  const filteredSectionGroups = sectionGroups
    .map((group) => ({
      ...group,
      sections: group.sections.filter((section) =>
        normalizedQuery
          ? `${section.title} ${section.summary}`
              .toLowerCase()
              .includes(normalizedQuery)
          : true,
      ),
    }))
    .filter((group) => group.sections.length > 0);

  const filteredFacts = memory
    ? memory.facts.filter((fact) =>
        normalizedQuery
          ? `${fact.content} ${fact.category}`
              .toLowerCase()
              .includes(normalizedQuery)
          : true,
      )
    : [];

  const showSummaries = filter !== "facts";
  const showFacts = filter !== "summaries";
  const shouldRenderSummariesBlock =
    showSummaries && (filteredSectionGroups.length > 0 || !normalizedQuery);
  const shouldRenderFactsBlock =
    showFacts &&
    (filteredFacts.length > 0 || !normalizedQuery || filter === "facts");
  const hasMatchingVisibleContent =
    !memory ||
    (showSummaries && filteredSectionGroups.length > 0) ||
    (showFacts && filteredFacts.length > 0);

  async function handleClearMemory() {
    try {
      await clearMemory.mutateAsync();
      toast.success(clearAllSuccess);
      setClearDialogOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDeleteFact() {
    if (!factToDelete) return;

    try {
      await deleteMemoryFact.mutateAsync(factToDelete.id);
      toast.success(factDeleteSuccess);
      setFactToDelete(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  function openCreateFactDialog() {
    setFactToEdit(null);
    setFactForm(DEFAULT_FACT_FORM_STATE);
    setFactEditorOpen(true);
  }

  function openEditFactDialog(fact: MemoryFact) {
    setFactToEdit(fact);
    setFactForm({
      content: fact.content,
      category: fact.category,
      confidence: String(fact.confidence),
    });
    setFactEditorOpen(true);
  }

  async function handleSaveFact() {
    const trimmedContent = factForm.content.trim();
    if (!trimmedContent) {
      toast.error(factValidationContent);
      return;
    }

    const confidence = Number(factForm.confidence);
    if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
      toast.error(factValidationConfidence);
      return;
    }

    const input: MemoryFactInput = {
      content: trimmedContent,
      category: factForm.category.trim() || "context",
      confidence,
    };

    try {
      if (factToEdit) {
        const patchInput: MemoryFactPatchInput = {
          content: input.content,
          category: input.category,
          confidence: input.confidence,
        };
        await updateMemoryFact.mutateAsync({
          factId: factToEdit.id,
          input: patchInput,
        });
        toast.success(editFactSuccess);
      } else {
        await createMemoryFact.mutateAsync(input);
        toast.success(addFactSuccess);
      }
      setFactEditorOpen(false);
      setFactToEdit(null);
      setFactForm(DEFAULT_FACT_FORM_STATE);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  const isFactFormPending =
    createMemoryFact.isPending || updateMemoryFact.isPending;

  return (
    <>
      <SettingsSection
        title={t.settings.memory.title}
        description={t.settings.memory.description}
      >
        {isLoading ? (
          <div className="text-muted-foreground text-sm">
            {t.common.loading}
          </div>
        ) : error ? (
          <div>Error: {error.message}</div>
        ) : !memory ? (
          <div className="text-muted-foreground text-sm">
            {t.settings.memory.empty}
          </div>
        ) : (
          <div className="space-y-4">
            {isMemorySummaryEmpty(memory) && memory.facts.length === 0 ? (
              <div className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
                {memoryFullyEmpty}
              </div>
            ) : null}

            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center">
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={searchPlaceholder}
                  className="sm:max-w-xs"
                />
                <ToggleGroup
                  type="single"
                  value={filter}
                  onValueChange={(value) => {
                    if (value) setFilter(value as MemoryViewFilter);
                  }}
                  variant="outline"
                >
                  <ToggleGroupItem value="all">{filterAll}</ToggleGroupItem>
                  <ToggleGroupItem value="facts">{filterFacts}</ToggleGroupItem>
                  <ToggleGroupItem value="summaries">
                    {filterSummaries}
                  </ToggleGroupItem>
                </ToggleGroup>
              </div>

              <div className="flex items-center gap-2">
                <Button variant="outline" onClick={openCreateFactDialog}>
                  <PlusIcon className="mr-2 h-4 w-4" />
                  {addFactLabel}
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => setClearDialogOpen(true)}
                  disabled={clearMemory.isPending}
                >
                  {clearMemory.isPending ? t.common.loading : clearAllLabel}
                </Button>
              </div>
            </div>

            {!hasMatchingVisibleContent && normalizedQuery ? (
              <div className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
                {noMatches}
              </div>
            ) : null}

            {shouldRenderSummariesBlock ? (
              <div className="rounded-lg border p-4">
                <div className="text-muted-foreground mb-4 text-sm">
                  {summaryReadOnly}
                </div>
                <Streamdown
                  className="size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
                  {...streamdownPlugins}
                >
                  {summariesToMarkdown(memory, filteredSectionGroups, t)}
                </Streamdown>
              </div>
            ) : null}

            {shouldRenderFactsBlock ? (
              <div className="rounded-lg border p-4">
                <div className="mb-4">
                  <h3 className="text-base font-medium">
                    {t.settings.memory.markdown.facts}
                  </h3>
                </div>

                {filteredFacts.length === 0 ? (
                  <div className="text-muted-foreground text-sm">
                    {normalizedQuery ? noMatches : noFacts}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {filteredFacts.map((fact) => {
                      const { key } = confidenceToLevelKey(fact.confidence);
                      const confidenceText =
                        t.settings.memory.markdown.table.confidenceLevel[key];

                      return (
                        <div
                          key={fact.id}
                          className="flex flex-col gap-3 rounded-md border p-3 sm:flex-row sm:items-start sm:justify-between"
                        >
                          <div className="min-w-0 space-y-2">
                            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                              <span>
                                <span className="text-muted-foreground">
                                  {t.settings.memory.markdown.table.category}:
                                </span>{" "}
                                {upperFirst(fact.category)}
                              </span>
                              <span>
                                <span className="text-muted-foreground">
                                  {t.settings.memory.markdown.table.confidence}:
                                </span>{" "}
                                {confidenceText}
                              </span>
                              <span>
                                <span className="text-muted-foreground">
                                  {t.settings.memory.markdown.table.createdAt}:
                                </span>{" "}
                                {formatTimeAgo(fact.createdAt)}
                              </span>
                            </div>
                            <p className="text-sm break-words">
                              {fact.content}
                            </p>
                            {fact.source === "manual" ? (
                              <span className="text-muted-foreground text-sm">
                                {manualFactSource}
                              </span>
                            ) : (
                              <Link
                                href={pathOfThread(fact.source)}
                                className="text-primary text-sm underline-offset-4 hover:underline"
                              >
                                {t.settings.memory.markdown.table.view}
                              </Link>
                            )}
                          </div>

                          <div className="flex shrink-0 items-center gap-1 self-start sm:ml-3">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="shrink-0"
                              onClick={() => openEditFactDialog(fact)}
                              disabled={deleteMemoryFact.isPending}
                              title={t.common.edit}
                              aria-label={t.common.edit}
                            >
                              <PenLineIcon className="h-4 w-4" />
                            </Button>

                            <Button
                              variant="ghost"
                              size="icon"
                              className="text-destructive hover:text-destructive shrink-0"
                              onClick={() => setFactToDelete(fact)}
                              disabled={deleteMemoryFact.isPending}
                              title={t.common.delete}
                              aria-label={t.common.delete}
                            >
                              <Trash2Icon className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : null}
          </div>
        )}
      </SettingsSection>

      <Dialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{clearAllConfirmTitle}</DialogTitle>
            <DialogDescription>{clearAllConfirmDescription}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setClearDialogOpen(false)}
              disabled={clearMemory.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleClearMemory()}
              disabled={clearMemory.isPending}
            >
              {clearMemory.isPending ? t.common.loading : clearAllLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={factEditorOpen}
        onOpenChange={(open) => {
          setFactEditorOpen(open);
          if (!open) {
            setFactToEdit(null);
            setFactForm(DEFAULT_FACT_FORM_STATE);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {factToEdit ? editFactTitle : addFactTitle}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor={factContentInputId}
              >
                {factContentLabel}
              </label>
              <Textarea
                id={factContentInputId}
                value={factForm.content}
                onChange={(event) =>
                  setFactForm((current) => ({
                    ...current,
                    content: event.target.value,
                  }))
                }
                placeholder={factContentPlaceholder}
                rows={4}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <label
                  className="text-sm font-medium"
                  htmlFor={factCategoryInputId}
                >
                  {factCategoryLabel}
                </label>
                <Input
                  id={factCategoryInputId}
                  value={factForm.category}
                  onChange={(event) =>
                    setFactForm((current) => ({
                      ...current,
                      category: event.target.value,
                    }))
                  }
                  placeholder={factCategoryPlaceholder}
                />
              </div>

              <div className="space-y-2">
                <label
                  className="text-sm font-medium"
                  htmlFor={factConfidenceInputId}
                >
                  {factConfidenceLabel}
                </label>
                <Input
                  id={factConfidenceInputId}
                  aria-describedby={factConfidenceHintId}
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  value={factForm.confidence}
                  onChange={(event) =>
                    setFactForm((current) => ({
                      ...current,
                      confidence: event.target.value,
                    }))
                  }
                />
                <div
                  className="text-muted-foreground text-xs"
                  id={factConfidenceHintId}
                >
                  {factConfidenceHint}
                </div>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setFactEditorOpen(false);
                setFactToEdit(null);
                setFactForm(DEFAULT_FACT_FORM_STATE);
              }}
              disabled={isFactFormPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={() => void handleSaveFact()}
              disabled={isFactFormPending}
            >
              {isFactFormPending ? t.common.loading : factSave}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={factToDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setFactToDelete(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{factDeleteConfirmTitle}</DialogTitle>
            <DialogDescription>
              {factDeleteConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          {factToDelete ? (
            <div className="bg-muted rounded-md border p-3 text-sm">
              <div className="text-muted-foreground mb-1 font-medium">
                {factPreviewLabel}
              </div>
              <p className="break-words">
                {truncateFactPreview(factToDelete.content)}
              </p>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setFactToDelete(null)}
              disabled={deleteMemoryFact.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleDeleteFact()}
              disabled={deleteMemoryFact.isPending}
            >
              {deleteMemoryFact.isPending ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
