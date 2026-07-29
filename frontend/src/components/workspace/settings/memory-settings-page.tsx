"use client";

import {
  DownloadIcon,
  PenLineIcon,
  PlusIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useId, useRef, useState } from "react";
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
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useI18n } from "@/core/i18n/hooks";
import { exportMemory } from "@/core/memory/api";
import {
  useClearMemory,
  useCreateMemoryFact,
  useDeleteMemoryFact,
  useImportMemory,
  useMemory,
  useUpdateMemoryFact,
} from "@/core/memory/hooks";
import type {
  MemorySection,
  MemoryFactInput,
  MemoryFactPatchInput,
  UserMemory,
} from "@/core/memory/types";
import { SafeStreamdown } from "@/core/streamdown/components";
import { streamdownPlugins } from "@/core/streamdown/plugins";
import { pathOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

import { SettingsSection } from "./settings-section";

type MemoryViewFilter = "all" | "facts" | "summaries";
type MemoryFact = UserMemory["facts"][number];

/** A display item (from ``display.sections[].items[]``) with optional metadata. */
type DisplayItem = Record<string, unknown> & { id?: string };
type DisplayEditHandler = (item: DisplayItem) => void;
type DisplayDeleteHandler = (item: DisplayItem) => void;

type MemorySummarySection = {
  title: string;
  summary: string;
  updatedAt?: string;
};

type MemorySummaryGroup = {
  title: string;
  sections: MemorySummarySection[];
};

type PendingImport = {
  fileName: string;
  memory: UserMemory;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isMemorySection(value: unknown): value is {
  summary: string;
  updatedAt: string;
} {
  return (
    isRecord(value) &&
    typeof value.summary === "string" &&
    typeof value.updatedAt === "string"
  );
}

function isMemoryFact(value: unknown): value is UserMemory["facts"][number] {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.content === "string" &&
    typeof value.category === "string" &&
    typeof value.confidence === "number" &&
    Number.isFinite(value.confidence) &&
    typeof value.createdAt === "string" &&
    typeof value.source === "string"
  );
}

function isImportedMemory(value: unknown): value is UserMemory {
  if (!isRecord(value)) {
    return false;
  }

  if (
    typeof value.version !== "string" ||
    typeof value.lastUpdated !== "string" ||
    !isRecord(value.user) ||
    !isRecord(value.history) ||
    !Array.isArray(value.facts)
  ) {
    return false;
  }

  return (
    isMemorySection(value.user.workContext) &&
    isMemorySection(value.user.personalContext) &&
    isMemorySection(value.user.topOfMind) &&
    isMemorySection(value.history.recentMonths) &&
    isMemorySection(value.history.earlierContext) &&
    isMemorySection(value.history.longTermBackground) &&
    value.facts.every(isMemoryFact)
  );
}

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
  section: MemorySummarySection,
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
): MemorySummaryGroup[] {
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
  sectionGroups: MemorySummaryGroup[],
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

function _displayCellValue(value: unknown): string {
  if (value == null) return "-";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "-";
  }
}

// ── Display-driven rendering (backend returns what to show) ─────────────────

function buildDisplaySections(memory: UserMemory): MemorySection[] | null {
  // If the backend provides a `display` field (even with empty sections),
  // use display mode -- only fall back when display is absent entirely
  // (backend doesn't support the display contract).
  if (!memory.display) return null;
  const sections = memory.display.sections ?? [];
  return [...sections].sort((a, b) => a.order - b.order);
}

function filterDisplaySections(
  sections: MemorySection[] | null,
  query: string,
): MemorySection[] | null {
  if (!sections) return null;
  if (!query) return sections;
  const normalized = query.toLowerCase();
  const filtered = sections
    .map((section) => {
      if (
        section.title.toLowerCase().includes(normalized) ||
        (section.content ?? "").toLowerCase().includes(normalized)
      ) {
        return section;
      }
      if (section.items?.length) {
        const matchedItems = section.items.filter((item) =>
          Object.values(item).some(
            (v) =>
              typeof v === "string" && v.toLowerCase().includes(normalized),
          ),
        );
        if (matchedItems.length > 0) {
          return { ...section, items: matchedItems };
        }
      }
      return null;
    })
    .filter(Boolean) as MemorySection[];
  return filtered.length > 0 ? filtered : null;
}

