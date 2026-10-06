"use client";

import {
  BookOpen,
  FolderPlus,
  Loader2,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import type { WikiGenerateMode } from "@/core/knowledge/api";
import type { WikiEntrySummary } from "@/core/knowledge/types";

import { ManualCardPanel } from "./manual-card-panel";
import { runAfterMenuClose } from "./run-after-menu-close";
import { WikiPanel } from "./wiki-panel";
import { WikiRebuildDialog } from "./wiki-rebuild-dialog";

/**
 * Wiki tab content (split-section layout, 2026-09-03 定高分屏): one unified
 * search box above two independently collapsible card sections — the AI
 * entries (WikiPanel, default expanded) and the user's manual cards
 * (ManualCardPanel, default expanded too — 2026-09-04：切进百科 tab 两区都展开).
 * Both expanded → each takes half the column and scrolls INSIDE its own card;
 * collapsing one yields the whole column to the other. So a huge auto-generated
 * entry list can never bury 我的条目 — users see both drawer boundaries (and
 * thus that 我的条目 exists) the moment they open the tab. 未来用户自建条目抽屉
 * 作为「我的条目」内的水平子抽屉生长，顶层恒为这两个容器（故 50/50 定分成立）。
 * The query is owned here and passed down, so one box filters both sections.
 */
export function WikiTab({
  kbId,
  entries,
  entriesLoading = false,
  updating = false,
  updatingEntryIds = [],
  active = false,
  onGenerateWiki,
  onRegenerateEntries,
  onOpenEntry,
  onEditEntry,
  onDeleteEntry,
  onOpenCard,
}: {
  kbId: string;
  entries: WikiEntrySummary[];
  entriesLoading?: boolean;
  updating?: boolean;
  /**
   * 局部更新在飞目标（2026-09-05）：非空时仅这些 entry 行显示「更新中」，
   * 其余 dirty 行保持「待更新」；空 + updating = 整库 run（全部 dirty 更新中）。
   */
  updatingEntryIds?: readonly string[];
  /**
   * 百科 tab 是否激活（2026-09-02）：透传给 ManualCardPanel 作卡片取数门控，
   * 与 entries（useWikiEntries）同节奏——tab 激活即取数，收起态也显示计数。
   */
  active?: boolean;
  /**
   * 百科维护动作（2026-08-30）：更新/重建本是百科功能，此前只在全局库菜单；
   * tab 内 ⋯ 承接同一触发器，与全局双入口。
   */
  onGenerateWiki?: (mode: WikiGenerateMode) => void;
  /** 局部更新/重建（2026-09-02）：透传给 WikiPanel 右键菜单（单条/多选）。 */
  onRegenerateEntries?: (entryIds: string[]) => void;
  onOpenEntry: (entry: WikiEntrySummary) => void;
  onEditEntry?: (entry: WikiEntrySummary) => void;
  onDeleteEntry: (entry: WikiEntrySummary) => Promise<void> | void;
  onOpenCard?: (cardId: string) => void;
}) {
  const { t } = useI18n();
  const tk = t.knowledge;
  const [query, setQuery] = useState("");
  const [rebuildOpen, setRebuildOpen] = useState(false);
  // 新建卡片全局入口（2026-09-02）：⋯ 菜单递增此信号，ManualCardPanel 用
  // render-time 派生状态监听变化并弹出创建框（同 lastQuery 惯用法）。
  const [cardCreateSignal, setCardCreateSignal] = useState(0);
  // 新建抽屉全局入口（2026-09-04）：⋯ 菜单递增此信号，ManualCardPanel 监听后开 DrawerEditor。
  const [drawerCreateSignal, setDrawerCreateSignal] = useState(0);

  return (
    <div className="bg-background flex h-full flex-col" data-testid="wiki-tab">
      <div className="flex shrink-0 items-center gap-2 px-4 py-2">
        <div className="relative flex-1">
          <Search className="text-muted-foreground absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
          <Input
            aria-label={tk.searchWiki}
            className="h-7 pr-7 pl-7 text-xs"
            placeholder={tk.searchWiki}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {query && (
            <button
              aria-label={tk.clearSearch}
              className="text-muted-foreground hover:text-foreground absolute top-1/2 right-1.5 -translate-y-1/2"
              type="button"
              onClick={() => setQuery("")}
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
        {/* 百科操作 ⋯（2026-08-30）：搜索框后承接更新/重建，与全局库菜单双入口；
            触发器 size-7 保 44px 栏高（⋯ 降档陷阱：默认 sm 是 h-8）；
            更新中禁用规则与全局菜单一致。 */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              aria-label={tk.wikiMoreOptions}
              className="size-7 shrink-0"
              size="icon-sm"
              variant="ghost"
            >
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            {/* 维护动作在上、用户自建动作沉底（2026-09-04 用户拍板：新建卡片移到最下面，
                其上方加新建抽屉）。两个新建项都经 runAfterMenuClose 递增信号，由
                ManualCardPanel 的 render-time 派生状态监听消费（新建抽屉→DrawerEditor，
                新建卡片→创建框）；与 wiki 生成无关，不受 updating 影响、始终可用。 */}
            <DropdownMenuItem
              disabled={updating}
              onSelect={() => onGenerateWiki?.("incremental")}
            >
              {updating ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <BookOpen className="size-4" />
              )}
              {updating ? tk.wikiPanel.updating : tk.updateWiki}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={updating}
              onSelect={() => runAfterMenuClose(() => setRebuildOpen(true))}
            >
              <RefreshCw className="size-4" />
              {tk.rebuildWiki}
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() =>
                runAfterMenuClose(() => setDrawerCreateSignal((n) => n + 1))
              }
            >
              <FolderPlus className="size-4" />
              {tk.manualCards.drawers.new}
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() =>
                runAfterMenuClose(() => setCardCreateSignal((n) => n + 1))
              }
            >
              <Plus className="size-4" />
              {tk.manualCards.newCard}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {/* 定高分屏 canvas（2026-09-03）：外层不再滚动（overflow-hidden），两张白卡在
          flex-col 里分摊高度——都展开各占一半、各自卡内 overflow-y-auto 内滚；收起
          一个是顶/底细条，另一个 flex-1 吃满。再长的生成条目也不会把「我的条目」顶
          出视野（用户口径：一进界面就看到两个抽屉的边界、知道有我的条目）。 */}
      <div
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-3"
        data-testid="wiki-split-canvas"
      >
        <WikiPanel
          entries={entries}
          loading={entriesLoading}
          query={query}
          updating={updating}
          updatingEntryIds={updatingEntryIds}
          onDeleteEntry={onDeleteEntry}
          onEditEntry={onEditEntry}
          onGenerateWiki={onGenerateWiki}
          onOpenEntry={onOpenEntry}
          onRebuildWiki={() => setRebuildOpen(true)}
          onRegenerateEntries={onRegenerateEntries}
        />
        <ManualCardPanel
          kbId={kbId}
          active={active}
          query={query}
          createSignal={cardCreateSignal}
          drawerCreateSignal={drawerCreateSignal}
          onOpenCard={onOpenCard}
        />
      </div>
      {/* 重建确认弹窗：与全局库菜单共用同一共享组件 */}
      <WikiRebuildDialog
        open={rebuildOpen}
        onOpenChange={setRebuildOpen}
        onConfirm={() => {
          onGenerateWiki?.("full");
          setRebuildOpen(false);
        }}
      />
    </div>
  );
}
