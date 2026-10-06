"use client";

import {
  ArrowUpDown,
  Check,
  ChevronDown,
  Columns,
  Download,
  Eye,
  EyeOff,
  FileText,
  MoreHorizontal,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import { classifyDocError } from "@/core/knowledge/doc-errors";
import {
  aggregateDocumentStats,
  formatBytes,
  formatKb,
  formatMb,
} from "@/core/knowledge/document-stats";
import {
  DEFAULT_DOCUMENT_SORT,
  filterDocuments,
  sortDocuments,
  type DocumentSortKey,
  type SortDirection,
} from "@/core/knowledge/document-view";
import {
  formatKnowledgeRelativeTime,
  formatKnowledgeTimestamp,
  formatVideoDuration,
} from "@/core/knowledge/format";
import { pathStatusLines } from "@/core/knowledge/path-status";
import { partitionFilesBySuffix } from "@/core/knowledge/supported-formats";
import type {
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeDocumentStatus,
} from "@/core/knowledge/types";
import type { DocFailureEntry } from "@/core/knowledge/use-doc-failure-notifier";
import {
  HIDEABLE_COLUMNS,
  useDocTablePrefs,
  type ColumnId,
  type DocTablePrefs,
  type SizeUnit,
  type TimeFormat,
} from "@/core/knowledge/use-doc-table-prefs";
import { cn } from "@/lib/utils";

import { DocFailurePanel } from "./doc-failure-panel";
import {
  FileTypeBadge,
  fileTypeKind,
  probeDraggedItems,
  probeSignature,
  type DragProbe,
} from "./file-type-badge";
import { toast } from "./kb-toast";
import { runAfterMenuClose } from "./run-after-menu-close";

const SORT_OPTIONS: {
  key: DocumentSortKey;
  labelKey: "createdAt" | "name" | "size" | "chunks";
}[] = [
  { key: "created_at", labelKey: "createdAt" },
  { key: "name", labelKey: "name" },
  { key: "size_bytes", labelKey: "size" },
  { key: "chunk_count", labelKey: "chunks" },
];

// 状态指示（2026-08-30）：圆点 + 小字（Linear 风格）替代实心徽章——
// 文件名是第一扫描目标，常态退后、异常突出。原黑底 default Badge 已移除。
// 就绪降不透明度而非加深：加深会抬高对比、更抢眼，与「常态退后」正好相反。
const STATUS_DOT_CLASS: Record<KnowledgeDocumentStatus, string> = {
  uploaded: "bg-muted-foreground/60",
  parsing: "bg-amber-500",
  chunking: "bg-amber-500",
  indexing: "bg-amber-500",
  ready: "bg-emerald-500/45",
  failed: "bg-destructive",
};

/**
 * Hover breakdown for the status column (P3, spec 2026-08-11 §5): three
 * per-path lines — vector / graph (percent combined mid-indexing) / wiki.
 * The wiki line carries the library-level hint because it is a library-wide
 * mirror, not a per-document state. Exported for dom tests.
 */
export function PathStatusBreakdown({
  doc,
}: {
  doc: Pick<KnowledgeDocument, "path_status" | "progress_percent" | "status">;
}) {
  const { t } = useI18n();
  const ps = t.knowledge.pathStatus;
  const lines = pathStatusLines(doc);
  if (!lines) {
    return null;
  }
  return (
    <div className="flex flex-col gap-1" data-testid="path-status-breakdown">
      {lines.map((line) => (
        <div
          key={line.path}
          className="flex items-center justify-between gap-4 text-xs"
          data-path={line.path}
        >
          <span className="text-muted-foreground">
            {ps[line.path]}
            {line.path === "wiki" ? ps.libraryHint : ""}
          </span>
          {/* degraded 着琥珀（spec 2026-09-08 §5）：对齐项目既有 caution 视觉词汇
              （text-amber-600 dark:text-amber-500，同 vector-tab / eval-synthesis-review）；
              按状态而非腿着色，图谱腿 degraded 与视频腿 degraded 同一处理。 */}
          <span
            className={cn(
              line.state === "degraded" && "text-amber-600 dark:text-amber-500",
            )}
            data-state={line.state}
          >
            {ps.state[line.state as keyof typeof ps.state] ?? line.state}
            {line.percent !== undefined ? ` ${line.percent}%` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * 可隐藏列的表头单元格（2026-09-02，方案 Task 5）：标题 + hover 淡入的 chevron
 * 触发器，点击弹列菜单。菜单含「隐藏列」；时间列额外有格式切换（绝对/相对），
 * 大小列额外有单位切换（KB/MB）。chevron 用 th 级 group/th 门控 opacity（不改
 * 布局，表头高度稳定）；打开时 has-[[data-state=open]] 常亮。
 */
function HideableColumnHeader({
  columnId,
  label,
  prefs,
  onToggleColumn,
  onSetTimeFormat,
  onSetSizeUnit,
}: {
  columnId: ColumnId;
  label: string;
  prefs: DocTablePrefs;
  onToggleColumn: (id: ColumnId) => void;
  onSetTimeFormat: (format: TimeFormat) => void;
  onSetSizeUnit: (unit: SizeUnit) => void;
}) {
  const { t } = useI18n();
  const tk = t.knowledge;
  return (
    <th className="group/th bg-background sticky top-0 z-10 px-2 text-xs font-medium shadow-[inset_0_-1px_0_var(--border)]">
      <div className="flex items-center gap-0.5">
        <span>{label}</span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label={`${label} ${tk.table.columnMenu}`}
              className="text-muted-foreground hover:text-foreground -mr-1 flex size-5 shrink-0 items-center justify-center rounded opacity-0 transition-opacity group-hover/th:opacity-100 focus-visible:opacity-100 has-[[data-state=open]]:opacity-100"
            >
              <ChevronDown className="size-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-40">
            {columnId === "createdAt" && (
              <>
                <DropdownMenuLabel>{tk.table.timeFormat}</DropdownMenuLabel>
                {(["absolute", "relative"] as const).map((format) => (
                  <DropdownMenuItem
                    key={format}
                    onSelect={() => onSetTimeFormat(format)}
                  >
                    <Check
                      className={cn(
                        "size-4",
                        prefs.timeFormat !== format && "invisible",
                      )}
                    />
                    {format === "absolute"
                      ? tk.table.timeFormatAbsolute
                      : tk.table.timeFormatRelative}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
              </>
            )}
            {columnId === "size" && (
              <>
                <DropdownMenuLabel>{tk.table.sizeUnit}</DropdownMenuLabel>
                {(["kb", "mb"] as const).map((unit) => (
                  <DropdownMenuItem
                    key={unit}
                    onSelect={() => onSetSizeUnit(unit)}
                  >
                    <Check
                      className={cn(
                        "size-4",
                        prefs.sizeUnit !== unit && "invisible",
                      )}
                    />
                    {unit === "kb" ? tk.table.sizeUnitKb : tk.table.sizeUnitMb}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuItem onSelect={() => onToggleColumn(columnId)}>
              <EyeOff className="size-4" />
              {tk.table.hideColumn}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </th>
  );
}

/**
 * 状态单元格（2026-09-03 自 tbody 内联 IIFE 提取）：圆点 + 小字单行，失败态
 * 把「友好原因 + 重试」收进悬停卡片（HoverCard 支持交互内容，Tooltip 不支持），
 * path_status 非空时悬停出三路分解。提取的直接动因是接上统一的列显隐门控：
 * 其余各列都是「短块 + 条件渲染」，90 行内联块既压不住行体，也无法跟着 prefs 收缩。
 */
function DocumentStatusCell({
  doc,
  onRetryDocument,
}: {
  doc: KnowledgeDocument;
  onRetryDocument: (docId: string) => void;
}) {
  const { t } = useI18n();
  const tk = t.knowledge;
  const indicator = (
    <span
      className="relative flex w-fit items-center gap-1"
      data-testid={doc.path_status ? "path-status-trigger" : undefined}
    >
      {/* 悬挂标记：-left-2.5 = 点 6px + 间隙 4px，与 td 的 px-2 配对，
        文字左缘才压得住表头那条线 */}
      <span
        aria-hidden
        className={cn(
          "absolute top-1/2 -left-2.5 size-1.5 -translate-y-1/2 rounded-full",
          STATUS_DOT_CLASS[doc.status] ?? "bg-muted-foreground/60",
        )}
      />
      <span
        className={cn(
          "text-xs",
          doc.status === "failed"
            ? "text-destructive"
            : "text-muted-foreground",
        )}
      >
        {tk.status[doc.status] ?? doc.status}
      </span>
      {/* 百分比只在 indexing 显示——前置阶段（解析/切片）无可测进度，不挂无信息量的 0% */}
      {doc.status === "indexing" && (
        <span className="text-muted-foreground text-xs">
          {doc.progress_percent}%
        </span>
      )}
    </span>
  );
  // 失败态（2026-08-31）：重试不占操作列，悬停失败状态出卡片；行级 ⋯ 与右键
  // 菜单都保留重试兜底，所以本列被隐藏时重试入口不会跟着消失。
  // 降级态（2026-10-04 D2=甲）：ready+任一腿 degraded 复用同款重试卡（说明不点名
  // 具体腿，明细行自证）；干净行保持 Tooltip。
  // P3：path_status 非 null 才挂悬停（老行/未进索引不展示）。
  const degraded = doc.status === "ready" && hasDegradedLeg(doc.path_status);
  const content =
    doc.status === "failed" ? (
      <HoverCard closeDelay={200} openDelay={150}>
        <HoverCardTrigger asChild>
          <span className="cursor-default" data-testid="doc-retry-trigger">
            {indicator}
          </span>
        </HoverCardTrigger>
        <HoverCardContent
          align="start"
          className="w-60 p-3"
          data-testid="doc-retry-card"
          side="top"
        >
          <p className="text-muted-foreground mb-2 text-xs">
            {tk.docErrors[classifyDocError(doc.error)]}
          </p>
          <Button
            className="h-7 gap-1.5 px-2.5"
            size="sm"
            onClick={() => onRetryDocument(doc.id)}
          >
            <RotateCcw className="size-3.5" />
            {tk.retryDocument}
          </Button>
        </HoverCardContent>
      </HoverCard>
    ) : degraded ? (
      <HoverCard closeDelay={200} openDelay={150}>
        <HoverCardTrigger asChild>
          <span className="cursor-default" data-testid="doc-retry-trigger">
            {indicator}
          </span>
        </HoverCardTrigger>
        <HoverCardContent
          align="start"
          className="w-60 p-3"
          data-testid="doc-retry-card"
          side="top"
        >
          <p className="text-muted-foreground mb-2 text-xs">
            {tk.degradedRetryHint}
          </p>
          <Button
            className="h-7 gap-1.5 px-2.5"
            size="sm"
            onClick={() => onRetryDocument(doc.id)}
          >
            <RotateCcw className="size-3.5" />
            {tk.retryDocument}
          </Button>
          <div className="mt-2">
            <PathStatusBreakdown doc={doc} />
          </div>
        </HoverCardContent>
      </HoverCard>
    ) : doc.path_status ? (
      <Tooltip content={<PathStatusBreakdown doc={doc} />}>{indicator}</Tooltip>
    ) : (
      indicator
    );
  // 单元格单行（2026-08-31）：错误行已删，不再需要 flex-col 叠放，nowrap
  // 防换行（图 1 反馈失败行被撑高）。
  return <td className="px-2 py-2 whitespace-nowrap">{content}</td>;
}

/** 任一腿 degraded（RFC §5.2 D1=甲：caption/graph/视频腿统一）——降级=ready+标记，
    与后端 ``has_degraded_leg`` 同判据；整篇重试入口的条件源。 */
function hasDegradedLeg(
  pathStatus: KnowledgeDocument["path_status"],
): boolean {
  return Object.values(pathStatus ?? {}).some((state) => state === "degraded");
}

/**
 * Documents pane of the middle column (spec §5.2/§3.6). Presentational: the
 * page owns data fetching, polling (via `useDocuments`), and mutations.
 * Library-level actions (rename/delete/generate wiki) live in the
 * `MiddleTabs` header row — this pane owns document actions only (upload,
 * search/sort, row operations).
 */
/** One filename per badge kind — the empty state's nine-grid doubles as a
 * quiet "all these formats are welcome" hint. `readme` (no suffix) lands on
 * the muted unknown sheet so the grid ends soft instead of loud. */
const EMPTY_STATE_SAMPLES = [
  "report.pdf",
  "notes.docx",
  "data.xlsx",
  "deck.pptx",
  "app.py",
  "photo.png",
  "video.mp4",
  "bundle.zip",
  "readme",
];

/**
 * 空态（2026-09-01）：降调九宫格 + 一句短文案，克制不抢戏（上传入口留在库菜单与整面拖放）。
 * 九宫格默认半透明垫场，悬停恢复全彩并上浮一格（彩蛋）。
 * 拖入识别双态（probe）：接受类型对应图标放大点亮；全部被拒时整体降灰，
 * 放下前就告知结果，不白跑一次上传。
 */
function EmptyDocumentsState({ probe }: { probe: DragProbe | null }) {
  const { t } = useI18n();
  const tk = t.knowledge;
  const lit = probe ? new Set(probe.litKinds) : null;
  const dimAll = probe !== null && !probe.anyAccepted;
  return (
    // absolute inset-0（2026-09-04 修居中回归）：空态现在是 ScrollArea 的子节点，
    // 而 Viewport 内层测量 wrapper 是 auto 高，h-full 会回退 auto 塌成内容高→靠上；
    // 改锚定 ScrollArea Root（relative）精确填满滚动区，恢复水平+垂直居中。
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-5 px-4 py-10 text-center">
      <div className="grid grid-cols-3 gap-3" data-testid="empty-doc-icons">
        {EMPTY_STATE_SAMPLES.map((name) => {
          const isLit = lit?.has(fileTypeKind(name)) ?? false;
          return (
            <FileTypeBadge
              key={name}
              fileName={name}
              className={cn(
                "size-8 cursor-default transition-all duration-150",
                // 静态态：半透明垫场 + 悬停彩蛋。
                probe === null &&
                  "opacity-60 hover:-translate-y-1 hover:opacity-100",
                // 拖入态：点亮的放大全彩，其余（或全拒时全部）降灰。
                probe !== null && (dimAll || !isLit) && "opacity-25",
                probe !== null && !dimAll && isLit && "scale-125 opacity-100",
              )}
            />
          );
        })}
      </div>
      <p className="text-muted-foreground text-sm">{tk.emptyDocuments}</p>
    </div>
  );
}

export function DocumentPanel({
  kb,
  documents,
  onUpload,
  onDeleteDocument,
  onRetryDocument,
  onOpenChunks,
  onDownload,
  onGenerateQuestion = () => undefined,
  supportedSuffixes,
  failures = [],
  onDismissFailure = () => undefined,
  onDismissAllFailures = () => undefined,
}: {
  kb: KnowledgeBase;
  documents: KnowledgeDocument[];
  onUpload: (files: File[]) => void;
  onDeleteDocument: (docId: string) => Promise<void> | void;
  onRetryDocument: (docId: string) => void;
  onOpenChunks: (doc: KnowledgeDocument) => void;
  /** 下载原文（2026-09-10 回环导出）：页面层触发浏览器下载（源文件路由），
      本层只挂菜单项（行尾三个点主入口 + 右键兜底，项目惯例双入口）；
      未提供时不渲染菜单项（复用方不关心下载）。 */
  onDownload?: (doc: KnowledgeDocument) => void;
  /** 右键快捷出题（2026-09-02）：页面层持有触发与通知（合成 hook + toast），
      本层只负责菜单项显隐（仅就绪文档可选）与回调传参（单篇/选中集）。 */
  onGenerateQuestion?: (docIds: string[]) => void;
  /** Upload allowlist (Task 6, spec §6): drag-drop pre-upload intercept. */
  supportedSuffixes: readonly string[];
  /** 失败通知面板（2026-08-31）：状态在页面层（useDocFailureNotifier），
      本层只负责渲染在 tab 内右下角——全局 toast 已退出文档错误链路。 */
  failures?: DocFailureEntry[];
  onDismissFailure?: (key: string) => void;
  onDismissAllFailures?: () => void;
}) {
  const { t, locale } = useI18n();
  const tk = t.knowledge;
  // 列偏好（2026-09-02，方案 Task 4/5）：per-kb 列显隐 + 时间格式 + 大小单位。
  const { prefs, toggleColumn, setTimeFormat, setSizeUnit, resetColumns } =
    useDocTablePrefs(kb.id);
  const [dragActive, setDragActive] = useState(false);
  // Drag-in type probe: which kinds light up / whether the batch is rejected.
  const [dragProbe, setDragProbe] = useState<DragProbe | null>(null);
  const probeKeyRef = useRef("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{
    key: DocumentSortKey;
    direction: SortDirection;
  }>(DEFAULT_DOCUMENT_SORT);
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(
    new Set(),
  );
  // Batch delete reuses the single-doc confirm dialog with a target list.
  const [deleteTargets, setDeleteTargets] = useState<string[] | null>(null);

  const stats = aggregateDocumentStats(documents);
  // The list endpoint returns the full collection, so the toolbar filter and
  // sort stay client-side (spec §5.2); the stats row always aggregates the
  // unfiltered list.
  const visibleDocuments = useMemo(
    () =>
      sortDocuments(
        filterDocuments(documents, query),
        sort.key,
        sort.direction,
      ),
    [documents, query, sort],
  );

  // Selection (checkbox model, spec §5.2): filtering clears it so a bulk
  // delete can never hit rows the user can no longer see.
  const updateQuery = (value: string) => {
    setQuery(value);
    setSelectedIds(new Set());
  };
  const visibleIds = visibleDocuments.map((doc) => doc.id);
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const someVisibleSelected = visibleIds.some((id) => selectedIds.has(id));
  const headerChecked = allVisibleSelected
    ? true
    : someVisibleSelected
      ? "indeterminate"
      : false;
  const toggleSelectAll = () => {
    setSelectedIds(allVisibleSelected ? new Set() : new Set(visibleIds));
  };
  const toggleSelect = (docId: string, checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(docId);
      } else {
        next.delete(docId);
      }
      return next;
    });
  };
  // File-manager convention: right-clicking an unselected row selects just
  // that row; right-clicking a selected row keeps the batch context.
  const handleRowContextMenu = (docId: string) => {
    if (!selectedIds.has(docId)) {
      setSelectedIds(new Set([docId]));
    }
  };
  // 批量快捷出题（2026-09-02）：全部选中文档就绪才启用——任一篇未就绪
  // 后端会整批 409，不如不亮菜单项；多篇联合出一条跨文档题。
  const allSelectedReady =
    selectedIds.size > 0 &&
    [...selectedIds].every(
      (id) => documents.find((item) => item.id === id)?.status === "ready",
    );
  const confirmDeleteTargets = async () => {
    if (!deleteTargets) {
      return;
    }
    const removed = new Set(deleteTargets);
    await Promise.allSettled(
      deleteTargets.map((id) => Promise.resolve(onDeleteDocument(id))),
    );
    setSelectedIds(
      (current) => new Set([...current].filter((id) => !removed.has(id))),
    );
    setDeleteTargets(null);
  };

  const handleFiles = (files: FileList | File[] | null) => {
    if (!files || files.length === 0) return;
    // Task 6: pre-upload allowlist intercept for drag-drop (no picker gate here).
    const { accepted, rejected } = partitionFilesBySuffix(
      Array.from(files),
      supportedSuffixes,
    );
    if (rejected.length > 0) {
      toast.error(
        tk.unsupportedFilesSkipped(rejected.map((f) => f.name).join(", ")),
      );
    }
    if (accepted.length > 0) {
      onUpload(accepted);
    }
  };

  return (
    <div
      className={cn(
        "relative flex h-full flex-col",
        dragActive && "bg-muted/40",
      )}
      data-testid="document-dropzone"
      onDragOver={(event) => {
        event.preventDefault();
        setDragActive(true);
        // Type probe: dragover exposes item MIME types, so the nine-grid
        // can light/dim before anything is dropped. dragover fires on every
        // mouse move — only a changed verdict re-renders. Drags with no file
        // items (dragged text/links) get no verdict at all.
        const probe = probeDraggedItems(
          event.dataTransfer?.items,
          supportedSuffixes,
        );
        const verdict = probe.anyAccepted || probe.anyRejected ? probe : null;
        const key = probeSignature(verdict);
        if (key !== probeKeyRef.current) {
          probeKeyRef.current = key;
          setDragProbe(verdict);
        }
      }}
      onDragLeave={(event) => {
        // 只有真正离开面板才复位——在九宫格图标间穿梭时，子元素/间隙会向根节点
        // 冒泡 dragleave，若照单全收会与 dragover 逐帧震荡（遮罩与图标闪烁）。
        if (event.currentTarget.contains(event.relatedTarget as Node | null))
          return;
        setDragActive(false);
        probeKeyRef.current = "";
        setDragProbe(null);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragActive(false);
        probeKeyRef.current = "";
        setDragProbe(null);
        handleFiles(event.dataTransfer?.files ?? null);
      }}
    >
      {/* The library header row (kb name + overflow menu incl. upload)
          lives in `MiddleTabs`; this pane starts at its own toolbar.
          Dragging files anywhere onto this pane also uploads. */}

      {/* Toolbar（2026-09-02 批量栏退役）：搜索 + 排序常驻；批量动作（删除所选/
          取消选择）全部由右键菜单承接——原位切换曾是抖动解法，菜单承接后
          切换本身成了冗余；h-11 稳定容器定高保留。 */}
      <div className="flex h-11 items-center gap-2 px-4">
        <div className="flex w-full items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <Search className="text-muted-foreground absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
            <Input
              aria-label={tk.searchDocuments}
              className="h-7 pr-7 pl-7 text-xs"
              placeholder={tk.searchDocuments}
              value={query}
              onChange={(event) => updateQuery(event.target.value)}
            />
            {query && (
              <button
                aria-label={tk.clearSearch}
                className="text-muted-foreground hover:text-foreground absolute top-1/2 right-1.5 -translate-y-1/2"
                type="button"
                onClick={() => updateQuery("")}
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              {/* size-7（28px）与搜索框 h-7 同高——icon-sm（32px）会把工具栏
                撑得比 wiki tab 搜索栏高 4px。 */}
              <Button
                aria-label={tk.sortDocuments}
                className="size-7"
                size="icon-sm"
                variant="ghost"
              >
                <ArrowUpDown className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuLabel>{tk.sortDocuments}</DropdownMenuLabel>
              {SORT_OPTIONS.map((option) => (
                <DropdownMenuItem
                  key={option.key}
                  onSelect={() =>
                    setSort((current) => ({ ...current, key: option.key }))
                  }
                >
                  <Check
                    className={cn(
                      "size-4",
                      sort.key !== option.key && "invisible",
                    )}
                  />
                  {tk.sort[option.labelKey]}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              {(["asc", "desc"] as const).map((direction) => (
                <DropdownMenuItem
                  key={direction}
                  onSelect={() =>
                    setSort((current) => ({ ...current, direction }))
                  }
                >
                  <Check
                    className={cn(
                      "size-4",
                      sort.direction !== direction && "invisible",
                    )}
                  />
                  {tk.sort[direction]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Document table (horizontal scroll protects the columns on narrow
          widths; 2026-08-31 操作列瘦身为尾部窄列，只承接悬停淡入的三个点) */}
      {/* 内容区：遮罩的定位上下文只盖表格区，不包住工具栏；外层不滚动，
          遮罩不随表格滚动。内层才是滚动容器。 */}
      <div className="relative min-h-0 flex-1">
        {/* Drop feedback overlay: makes the drop affordance explicit while a
            file hovers over the panel (the root bg tint alone is too subtle).
            Empty kb: border-only overlay so the nine-grid probe stays visible,
            hint pinned to the bottom; all-rejected drags swap the copy. */}
        {dragActive &&
          (documents.length === 0 ? (
            <div
              className="pointer-events-none absolute inset-2 z-10 rounded-lg border-2 border-dashed"
              data-testid="document-drop-overlay"
            >
              <p className="text-muted-foreground absolute inset-x-0 bottom-3 flex justify-center">
                <span className="bg-background flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium shadow-sm">
                  <Upload className="size-3.5" />
                  {dragProbe && dragProbe.anyRejected && !dragProbe.anyAccepted
                    ? tk.dropUnsupported
                    : tk.dropToUpload}
                </span>
              </p>
            </div>
          ) : (
            <div
              className="bg-background/70 pointer-events-none absolute inset-2 z-20 flex items-center justify-center rounded-lg border-2 border-dashed"
              data-testid="document-drop-overlay"
            >
              <p className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
                <Upload className="size-4" />
                {tk.dropToUpload}
              </p>
            </div>
          ))}
        {/* 百科 Tab 容器同款 overlay 滚动条（2026-09-04）：文档表纵+横滚改 ScrollArea
            （horizontal 接管 min-w-[34rem] 横滚；吸顶表头的滚动祖先变为 Viewport，sticky 不变）。 */}
        <ScrollArea
          className="h-full"
          horizontal
          scrollHideDelay={2000}
          type="scroll"
        >
          {documents.length === 0 ? (
            <EmptyDocumentsState probe={dragProbe} />
          ) : visibleDocuments.length === 0 ? (
            <p className="text-muted-foreground px-4 py-10 text-center text-sm">
              {tk.noMatchingDocuments}
            </p>
          ) : (
            <table className="w-full min-w-[34rem] border-separate border-spacing-0 text-sm">
              <thead>
                {/* 吸顶表头（2026-09-02）：折叠模式下粘性单元格的边框会随滚动丢失，
                  故表格改 border-separate。发丝线用 inset 阴影而非 border：
                  border 参与盒高，会使 th 高度随复选框状态在 36.13↔36.00 间
                  重取整，击穿 h-9 钉高——勾选时行跳动复发的根因；阴影不
                  参与布局，h-9 重新成为行高唯一裁决者。 */}
                {/* 表头右键菜单（2026-09-02 Task 7）：与末尾 Columns 按钮同内容的列显隐
                  总控，作键盘/触屏无悬停场景的兜底（项目惯例：可见主入口 + 右键兜底）。
                  Trigger asChild 直接落在 tr 上（thead 的 DOM 子仍是 tr，Content 走 portal）。 */}
                <ContextMenu>
                  <ContextMenuTrigger asChild>
                    <tr className="group/colhead text-muted-foreground h-9 text-left text-xs whitespace-nowrap">
                      {/* 复选框列用内层 flex 几何居中（2026-09-02）：inline strut 居中受字号/
                    行高环境影响（12/16 strut 偏上 1.7，14/20 才正中），两表口径不同就错位；
                    flex 按盒子几何居中，与字体环境无关。不能给 th 自身挂 flex——
                    th 会脱出表格布局、表头高度塌陷到 16 */}
                      <th className="bg-background sticky top-0 z-10 w-8 px-2 text-xs shadow-[inset_0_-1px_0_var(--border)]">
                        <div className="flex h-9 items-center">
                          <Checkbox
                            aria-label={tk.selectAllDocuments}
                            checked={headerChecked}
                            onCheckedChange={toggleSelectAll}
                          />
                        </div>
                      </th>
                      <th className="bg-background sticky top-0 z-10 px-2 text-xs font-medium shadow-[inset_0_-1px_0_var(--border)]">
                        {tk.table.name}
                      </th>
                      {/* 状态提到上传者前（2026-09-02）：状态是核心高频元数据（直接决定用户操作），
                    上传者在个人库信息量低（几乎都是「我」），故状态紧随名称。
                    09-03 起接入统一列显隐：表头换 HideableColumnHeader，chevron
                    菜单只有「隐藏列」（状态无格式/单位可切）。 */}
                      {!prefs.hidden.includes("status") && (
                        <HideableColumnHeader
                          columnId="status"
                          label={tk.table.status}
                          prefs={prefs}
                          onToggleColumn={toggleColumn}
                          onSetTimeFormat={setTimeFormat}
                          onSetSizeUnit={setSizeUnit}
                        />
                      )}
                      {!prefs.hidden.includes("uploader") && (
                        <HideableColumnHeader
                          columnId="uploader"
                          label={tk.table.uploader}
                          prefs={prefs}
                          onToggleColumn={toggleColumn}
                          onSetTimeFormat={setTimeFormat}
                          onSetSizeUnit={setSizeUnit}
                        />
                      )}
                      {!prefs.hidden.includes("createdAt") && (
                        <HideableColumnHeader
                          columnId="createdAt"
                          label={tk.table.createdAt}
                          prefs={prefs}
                          onToggleColumn={toggleColumn}
                          onSetTimeFormat={setTimeFormat}
                          onSetSizeUnit={setSizeUnit}
                        />
                      )}
                      {/* 数值列表头左对齐（与文本列一致，2026-08-31 用户拍板），
                    数值内容整体靠右 + tabular-nums，单位右缘自成列 */}
                      {!prefs.hidden.includes("size") && (
                        <HideableColumnHeader
                          columnId="size"
                          label={tk.table.size}
                          prefs={prefs}
                          onToggleColumn={toggleColumn}
                          onSetTimeFormat={setTimeFormat}
                          onSetSizeUnit={setSizeUnit}
                        />
                      )}
                      {!prefs.hidden.includes("chunks") && (
                        <HideableColumnHeader
                          columnId="chunks"
                          label={tk.table.chunks}
                          prefs={prefs}
                          onToggleColumn={toggleColumn}
                          onSetTimeFormat={setTimeFormat}
                          onSetSizeUnit={setSizeUnit}
                        />
                      )}
                      {/* 尾部窄列（2026-08-31）：数据行承接悬停三个点；表头（2026-09-02 Task 6）
                    放 hover 淡入的「列」总控按钮——零新增列、不占工具栏，与数据行三点同列
                    对齐（表头=列级操作，数据行=行级操作）。列出可隐藏列勾选显隐 + 全部显示。 */}
                      <th className="bg-background sticky top-0 z-10 w-10 shadow-[inset_0_-1px_0_var(--border)]">
                        <div className="flex h-9 items-center justify-end pr-1">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button
                                type="button"
                                aria-label={tk.table.columns}
                                className="text-muted-foreground hover:text-foreground flex size-6 items-center justify-center rounded opacity-0 transition-opacity group-hover/colhead:opacity-100 focus-visible:opacity-100 has-[[data-state=open]]:opacity-100"
                              >
                                <Columns className="size-4" />
                              </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-40">
                              <DropdownMenuLabel>
                                {tk.table.columns}
                              </DropdownMenuLabel>
                              {HIDEABLE_COLUMNS.map((id) => (
                                <DropdownMenuItem
                                  key={id}
                                  onSelect={() => toggleColumn(id)}
                                >
                                  <Check
                                    className={cn(
                                      "size-4",
                                      prefs.hidden.includes(id) && "invisible",
                                    )}
                                  />
                                  {tk.table[id]}
                                </DropdownMenuItem>
                              ))}
                              <DropdownMenuSeparator />
                              <DropdownMenuItem onSelect={resetColumns}>
                                <Eye className="size-4" />
                                {tk.table.showAllColumns}
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </th>
                    </tr>
                  </ContextMenuTrigger>
                  <ContextMenuContent className="w-40">
                    <ContextMenuLabel>{tk.table.columns}</ContextMenuLabel>
                    {HIDEABLE_COLUMNS.map((id) => (
                      <ContextMenuItem
                        key={id}
                        onSelect={() => toggleColumn(id)}
                      >
                        <Check
                          className={cn(
                            "size-4",
                            prefs.hidden.includes(id) && "invisible",
                          )}
                        />
                        {tk.table[id]}
                      </ContextMenuItem>
                    ))}
                    <ContextMenuSeparator />
                    <ContextMenuItem onSelect={resetColumns}>
                      <Eye className="size-4" />
                      {tk.table.showAllColumns}
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>
              </thead>
              <tbody>
                {visibleDocuments.map((doc) => {
                  const isSelected = selectedIds.has(doc.id);
                  return (
                    <ContextMenu key={doc.id}>
                      <ContextMenuTrigger asChild>
                        <tr
                          className={cn(
                            // 行分隔靠留白+悬停底色（2026-08-31）：去 border-b，
                            // 对齐 Drive/Notion 无框表风格，结构线只留表头与统计行两条。
                            "group hover:bg-muted/50 cursor-pointer",
                            isSelected && "bg-muted/60",
                          )}
                          data-selected={isSelected}
                          onClick={() => onOpenChunks(doc)}
                          onContextMenu={() => handleRowContextMenu(doc.id)}
                        >
                          <td
                            className="w-8 px-2 py-2"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <Checkbox
                              aria-label={`${tk.selectDocument}: ${doc.name}`}
                              checked={isSelected}
                              className={cn(
                                "opacity-0 transition-opacity group-hover:opacity-100 data-[state=checked]:opacity-100",
                                selectedIds.size > 0 && "opacity-100",
                              )}
                              onCheckedChange={(checked) =>
                                toggleSelect(doc.id, checked === true)
                              }
                            />
                          </td>
                          <td className="max-w-48 px-2 py-2">
                            <div className="flex items-center gap-2">
                              {/* 类型徽章：设计稿 56 网格原样，20px 是保得住折角与细节条的 S 档下限（16px 会糊成 1px 发丝） */}
                              <FileTypeBadge
                                className="size-5 shrink-0"
                                fileName={doc.name}
                              />
                              <span className="truncate">{doc.name}</span>
                              {/* 视频行时长徽章（spec 2026-09-08 §5）：胶片图标已由
                                  FileTypeBadge 按 .mp4/.mov/.mkv 后缀自动渲染，此处只补时长——
                                  仅列表接口注入了 duration_ms 的已物化视频文档才有（文本文档/
                                  解析中的视频行不渲染）。镜头数与「切片数」列重复，2026-09-09 移除。 */}
                              {doc.duration_ms != null && (
                                <span
                                  className="text-muted-foreground flex shrink-0 items-center gap-1 text-xs tabular-nums"
                                  data-testid="doc-video-meta"
                                >
                                  <span title={tk.videoDuration}>
                                    {formatVideoDuration(doc.duration_ms)}
                                  </span>
                                </span>
                              )}
                            </div>
                          </td>
                          {/* 状态列（2026-09-03 接入列显隐）：单元格内容已提为
                      DocumentStatusCell，与其他可隐藏列同构（短块 + 条件渲染）。 */}
                          {!prefs.hidden.includes("status") && (
                            <DocumentStatusCell
                              doc={doc}
                              onRetryDocument={onRetryDocument}
                            />
                          )}
                          {/* 上传者内容内缩一档（2026-08-31）：表头 12px 浅灰、内容 14px 深色，
                            重墨色视觉上会「抢出来」，pl-3 比表头 px-2 多缩 4px 做光学校正。
                            列序：状态提前后，上传者落在状态与时间之间（2026-09-02）。 */}
                          {!prefs.hidden.includes("uploader") && (
                            <td className="text-muted-foreground py-2 pr-2 pl-3">
                              {doc.uploader_id === kb.owner_id
                                ? tk.uploaderMe
                                : doc.uploader_id}
                            </td>
                          )}
                          {/* 时间列等宽数字（2026-08-31）：格式已零填充定长，再加 tabular-nums
                      使 1/2 同宽，行间时分纵向对齐（与大小/切片数同方案）。
                      格式可切换（2026-09-02 Task 4）：绝对（Intl 日期）↔ 相对（N 天前）。 */}
                          {!prefs.hidden.includes("createdAt") && (
                            <td className="text-muted-foreground px-2 py-2 whitespace-nowrap tabular-nums">
                              {prefs.timeFormat === "relative"
                                ? formatKnowledgeRelativeTime(
                                    doc.created_at,
                                    locale,
                                  )
                                : formatKnowledgeTimestamp(
                                    doc.created_at,
                                    locale,
                                  )}
                            </td>
                          )}
                          {/* 大小（2026-08-31 KB 默认）：每格带单位后缀（表头不带单位），
                      纯数字 + 右对齐；精确字节收进悬停 Tooltip。单位可切换 KB↔MB
                      （2026-09-02 Task 4）。 */}
                          {!prefs.hidden.includes("size") && (
                            <td className="text-muted-foreground px-2 py-2 text-right whitespace-nowrap tabular-nums">
                              <Tooltip
                                content={`${doc.size_bytes.toLocaleString()} B`}
                              >
                                <span data-testid="doc-size-value">
                                  {prefs.sizeUnit === "mb"
                                    ? `${formatMb(doc.size_bytes)} MB`
                                    : `${formatKb(doc.size_bytes)} KB`}
                                </span>
                              </Tooltip>
                            </td>
                          )}
                          {!prefs.hidden.includes("chunks") && (
                            <td className="text-muted-foreground px-2 py-2 text-right tabular-nums">
                              {doc.chunk_count ?? "—"}
                            </td>
                          )}
                          {/* 悬停三个点窄列（2026-08-31）：预留列不遮切片数/大小——
                      悬停/选中/键盘聚焦时淡入；菜单镜像右键菜单（查看切片/重试/删除），
                      右键菜单保留兜底 */}
                          <td
                            className="w-10 px-1 py-2"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <div
                              className={cn(
                                "flex justify-end transition-opacity",
                                "opacity-0 group-hover:opacity-100 focus-within:opacity-100 has-[[data-state=open]]:opacity-100",
                                isSelected && "opacity-100",
                              )}
                              data-testid="doc-row-more"
                            >
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button
                                    aria-label={tk.moreActions}
                                    className="size-6"
                                    size="icon"
                                    variant="ghost"
                                  >
                                    <MoreHorizontal className="size-4" />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent
                                  align="end"
                                  className="w-40"
                                >
                                  <DropdownMenuItem
                                    onSelect={() => onOpenChunks(doc)}
                                  >
                                    <FileText className="size-4" />
                                    {tk.openChunks}
                                  </DropdownMenuItem>
                                  {onDownload && (
                                    <DropdownMenuItem
                                      onSelect={() => onDownload(doc)}
                                    >
                                      <Download className="size-4" />
                                      {tk.downloadDocument}
                                    </DropdownMenuItem>
                                  )}
                                  {(doc.status === "failed" ||
                                    (doc.status === "ready" &&
                                      hasDegradedLeg(doc.path_status))) && (
                                    <DropdownMenuItem
                                      onSelect={() => onRetryDocument(doc.id)}
                                    >
                                      <RotateCcw className="size-4" />
                                      {tk.retryDocument}
                                    </DropdownMenuItem>
                                  )}
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    variant="destructive"
                                    onSelect={() => setDeleteTargets([doc.id])}
                                  >
                                    <Trash2 className="size-4" />
                                    {tk.deleteDocument}
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </div>
                          </td>
                        </tr>
                      </ContextMenuTrigger>
                      <ContextMenuContent className="w-44">
                        {isSelected && selectedIds.size > 1 ? (
                          <>
                            <ContextMenuLabel>
                              {tk.selectedCount(selectedIds.size)}
                            </ContextMenuLabel>
                            {/* 快捷出题（2026-09-02）：选中集联合出一条，合并进待审候选；
                              图标与评测页「生成考题」入口统一用 Sparkles；文案不带篇数，
                              避免窄面板下菜单项换行 */}
                            {allSelectedReady && (
                              <ContextMenuItem
                                onSelect={() =>
                                  runAfterMenuClose(() =>
                                    onGenerateQuestion([...selectedIds]),
                                  )
                                }
                              >
                                <Sparkles className="size-4" />
                                {tk.generateQuestionBatch}
                              </ContextMenuItem>
                            )}
                            {/* 取消选择是选择态的退出动作，属非破坏组：紧跟普通动作；
                              危险操作沉底并用分隔线单独隔离（2026-09-02 用户拍板）；
                              X 图标与批量操作栏的取消选择对称 */}
                            <ContextMenuItem
                              onSelect={() => setSelectedIds(new Set())}
                            >
                              <X className="size-4" />
                              {tk.cancelSelection}
                            </ContextMenuItem>
                            <ContextMenuSeparator />
                            <ContextMenuItem
                              variant="destructive"
                              onSelect={() =>
                                runAfterMenuClose(() =>
                                  setDeleteTargets([...selectedIds]),
                                )
                              }
                            >
                              <Trash2 className="size-4" />
                              {tk.deleteSelected}
                            </ContextMenuItem>
                          </>
                        ) : (
                          <>
                            <ContextMenuItem
                              onSelect={() =>
                                runAfterMenuClose(() => onOpenChunks(doc))
                              }
                            >
                              <FileText className="size-4" />
                              {tk.openChunks}
                            </ContextMenuItem>
                            {/* 下载不开第二弹层（锚点导航），无 pointer-events 交叠风险，
                                不像查看切片需 runAfterMenuClose 延后。 */}
                            {onDownload && (
                              <ContextMenuItem onSelect={() => onDownload(doc)}>
                                <Download className="size-4" />
                                {tk.downloadDocument}
                              </ContextMenuItem>
                            )}
                            {/* 快捷出题（2026-09-02）：仅就绪文档可选（无切片必 409），
                              为该篇出一条题，合并进评测页待审候选；图标与评测页入口统一 */}
                            {doc.status === "ready" && (
                              <ContextMenuItem
                                onSelect={() =>
                                  runAfterMenuClose(() =>
                                    onGenerateQuestion([doc.id]),
                                  )
                                }
                              >
                                <Sparkles className="size-4" />
                                {tk.generateQuestion}
                              </ContextMenuItem>
                            )}
                            {(doc.status === "failed" ||
                              (doc.status === "ready" &&
                                hasDegradedLeg(doc.path_status))) && (
                              <ContextMenuItem
                                onSelect={() => onRetryDocument(doc.id)}
                              >
                                <RotateCcw className="size-4" />
                                {tk.retryDocument}
                              </ContextMenuItem>
                            )}
                            {/* 取消选择（2026-09-02 用户拍板）：右键单选也会选中该行
                              （文件管理器惯例），退出选择态的入口两态对称；
                              非破坏组，危险操作仍沉底隔离 */}
                            <ContextMenuItem
                              onSelect={() => setSelectedIds(new Set())}
                            >
                              <X className="size-4" />
                              {tk.cancelSelection}
                            </ContextMenuItem>
                            <ContextMenuSeparator />
                            {/* 措辞对齐批量栏（2026-09-02）：右键即选中，此时删除目标
                              就是当前选择集——同屏两处措辞必须同一词汇（删除所选）；
                              行级悬停三个点菜单仍用「删除」（不依赖选择态，语义不同） */}
                            <ContextMenuItem
                              variant="destructive"
                              onSelect={() =>
                                runAfterMenuClose(() =>
                                  setDeleteTargets([doc.id]),
                                )
                              }
                            >
                              <Trash2 className="size-4" />
                              {tk.deleteSelected}
                            </ContextMenuItem>
                          </>
                        )}
                      </ContextMenuContent>
                    </ContextMenu>
                  );
                })}
              </tbody>
            </table>
          )}
        </ScrollArea>
      </div>

      {/* Bottom stats row (spec §3.6, aggregated client-side). Two nowrap segments
          (spec 2026-09-24 §7.2 甲): volume on the left, status counts on the right with
          the status column's own dots; a zero count stays silent instead of shouting "0". */}
      <div
        className="text-muted-foreground flex flex-wrap gap-x-3 border-t px-4 py-2 text-xs"
        data-testid="document-stats-row"
      >
        <span className="flex items-center gap-1 whitespace-nowrap">
          {tk.statsDocuments} {stats.total} · {tk.statsChunks}{" "}
          {stats.totalChunks} · {formatBytes(stats.totalBytes)}
        </span>
        <span className="ml-auto flex items-center gap-2 whitespace-nowrap">
          {(
            [
              ["ready", stats.ready],
              ["indexing", stats.inProgress],
              ["failed", stats.failed],
            ] as const
          ).map(([key, count]) =>
            count > 0 ? (
              <span key={key} className="flex items-center gap-1">
                <span
                  className={cn("size-1.5 rounded-full", STATUS_DOT_CLASS[key])}
                />
                {tk.status[key]} {count}
              </span>
            ) : null,
          )}
        </span>
      </div>

      {/* Document delete confirm */}
      <Dialog
        open={deleteTargets !== null}
        onOpenChange={(open) => !open && setDeleteTargets(null)}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{tk.deleteDocumentConfirmTitle}</DialogTitle>
            <DialogDescription>
              {tk.deleteDocumentConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTargets(null)}>
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void confirmDeleteTargets()}
            >
              {t.common.confirmDelete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 失败通知面板（2026-08-31）：绝对定位在 tab 内右下角，不跑到文档 tab 外侧；
          面板内重试复用行级 onRetryDocument（条目 key 即文档 id） */}
      <DocFailurePanel
        failures={failures}
        onDismiss={onDismissFailure}
        onDismissAll={onDismissAllFailures}
        onRetry={onRetryDocument}
      />
    </div>
  );
}