function renderDisplaySection(
  section: MemorySection,
  t: ReturnType<typeof useI18n>["t"],
  onEdit: DisplayEditHandler,
  onDelete: DisplayDeleteHandler,
) {
  switch (section.type) {
    case "content":
      return renderContentSection(section, t);
    case "list":
      return renderListSection(section, t, onEdit, onDelete);
    case "cards":
      return renderCardsSection(section, t, onEdit, onDelete);
    case "table":
      return renderTableSection(section, t, onEdit, onDelete);
  }
}

// Color rotation for section accents -- backend-agnostic (by order, not by id).
// Any memory system gets distinguishable colored left borders without
// hardcoding backend-specific type names.
const SECTION_ACCENT_ROTATION = [
  "border-l-blue-500",
  "border-l-green-500",
  "border-l-red-500",
  "border-l-teal-500",
  "border-l-purple-500",
  "border-l-orange-500",
  "border-l-violet-500",
  "border-l-pink-500",
  "border-l-amber-500",
  "border-l-indigo-500",
] as const;

function SectionWrapper({
  section,
  children,
}: {
  section: MemorySection;
  children: React.ReactNode;
}) {
  const accent =
    SECTION_ACCENT_ROTATION[
      (section.order ?? 0) % SECTION_ACCENT_ROTATION.length
    ];
  return (
    <div
      key={section.id}
      className={`rounded-md border border-l-2 ${accent} bg-card/50 p-3`}
    >
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold">{section.title}</h3>
        <span className="text-muted-foreground bg-muted rounded px-1.5 py-0.5 text-[10px] tracking-wide uppercase">
          {section.type}
        </span>
      </div>
      {children}
    </div>
  );
}

function renderContentSection(
  section: MemorySection,
  _t: ReturnType<typeof useI18n>["t"],
) {
  const body = section.content?.trim();
  return (
    <SectionWrapper section={section}>
      {body ? (
        <SafeStreamdown
          className="text-muted-foreground size-full min-w-0 text-sm [overflow-wrap:anywhere] [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
          {...streamdownPlugins}
        >
          {body}
        </SafeStreamdown>
      ) : (
        <div className="text-muted-foreground text-xs italic">(empty)</div>
      )}
    </SectionWrapper>
  );
}

function renderListSection(
  section: MemorySection,
  t: ReturnType<typeof useI18n>["t"],
  onEdit: DisplayEditHandler,
  onDelete: DisplayDeleteHandler,
) {
  const items = section.items ?? [];
  return (
    <SectionWrapper section={section}>
      {items.length === 0 ? (
        <div className="text-muted-foreground text-xs italic">
          {t.settings.memory.noFacts ?? "No items."}
        </div>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item, i) => {
            const content =
              typeof item.content === "string" ? item.content : "";
            const itemId = typeof item.id === "string" ? item.id : `item-${i}`;
            const deletable = item.deletable === true;
            const editable = item.editable === true;
            return (
              <li
                key={itemId}
                className="border-border/60 flex flex-col gap-1.5 rounded border p-2 sm:flex-row sm:items-start sm:justify-between"
              >
                <div className="min-w-0 space-y-1 [overflow-wrap:anywhere]">
                  <DisplayItemMeta item={item} t={t} />
                  <SafeStreamdown
                    className="size-full min-w-0 text-sm [overflow-wrap:anywhere] [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
                    {...streamdownPlugins}
                  >
                    {content || "(empty)"}
                  </SafeStreamdown>
                </div>
                <DisplayItemActions
                  item={item}
                  deletable={deletable}
                  editable={editable}
                  onEdit={onEdit}
                  onDelete={onDelete}
                  t={t}
                />
              </li>
            );
          })}
        </ul>
      )}
    </SectionWrapper>
  );
}

