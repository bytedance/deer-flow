"use client";

import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  Loader2,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
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
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import type { WikiGenerateMode } from "@/core/knowledge/api";
import {
  formatKnowledgeRelativeTime,
  formatKnowledgeTimestamp,
  stripSummaryHeading,
} from "@/core/knowledge/format";
import type { WikiEntrySummary } from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

import { runAfterMenuClose } from "./run-after-menu-close";

/**
 * Wiki entries section of the wiki tab (split-section layout): a collapsible
 * section — default expanded — that shares the tab's unified search box with
 * the manual-cards section below. Filtering is client-side (the entries list
 * is a full collection); a non-empty query with matches force-expands the
 * section for the duration of the search. Rows carry the document-table
 * interaction model: checkbox multi-select + batch bar + batch delete (the
 * confirm copy keeps the regeneration semantics), and a right-click context
 * menu (open / edit / delete; batch variant inside a multi-selection). Row
 * click opens the right-side entry drawer.
 */
export function WikiPanel({
  entries,
  loading = false,
  updating = false,
  updatingEntryIds = [],
  query = "",
  onOpenEntry,
  onDeleteEntry,
  onEditEntry,
  onRegenerateEntries,
  onGenerateWiki,
  onRebuildWiki,
}: {
  entries: WikiEntrySummary[];
  loading?: boolean;
  /**
   * Wiki 更新状态可见 (2026-08-14): a generation run is in flight — the
   * hint line stays up and dirty badges switch to 更新中 until the run
   * drains (the entries query polls while the backend reports generating).
   */
  updating?: boolean;
  /**
   * 局部更新在飞目标（2026-09-05）：非空时仅这些 entry 行显示「更新中」，
   * 其余 dirty 行保持「待更新」；空 + updating = 整库 run（全部 dirty 更新中）。
   */
  updatingEntryIds?: readonly string[];
  /** Unified wiki-tab search text (title + summary containment, client-side). */
  query?: string;
  onOpenEntry: (entry: WikiEntrySummary) => void;
  onDeleteEntry: (entry: WikiEntrySummary) => Promise<void> | void;
  /** Phase-3 Batch-1 P1: edit entry (opens WikiEditDialog) */
  onEditEntry?: (entry: WikiEntrySummary) => void;
  /**
   * 局部更新/重建 (2026-09-02): regenerate the hand-picked entries from their
   * entities' current chunks. Single right-click passes ``[entry.id]``; a
   * multi-selection passes the whole selected set. Disabled while ``updating``
   * (shares the library-level in-flight guard, so no overlapping LLM run).
   */
  onRegenerateEntries?: (entryIds: string[]) => void;
  /**
   * 百科维护（2026-09-04）：生成条目头部右键承接「更新百科/重建百科」，与搜索框旁
   * ⋯ 菜单同一套动作（此前头部右键无动作）。onRebuildWiki 打开重建确认弹窗。
   */
  onGenerateWiki?: (mode: WikiGenerateMode) => void;
  onRebuildWiki?: () => void;
}) {
  const { t, locale } = useI18n();
  const tk = t.knowledge;
  const tw = t.knowledge.wikiPanel;
  const [expanded, setExpanded] = useState(true);
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(
    new Set(),
  );
  // Batch delete reuses the single-entry confirm dialog with a target list.
  const [deleteTargets, setDeleteTargets] = useState<WikiEntrySummary[] | null>(
    null,
  );

  // Filtering clears the selection so a bulk delete can never hit rows the
  // user can no longer see (same rule as the document table). Render-time
  // derived-state reset avoids an effect round-trip.
  const [lastQuery, setLastQuery] = useState(query);
  if (lastQuery !== query) {
    setLastQuery(query);
    setSelectedIds(new Set());
  }

  const visibleEntries = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) {
      return entries;
    }
    return entries.filter(
      (entry) =>
        entry.title.toLowerCase().includes(needle) ||
        entry.summary.toLowerCase().includes(needle),
    );
  }, [entries, query]);

  // 搜索期间有匹配 → 强制展开（用户收起优先让位于"看到搜索结果"）。
  const searching = query.trim() !== "";
  const effectiveExpanded =
    expanded || (searching && visibleEntries.length > 0);

  // Selection (checkbox model, same as the document table).
  const visibleIds = visibleEntries.map((entry) => entry.id);
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
  const toggleSelect = (entryId: string, checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(entryId);
      } else {
        next.delete(entryId);
      }
      return next;
    });
  };
  // File-manager convention: right-clicking an unselected row selects just
  // that row; right-clicking a selected row keeps the batch context.
  const handleRowContextMenu = (entryId: string) => {
    if (!selectedIds.has(entryId)) {
      setSelectedIds(new Set([entryId]));
    }
  };
  const selectedEntries = () =>
    entries.filter((entry) => selectedIds.has(entry.id));
  const confirmDeleteTargets = async () => {
    if (!deleteTargets) {
      return;
    }
    const removed = new Set(deleteTargets.map((entry) => entry.id));
    await Promise.allSettled(
      deleteTargets.map((entry) => Promise.resolve(onDeleteEntry(entry))),
    );
    setSelectedIds(
      (current) => new Set([...current].filter((id) => !removed.has(id))),
    );
    setDeleteTargets(null);
  };

  return (
    <section
      className={cn(
        "bg-card dark:bg-muted flex flex-col overflow-hidden rounded-md border shadow-[0_1px_3px_rgba(26,24,20,0.06)] dark:shadow-[0_2px_6px_rgba(0,0,0,0.35)]",
        // 定高分屏（2026-09-03）：展开=flex-1 吃一份额定高度（两个都展开即 50/50）、
        // 收起=shrink-0 细条；列表在卡内 overflow-y-auto 内滚，取代外层单滚动。
        effectiveExpanded ? "min-h-0 flex-1" : "shrink-0",
      )}
      data-testid="wiki-entries-section"
    >
      {/* Section header: collapse toggle + count + select-all checkbox. The
          toggle and the checkbox are siblings so neither nests in a button. */}
      <div className="flex shrink-0 items-center gap-1 bg-[var(--wiki-ai-bg)] pr-3 pl-1.5 transition-colors hover:bg-[var(--wiki-ai-bg-hover)]">
        {/* 生成条目头部右键（2026-09-04）：承接搜索框旁 ⋯ 菜单的「更新百科/重建百科」
            （此前头部右键无动作）。左键仍是展开/收起。 */}
        <ContextMenu>
          <ContextMenuTrigger asChild>
            <button
              aria-expanded={effectiveExpanded}
              className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-4 py-2 text-left"
              data-testid="wiki-entries-toggle"
              type="button"
              onClick={() => setExpanded((value) => !value)}
            >
              {effectiveExpanded ? (
                <ChevronDown className="size-4" />
              ) : (
                <ChevronRight className="size-4" />
              )}
              <BookOpen className="size-4 shrink-0 text-[var(--wiki-ai)]" />
              <span className="text-sm font-medium">{tw.sectionTitle}</span>
              <span className="bg-card ml-1 inline-flex h-5 items-center rounded-full border border-[var(--wiki-ai-ring)] px-1.5 text-xs text-[var(--wiki-ai)] tabular-nums">
                {entries.length}
              </span>
              {/* 更新中徽章（2026-09-02）：原独立提示行挤占条目空间，收进头行——
                  spinner + 短文案「更新中」，完整说明进 tooltip；与 row 级 dirty/updating
                  徽章同款 h-5 py-0，在 toggle 按钮内故收起态也可见。 */}
              {updating && (
                <Tooltip content={tw.updatingHint}>
                  <Badge
                    className="ml-1 h-5 gap-1 py-0"
                    data-testid="wiki-updating-hint"
                    variant="secondary"
                  >
                    <Loader2 className="size-3 animate-spin" />
                    {tw.updating}
                  </Badge>
                </Tooltip>
              )}
            </button>
          </ContextMenuTrigger>
          <ContextMenuContent className="w-44">
            <ContextMenuItem
              disabled={updating}
              onSelect={() => onGenerateWiki?.("incremental")}
            >
              {updating ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <BookOpen className="size-4" />
              )}
              {updating ? tw.updating : tk.updateWiki}
            </ContextMenuItem>
            <ContextMenuItem
              disabled={updating}
              onSelect={() => runAfterMenuClose(() => onRebuildWiki?.())}
            >
              <RefreshCw className="size-4" />
              {tk.rebuildWiki}
            </ContextMenuItem>
          </ContextMenuContent>
        </ContextMenu>
        {effectiveExpanded && visibleEntries.length > 0 && (
          <Checkbox
            aria-label={tk.selectAllDocuments}
            checked={headerChecked}
            onCheckedChange={toggleSelectAll}
          />
        )}
      </div>

      {effectiveExpanded && (
        <>
          {/* 批量栏退役（2026-09-02）：插入式条推挤内容产生抖动；
              删除所选/取消选择全部由右键菜单承接 */}

          {loading && entries.length === 0 ? (
            <div className="text-muted-foreground flex flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
              <Loader2 className="size-8 animate-spin" />
              <p className="text-sm">{tw.loading}</p>
            </div>
          ) : visibleEntries.length === 0 ? (
            // 空态居中 + 放大图标（2026-09-04）：flex-1 撑满剩余高度、内容垂直水平居中；
            // BookOpen 放大淡化置于说明文字上方（对应本区图标，与我的条目 StickyNote 对称）。
            <div className="text-muted-foreground flex flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
              <BookOpen className="size-8 opacity-40" />
              <p className="text-sm">
                {entries.length === 0 ? tw.empty : tw.noMatches}
              </p>
            </div>
          ) : (
            <ScrollArea
              className="min-h-0 flex-1"
              scrollHideDelay={2000}
              type="scroll"
            >
              <ul
                className="flex flex-col px-2 py-2"
                data-testid="wiki-entry-list"
              >
                {visibleEntries.map((entry) => {
                  const isSelected = selectedIds.has(entry.id);
                  // 剥掉摘要开头的「# 标题」markdown 行（2026-09-03）：标题已单独渲染，正文保留
                  const summaryText = stripSummaryHeading(entry.summary);
                  // 行级更新中（2026-09-05）：目标行只要 ids 置位就显示「更新中」
                  // （不依赖库级 updating——202 ack→in-flight 间隙 updating 会短暂为假，
                  // 若与 updating 相与目标行会在间隙闪回「待更新」）；非目标 dirty 行
                  // 仅在整库 run（ids 空）时随 updating 显示更新中，局部 run 保持待更新。
                  const rowUpdating =
                    updatingEntryIds.includes(entry.id) ||
                    (updating && updatingEntryIds.length === 0);
                  return (
                    <li key={entry.id}>
                      <ContextMenu>
                        <ContextMenuTrigger asChild>
                          <div
                            className={cn(
                              "group hover:bg-muted/50 flex h-10 items-center gap-2 rounded-md px-2",
                              isSelected && "bg-muted/60",
                            )}
                            data-selected={isSelected}
                            data-testid={`wiki-entry-row-${entry.id}`}
                            onContextMenu={() => handleRowContextMenu(entry.id)}
                          >
                            <Checkbox
                              aria-label={`${tw.selectEntry}: ${entry.title}`}
                              checked={isSelected}
                              className={cn(
                                "shrink-0 opacity-0 transition-opacity group-hover:opacity-100 data-[state=checked]:opacity-100",
                                selectedIds.size > 0 && "opacity-100",
                              )}
                              onCheckedChange={(checked) =>
                                toggleSelect(entry.id, checked === true)
                              }
                            />
                            {/* 单行内联（2026-09-03）：图标 + 标题(hug,≤45%) + 摘要(fill,truncate,剥H1行+淡化 /70) 连读；
                              状态徽章/时间/⋯ 靠右。取代原「标题/摘要/时间」三行堆叠。 */}
                            <button
                              className="flex min-w-0 flex-1 items-center gap-2 text-left"
                              type="button"
                              onClick={() => onOpenEntry(entry)}
                            >
                              <BookOpen className="text-muted-foreground size-4 shrink-0" />
                              <span className="max-w-[45%] shrink-0 truncate text-sm font-medium">
                                {entry.title}
                              </span>
                              <span className="text-muted-foreground/70 min-w-0 flex-1 truncate text-xs">
                                {summaryText}
                              </span>
                            </button>
                            {entry.status === "dirty" && (
                              <Badge
                                className="h-5 shrink-0 gap-1.5 bg-[var(--wiki-dirty-bg)] py-0 text-[var(--wiki-dirty)]"
                                variant="secondary"
                              >
                                {rowUpdating ? (
                                  <Loader2 className="size-3 animate-spin" />
                                ) : (
                                  /* 待更新琥珀胶囊（spec ⑤）：圆点沿用文档 tab
                                     「圆点+文字」配方（size-1.5 rounded-full）。 */
                                  <span
                                    aria-hidden
                                    className="bg-[var(--wiki-dirty-dot)] size-1.5 shrink-0 rounded-full"
                                  />
                                )}
                                {rowUpdating ? tw.updating : tw.dirty}
                              </Badge>
                            )}
                            <Tooltip
                              content={`${tw.updatedAt} ${formatKnowledgeTimestamp(entry.updated_at, locale)}`}
                            >
                              <span className="text-muted-foreground shrink-0 truncate text-right text-xs tabular-nums">
                                {formatKnowledgeRelativeTime(
                                  entry.updated_at,
                                  locale,
                                )}
                              </span>
                            </Tooltip>
                            {/* 行尾 ⋯（2026-09-03）：镜像右键行级子集，取代 hover 浮现的编辑/删除；
                              opacity 门控淡入、打开时常驻（对齐文档 tab 末列三点惯例）。 */}
                            <div
                              className="shrink-0"
                              onClick={(event) => event.stopPropagation()}
                            >
                              <div
                                className={cn(
                                  "flex justify-end transition-opacity",
                                  "opacity-0 group-hover:opacity-100 focus-within:opacity-100 has-[[data-state=open]]:opacity-100",
                                  isSelected && "opacity-100",
                                )}
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
                                    className="w-44"
                                  >
                                    <DropdownMenuItem
                                      onSelect={() =>
                                        runAfterMenuClose(() =>
                                          onOpenEntry(entry),
                                        )
                                      }
                                    >
                                      <BookOpen className="size-4" />
                                      {tw.openEntry}
                                    </DropdownMenuItem>
                                    {onEditEntry && (
                                      <DropdownMenuItem
                                        onSelect={() =>
                                          runAfterMenuClose(() =>
                                            onEditEntry(entry),
                                          )
                                        }
                                      >
                                        <Pencil className="size-4" />
                                        {tw.editEntry}
                                      </DropdownMenuItem>
                                    )}
                                    {onRegenerateEntries && (
                                      <DropdownMenuItem
                                        disabled={updating}
                                        onSelect={() =>
                                          runAfterMenuClose(() =>
                                            onRegenerateEntries([entry.id]),
                                          )
                                        }
                                      >
                                        <RefreshCw className="size-4" />
                                        {tw.updateEntry}
                                      </DropdownMenuItem>
                                    )}
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem
                                      variant="destructive"
                                      onSelect={() =>
                                        runAfterMenuClose(() =>
                                          setDeleteTargets([entry]),
                                        )
                                      }
                                    >
                                      <Trash2 className="size-4" />
                                      {tw.deleteEntry}
                                    </DropdownMenuItem>
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              </div>
                            </div>
                          </div>
                        </ContextMenuTrigger>
                        <ContextMenuContent className="w-44">
                          {isSelected && selectedIds.size > 1 ? (
                            <>
                              <ContextMenuLabel>
                                {tk.selectedCount(selectedIds.size)}
                              </ContextMenuLabel>
                              {/* 结构节奏同文档右键菜单（2026-09-02 定稿）：普通动作 →
                                取消选择（X）→ 分隔线 → 危险操作沉底单独隔离 */}
                              {/* 局部更新（2026-09-02）：对选中集批量重生成；更新中禁用
                                （与库级生成共享 in-flight 互斥，防重叠 LLM 跑）。 */}
                              {onRegenerateEntries && (
                                <ContextMenuItem
                                  disabled={updating}
                                  onSelect={() =>
                                    runAfterMenuClose(() =>
                                      onRegenerateEntries([...selectedIds]),
                                    )
                                  }
                                >
                                  <RefreshCw className="size-4" />
                                  {tw.updateSelected}
                                </ContextMenuItem>
                              )}
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
                                    setDeleteTargets(selectedEntries()),
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
                                  runAfterMenuClose(() => onOpenEntry(entry))
                                }
                              >
                                <BookOpen className="size-4" />
                                {tw.openEntry}
                              </ContextMenuItem>
                              {onEditEntry && (
                                <ContextMenuItem
                                  onSelect={() =>
                                    runAfterMenuClose(() => onEditEntry(entry))
                                  }
                                >
                                  <Pencil className="size-4" />
                                  {tw.editEntry}
                                </ContextMenuItem>
                              )}
                              {/* 局部更新（2026-09-02）：右键即选中，单条重生成（同一机制
                                兼局部重建）；更新中禁用。 */}
                              {onRegenerateEntries && (
                                <ContextMenuItem
                                  disabled={updating}
                                  onSelect={() =>
                                    runAfterMenuClose(() =>
                                      onRegenerateEntries([entry.id]),
                                    )
                                  }
                                >
                                  <RefreshCw className="size-4" />
                                  {tw.updateEntry}
                                </ContextMenuItem>
                              )}
                              {/* 右键即选中，退出选择态入口两态对称（同文档规范） */}
                              <ContextMenuItem
                                onSelect={() => setSelectedIds(new Set())}
                              >
                                <X className="size-4" />
                                {tk.cancelSelection}
                              </ContextMenuItem>
                              <ContextMenuSeparator />
                              {/* 措辞对齐（同文档规范）：右键即选中，删除目标就是选择集 */}
                              <ContextMenuItem
                                variant="destructive"
                                onSelect={() =>
                                  runAfterMenuClose(() =>
                                    setDeleteTargets([entry]),
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
                    </li>
                  );
                })}
              </ul>
            </ScrollArea>
          )}
        </>
      )}

      {/* Entry delete confirm (regeneration semantics in the copy; the title
          carries the count in the batch case) */}
      <Dialog
        open={deleteTargets !== null}
        onOpenChange={(open) => !open && setDeleteTargets(null)}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>
              {deleteTargets && deleteTargets.length > 1
                ? tw.deleteBatchTitle(deleteTargets.length)
                : tw.deleteConfirmTitle}
            </DialogTitle>
            <DialogDescription>{tw.deleteConfirmDescription}</DialogDescription>
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
    </section>
  );
}