function renderCardsSection(
  section: MemorySection,
  t: ReturnType<typeof useI18n>["t"],
  onEdit: DisplayEditHandler,
  onDelete: DisplayDeleteHandler,
) {
  const items = section.items ?? [];
  return (
    <SectionWrapper section={section}>
      {items.length === 0 ? (
        <div className="text-muted-foreground text-xs italic">
          {t.settings.memory.noFacts ?? "No items."}
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {items.map((item, i) => {
            const title =
              typeof item.title === "string" ? item.title : undefined;
            const body = typeof item.body === "string" ? item.body : "";
            const tags: string[] = Array.isArray(item.tags)
              ? item.tags.filter((t): t is string => typeof t === "string")
              : [];
            const itemId = typeof item.id === "string" ? item.id : `card-${i}`;
            const deletable = item.deletable === true;
            const editable = item.editable === true;
            return (
              <div key={itemId} className="border-border/60 rounded border p-2">
                <div className="mb-1 flex items-start justify-between gap-2">
                  {title && <h4 className="text-xs font-semibold">{title}</h4>}
                  <DisplayItemActions
                    item={item}
                    deletable={deletable}
                    editable={editable}
                    onEdit={onEdit}
                    onDelete={onDelete}
                    t={t}
                  />
                </div>
                <DisplayItemMeta item={item} t={t} />
                <SafeStreamdown
                  className="text-muted-foreground size-full min-w-0 text-xs [overflow-wrap:anywhere] [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
                  {...streamdownPlugins}
                >
                  {body || "(empty)"}
                </SafeStreamdown>
                {tags.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {tags.map((tag) => (
                      <span
                        key={tag}
                        className="bg-muted rounded px-1.5 py-0.5 text-[10px]"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </SectionWrapper>
  );
}

function renderTableSection(
  section: MemorySection,
  t: ReturnType<typeof useI18n>["t"],
  onEdit: DisplayEditHandler,
  onDelete: DisplayDeleteHandler,
) {
  const items = section.items ?? [];
  if (items.length === 0) return null;
  const internalKeys = new Set(["deletable", "editable", "id", "body"]);
  const allKeys = new Set<string>();
  for (const item of items) {
    Object.keys(item).forEach((k) => {
      if (!internalKeys.has(k)) allKeys.add(k);
    });
  }
  const columns = Array.from(allKeys);
  const hasActions = items.some(
    (item) => item.deletable === true || item.editable === true,
  );
  if (hasActions) columns.push("_actions");
  return (
    <SectionWrapper section={section}>
      <div className="border-border/60 overflow-x-auto rounded border">
        <table className="w-full text-xs">
          <thead className="bg-muted/60 border-b">
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  className="px-2 py-1.5 text-left font-medium whitespace-nowrap"
                >
                  {col === "_actions" ? "" : col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => {
              const rid = typeof item.id === "string" ? item.id : `row-${i}`;
              const deletable = item.deletable === true;
              const editable = item.editable === true;
              return (
                <tr key={rid} className="border-b last:border-0">
                  {columns.map((col) =>
                    col === "_actions" ? (
                      <td key={col} className="px-2 py-1.5">
                        <DisplayItemActions
                          item={item}
                          deletable={deletable}
                          editable={editable}
                          onEdit={onEdit}
                          onDelete={onDelete}
                          t={t}
                        />
                      </td>
                    ) : (
                      <td
                        key={col}
                        className="max-w-[280px] truncate px-2 py-1.5 [overflow-wrap:anywhere]"
                      >
                        {_displayCellValue(item[col])}
                      </td>
                    ),
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </SectionWrapper>
  );
}

// ── Display item sub-components ──────────────────────────────────────────

function DisplayItemMeta({
  item,
  t,
}: {
  item: DisplayItem;
  t: ReturnType<typeof useI18n>["t"];
}) {
  const category =
    typeof item.category === "string" ? item.category : undefined;
  const confidence =
    typeof item.confidence === "number" ? item.confidence : undefined;
  const createdAt =
    typeof item.createdAt === "string" ? item.createdAt : undefined;
  const source = typeof item.source === "string" ? item.source : undefined;

  if (!category && confidence == null && !createdAt && !source) return null;

  const { key: confidenceKey } = confidenceToLevelKey(confidence);
  const confidenceText =
    t.settings.memory.markdown.table.confidenceLevel[confidenceKey];

  return (
    <div className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {category && (
        <span>
          {t.settings.memory.markdown.table.category}: {upperFirst(category)}
        </span>
      )}
      {confidence != null && (
        <span>
          {t.settings.memory.markdown.table.confidence}: {confidenceText}
        </span>
      )}
      {createdAt && (
        <span>
          {t.settings.memory.markdown.table.createdAt}:{" "}
          {formatTimeAgo(createdAt)}
        </span>
      )}
      {source && (
        <span>
          {t.settings.memory.markdown.table.source}:{" "}
          {source === "manual" ? (
            t.settings.memory.manualFactSource
          ) : (
            <Link
              href={pathOfThread(source)}
              className="text-primary underline-offset-4 hover:underline"
            >
              {t.settings.memory.markdown.table.view}
            </Link>
          )}
        </span>
      )}
    </div>
  );
}

function DisplayItemActions({
  item,
  deletable,
  editable,
  onEdit,
  onDelete,
  t,
}: {
  item: DisplayItem;
  deletable: boolean;
  editable: boolean;
  onEdit: DisplayEditHandler;
  onDelete: DisplayDeleteHandler;
  t: ReturnType<typeof useI18n>["t"];
}) {
  if (!deletable && !editable) return null;
  const editLabel = t.settings.memory.editAction;
  const deleteLabel = t.settings.memory.deleteAction;
  return (
    <div className="flex shrink-0 items-center gap-1 self-start">
      {editable && (
        <Button
          variant="ghost"
          size="icon"
          className="shrink-0"
          onClick={() => onEdit(item)}
          title={editLabel}
          aria-label={editLabel}
        >
          <PenLineIcon className="h-4 w-4" />
        </Button>
      )}
      {deletable && (
        <Button
          variant="ghost"
          size="icon"
          className="text-destructive hover:text-destructive shrink-0"
          onClick={() => onDelete(item)}
          title={deleteLabel}
          aria-label={deleteLabel}
        >
          <Trash2Icon className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}

export function MemorySettingsPage() {
  const { t } = useI18n();
  const { memory, isLoading, error } = useMemory();
  const clearMemory = useClearMemory();
  const createMemoryFact = useCreateMemoryFact();
  const deleteMemoryFact = useDeleteMemoryFact();
  const importMemoryMutation = useImportMemory();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const updateMemoryFact = useUpdateMemoryFact();
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [factToDelete, setFactToDelete] = useState<
    MemoryFact | DisplayItem | null
  >(null);
  const [factToEdit, setFactToEdit] = useState<MemoryFact | DisplayItem | null>(
    null,
  );
  const [factEditorOpen, setFactEditorOpen] = useState(false);
  const [factForm, setFactForm] = useState<FactFormState>(
    DEFAULT_FACT_FORM_STATE,
  );
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<MemoryViewFilter>("all");
  const [pendingImport, setPendingImport] = useState<PendingImport | null>(
    null,
  );
  const [isExporting, setIsExporting] = useState(false);
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
  const exportButton = t.settings.memory.exportButton ?? t.common.export;
  const exportSuccess =
    t.settings.memory.exportSuccess ?? t.common.exportSuccess;
  const importButton = t.settings.memory.importButton ?? t.common.import;
  const importSuccess = t.settings.memory.importSuccess ?? "Memory imported";

  const sectionGroups = memory ? buildMemorySectionGroups(memory, t) : [];
  const displaySections = memory ? buildDisplaySections(memory) : null;
  const usesDisplaySections = displaySections !== null;

  const filteredSectionGroups = usesDisplaySections
    ? []
    : sectionGroups
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

  const filteredDisplaySections = filterDisplaySections(
    displaySections,
    normalizedQuery,
  );

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
  const hasFilteredDisplaySections =
    usesDisplaySections &&
    filteredDisplaySections !== null &&
    filteredDisplaySections.length > 0;
  const shouldRenderSummariesBlock =
    showSummaries &&
    (usesDisplaySections
      ? filteredDisplaySections !== null &&
        (filteredDisplaySections.length > 0 || !normalizedQuery)
      : filteredSectionGroups.length > 0 || !normalizedQuery);
  const shouldRenderFactsBlock =
    !usesDisplaySections &&
    showFacts &&
    (filteredFacts.length > 0 || !normalizedQuery || filter === "facts");
  const hasMatchingVisibleContent =
    !memory ||
    (showSummaries &&
      (usesDisplaySections
        ? hasFilteredDisplaySections
        : filteredSectionGroups.length > 0)) ||
    (showFacts && filteredFacts.length > 0);

  async function handleExportMemory() {
    try {
      setIsExporting(true);
      const exportedMemory = await exportMemory();
      const fileName = `deerflow-memory-${(exportedMemory.lastUpdated || new Date().toISOString()).replace(/[:.]/g, "-")}.json`;
      const blob = new Blob([JSON.stringify(exportedMemory, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast.success(exportSuccess);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setIsExporting(false);
    }
  }

  async function handleImportFileSelection(event: {
    target: HTMLInputElement;
  }) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (!isImportedMemory(parsed)) {
        toast.error(t.settings.memory.importInvalidFile);
        return;
      }
      setPendingImport({
        fileName: file.name,
        memory: parsed,
      });
    } catch {
      toast.error(t.settings.memory.importInvalidFile);
    }
  }

  async function handleConfirmImport() {
    if (!pendingImport) {
      return;
    }

    try {
      await importMemoryMutation.mutateAsync(pendingImport.memory);
      toast.success(importSuccess);
      setPendingImport(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleClearMemory() {
    try {
      await clearMemory.mutateAsync();
      toast.success(clearAllSuccess);
      setClearDialogOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  function _itemId(item: MemoryFact | DisplayItem): string {
    if (typeof item.id === "string") return item.id;
    return "";
  }

  function _itemContent(item: MemoryFact | DisplayItem): string {
    if (typeof item.content === "string") return item.content;
    return "";
  }

  async function handleDeleteFact() {
    if (!factToDelete) return;
    const factId = _itemId(factToDelete);
    if (!factId) return;

    try {
      await deleteMemoryFact.mutateAsync(factId);
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

  function openEditFactDialog(item: MemoryFact | DisplayItem) {
    setFactToEdit(item);
    // Only pre-fill category/confidence from fields the item actually owns.
    // Display items from some backends (e.g. OpenViking) don't carry these
    // fields, and fabricating defaults here would silently corrupt metadata
    // on save (the PATCH would move the file to memories/context/ etc.).
    const itemRec = item as Record<string, unknown>;
    const itemCategory =
      typeof itemRec.category === "string" ? itemRec.category : "";
    const itemConfidence =
      typeof itemRec.confidence === "number"
        ? String(itemRec.confidence)
        : "";
    setFactForm({
      content: _itemContent(item),
      category: itemCategory,
      confidence: itemConfidence,
    });
    setFactEditorOpen(true);
  }

  function handleEditDisplayItem(item: DisplayItem) {
    openEditFactDialog(item);
  }

  function handleDeleteDisplayItem(item: DisplayItem) {
    setFactToDelete(item);
  }

  async function handleSaveFact() {
    const trimmedContent = factForm.content.trim();
    if (!trimmedContent) {
      toast.error(factValidationContent);
      return;
    }

    // Validate confidence only when a value was actually entered.
    const trimmedConfidence = factForm.confidence.trim();
    let confidence: number | undefined;
    if (trimmedConfidence) {
      confidence = Number(trimmedConfidence);
      if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
        toast.error(factValidationConfidence);
        return;
      }
    }

    const input: MemoryFactInput = {
      content: trimmedContent,
      category: factForm.category.trim() || "context",
      confidence: confidence ?? 0.5,
    };

    try {
      if (factToEdit) {
        const factId = _itemId(factToEdit);
        if (!factId) {
          toast.error(factValidationContent);
          return;
        }
        const trimmedCat = factForm.category.trim();
        const patchInput: MemoryFactPatchInput = {
          content: input.content,
        };
        // Only include category/confidence in the PATCH if the form has
        // actual values for them. Display items from backends like
        // OpenViking don't guarantee these fields; including fabricated
        // defaults would silently move the file or corrupt metadata.
        if (trimmedCat) {
          patchInput.category = trimmedCat;
        }
        if (confidence !== undefined) {
          patchInput.confidence = confidence;
        }
        await updateMemoryFact.mutateAsync({
          factId,
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
            {isMemorySummaryEmpty(memory) &&
            memory.facts.length === 0 &&
            !usesDisplaySections ? (
              <div className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
                {memoryFullyEmpty}
              </div>
            ) : null}

            <div className="flex flex-col gap-3">
              {/* Row 1: search + filter tabs */}
              <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={searchPlaceholder}
                  className="min-w-0 flex-1 sm:max-w-md"
                />
                {!usesDisplaySections && (
                  <ToggleGroup
                    type="single"
                    value={filter}
                    onValueChange={(value) => {
                      if (value) setFilter(value as MemoryViewFilter);
                    }}
                    variant="outline"
                    className="shrink-0 self-start sm:ml-auto sm:self-auto"
                  >
                    <ToggleGroupItem value="all" className="whitespace-nowrap">
                      {filterAll}
                    </ToggleGroupItem>
                    <ToggleGroupItem
                      value="facts"
                      className="whitespace-nowrap"
                    >
                      {filterFacts}
                    </ToggleGroupItem>
                    <ToggleGroupItem
                      value="summaries"
                      className="whitespace-nowrap"
                    >
                      {filterSummaries}
                    </ToggleGroupItem>
                  </ToggleGroup>
                )}
              </div>

              {/* Row 2: actions — constructive group on the left, destructive separated to the right */}
              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json,application/json"
                  className="hidden"
                  onChange={(event) => void handleImportFileSelection(event)}
                />
                <Button
                  variant="outline"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={importMemoryMutation.isPending}
                >
                  <UploadIcon className="mr-2 h-4 w-4" />
                  {importButton}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => void handleExportMemory()}
                  disabled={isExporting}
                >
                  <DownloadIcon className="mr-2 h-4 w-4" />
                  {isExporting ? t.common.loading : exportButton}
                </Button>
                <Button variant="outline" onClick={openCreateFactDialog}>
                  <PlusIcon className="mr-2 h-4 w-4" />
                  {addFactLabel}
                </Button>
                <Button
                  variant="destructive"
                  className="ml-auto"
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
              <div className="min-w-0 rounded-lg border p-4">
                {usesDisplaySections ? (
                  /* Display-driven sections (backend native format) */
                  <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
                    {filteredDisplaySections &&
                    filteredDisplaySections.length > 0 ? (
                      filteredDisplaySections.map((section) =>
                        renderDisplaySection(
                          section,
                          t,
                          handleEditDisplayItem,
                          handleDeleteDisplayItem,
                        ),
                      )
                    ) : (
                      <div className="text-muted-foreground py-8 text-center text-sm">
                        {memoryFullyEmpty}
                      </div>
                    )}
                  </div>
                ) : (
                  /* Fallback: current hardcoded 6-slot DeerMem layout */
                  <>
                    <div className="text-muted-foreground mb-4 text-sm">
                      {summaryReadOnly}
                    </div>
                    <SafeStreamdown
                      className="size-full min-w-0 [overflow-wrap:anywhere] [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
                      {...streamdownPlugins}
                    >
                      {summariesToMarkdown(memory, filteredSectionGroups, t)}
                    </SafeStreamdown>
                  </>
                )}
              </div>
            ) : null}

            {shouldRenderFactsBlock ? (
              <div className="min-w-0 rounded-lg border p-4">
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
                          <div className="min-w-0 space-y-2 [overflow-wrap:anywhere]">
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
                              <span>
                                <span className="text-muted-foreground">
                                  {t.settings.memory.markdown.table.source}:
                                </span>{" "}
                                {fact.source === "manual" ? (
                                  t.settings.memory.manualFactSource
                                ) : (
                                  <Link
                                    href={pathOfThread(fact.source)}
                                    className="text-primary underline-offset-4 hover:underline"
                                  >
                                    {t.settings.memory.markdown.table.view}
                                  </Link>
                                )}
                              </span>
                            </div>
                            <p className="text-sm [overflow-wrap:anywhere]">
                              {fact.content}
                            </p>
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
                {truncateFactPreview(_itemContent(factToDelete))}
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

      <Dialog
        open={pendingImport !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingImport(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.settings.memory.importConfirmTitle}</DialogTitle>
            <DialogDescription>
              {t.settings.memory.importConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          {pendingImport ? (
            <div className="bg-muted rounded-md border p-3 text-sm">
              <div>
                <span className="text-muted-foreground">
                  {t.settings.memory.importFileLabel}:
                </span>{" "}
                {pendingImport.fileName}
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t.settings.memory.markdown.facts}:
                </span>{" "}
                {pendingImport.memory.facts.length}
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t.common.lastUpdated}:
                </span>{" "}
                {pendingImport.memory.lastUpdated
                  ? formatTimeAgo(pendingImport.memory.lastUpdated)
                  : "-"}
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPendingImport(null)}
              disabled={importMemoryMutation.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={() => void handleConfirmImport()}
              disabled={importMemoryMutation.isPending}
            >
              {importMemoryMutation.isPending
                ? t.common.loading
                : t.common.import}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
