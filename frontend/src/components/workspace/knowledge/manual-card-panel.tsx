"use client";

import {
  Check,
  ChevronDown,
  ChevronRight,
  FolderInput,
  FolderPlus,
  LayoutList,
  Loader2,
  MoreHorizontal,
  Pencil,
  Plus,
  SearchCheck,
  SearchX,
  StickyNote,
  Trash2,
  X,
} from "lucide-react";
import { Fragment, useMemo, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
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
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import {
  DRAWER_COLORS,
  useCardDrawers,
  type CardDrawer,
} from "@/core/knowledge/card-drawers";
import {
  formatKnowledgeRelativeTime,
  formatKnowledgeTimestamp,
  stripSummaryHeading,
} from "@/core/knowledge/format";
import {
  useCreateManualCard,
  useDeleteManualCard,
  useManualCard,
  useManualCards,
  useUpdateManualCard,
} from "@/core/knowledge/hooks";
import type {
  ManualCardDetail,
  ManualCardSummary,
} from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

import { DrawerEditor } from "./drawer-editor";
import { DrawerGlyph } from "./drawer-icon";
import { toast } from "./kb-toast";
import { runAfterMenuClose } from "./run-after-menu-close";

interface CardPayload {
  title: string;
  content: string;
  tags: string[];
  include_in_wiki_search: boolean;
}

function parseTags(input: string): string[] {
  return input
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

/**
 * Card create/edit dialog (Phase-3 Batch-1 P6). ``initial`` null = create
 * mode. Save is disabled until title + content are non-blank; a failed save
 * keeps the dialog open (the caller toasts and rethrows).
 */
function ManualCardEditor({
  initial,
  open,
  saving,
  onOpenChange,
  onSave,
}: {
  initial: ManualCardDetail | null;
  open: boolean;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (body: CardPayload) => Promise<void>;
}) {
  const { t } = useI18n();
  const tc = t.knowledge.manualCards;
  const [title, setTitle] = useState(initial?.title ?? "");
  const [content, setContent] = useState(initial?.content ?? "");
  const [tagsInput, setTagsInput] = useState((initial?.tags ?? []).join(", "));
  const [include, setInclude] = useState(
    initial?.include_in_wiki_search ?? false,
  );
  const canSave =
    title.trim().length > 0 && content.trim().length > 0 && !saving;

  const handleSubmit = async () => {
    try {
      await onSave({
        title: title.trim(),
        content: content.trim(),
        tags: parseTags(tagsInput),
        include_in_wiki_search: include,
      });
    } catch {
      // Stay open — the caller already surfaced the error toast.
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>
            {initial ? tc.editorEditTitle : tc.editorCreateTitle}
          </DialogTitle>
          <DialogDescription>{tc.editorDescription}</DialogDescription>
        </DialogHeader>
        {/* field-sizing-content 的 textarea 会把内容宽度沿 grid/flex item 链
            向上传递撑宽对话框——链上每层容器 min-w-0 阻断，宽度固定后
            长行自然软换行。 */}
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor="manual-card-title">{tc.titleLabel}</Label>
            <Input
              id="manual-card-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={tc.titlePlaceholder}
            />
          </div>
          <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor="manual-card-content">{tc.contentLabel}</Label>
            <Textarea
              id="manual-card-content"
              className="min-h-32"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={tc.contentPlaceholder}
            />
          </div>
          <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor="manual-card-tags">{tc.tagsLabel}</Label>
            <Input
              id="manual-card-tags"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder={tc.tagsPlaceholder}
            />
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="manual-card-include"
              checked={include}
              onCheckedChange={setInclude}
            />
            <Label htmlFor="manual-card-include">{tc.includeInSearch}</Label>
            <span className="text-muted-foreground text-xs">
              {tc.includeHint}
            </span>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button disabled={!canSave} onClick={() => void handleSubmit()}>
            {saving ? tc.saving : tc.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * One flat drawer entry in the 我的条目 header row (2026-09-04). NOT a boxed
 * tab — entries sit inline separated by `│` dividers (see the strip), so there
 * is no per-drawer container. The active entry is full-opacity + medium weight
 * and its label takes the drawer accent; idle entries dim to ~55% and lift on
 * hover, all at a uniform width (w-28 — 容纳 ≥4 个汉字；标签在 × 边界处硬截断、
 * 不带省略号). A user drawer shows its colored icon, a
 * hover-revealed × (收起/hide → moves to the -> overflow dropdown, NOT deleted)
 * and a right-click menu (新建卡片 into this drawer / edit / delete); the home
 * entry (「我的条目」) is rendered by the caller, not here.
 */
function DrawerTab({
  active,
  accent,
  icon,
  label,
  testId,
  onClick,
  onClose,
  onCreateCard,
  onEdit,
  onDelete,
}: {
  active: boolean;
  accent?: string;
  icon: ReactNode;
  label: string;
  testId: string;
  onClick: () => void;
  onClose?: () => void;
  onCreateCard?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
}) {
  const { t } = useI18n();
  const tc = t.knowledge.manualCards;
  const td = tc.drawers;
  const tab = (
    <div
      className="group/tab flex w-28 shrink-0 items-center rounded-md transition-colors hover:bg-[var(--wiki-card-bg-hover)]"
      data-active={active}
      data-testid={testId}
    >
      <button
        className={cn(
          "flex min-w-0 flex-1 items-center gap-1.5 rounded py-1.5 pr-1 pl-2 text-sm transition-opacity",
          active ? "font-medium opacity-100" : "opacity-55 hover:opacity-90",
        )}
        style={active && accent ? { color: accent } : undefined}
        type="button"
        onClick={onClick}
      >
        {icon}
        <span className="overflow-hidden whitespace-nowrap">{label}</span>
      </button>
      {onClose && (
        <button
          aria-label={td.close}
          className="text-muted-foreground hover:text-foreground mr-1 -ml-1 opacity-0 transition-opacity group-hover/tab:opacity-100 focus-visible:opacity-100"
          data-testid={`${testId}-close`}
          type="button"
          onClick={onClose}
        >
          <X className="size-3" />
        </button>
      )}
    </div>
  );
  if (!onEdit || !onDelete) {
    return tab;
  }
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{tab}</ContextMenuTrigger>
      <ContextMenuContent className="w-40">
        {/* 新建卡片（2026-09-04）：加到本抽屉（onCreateCard 会先切到该抽屉再开创建框）。 */}
        {onCreateCard && (
          <ContextMenuItem
            onSelect={() => runAfterMenuClose(() => onCreateCard())}
          >
            <Plus className="size-4" />
            {tc.newCard}
          </ContextMenuItem>
        )}
        <ContextMenuItem onSelect={onEdit}>
          <Pencil className="size-4" />
          {td.edit}
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem variant="destructive" onSelect={onDelete}>
          <Trash2 className="size-4" />
          {td.delete}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/**
 * Manual knowledge card section of the wiki tab (Phase-3 Batch-1 P6, spec §8;
 * split-section redesign): a collapsible section under the AI entries —
 * default EXPANDED (2026-09-04: 与生成条目一致，切进百科 tab 两区都展开；定高
 * 分屏下各占一半、卡内各自内滚) — sharing the tab's unified search box.
 * Searching force-fetches and force-expands the section (a collapsed section
 * would otherwise never match). Rows carry the document-table
 * interaction model: checkbox multi-select + batch bar + batch delete, and a
 * right-click context menu (open / edit / include-toggle / delete). Cards are
 * fully user-managed (never auto-regenerated, unlike the AI wiki entries);
 * each row keeps its 混入搜索 toggle driving the card's retrieval vector
 * lifecycle server-side.
 */
export function ManualCardPanel({
  kbId,
  active = false,
  query = "",
  createSignal = 0,
  drawerCreateSignal = 0,
  onOpenCard,
}: {
  kbId: string;
  /**
   * 百科 tab 是否激活（2026-09-02）：卡片列表取数门控从「分区展开」上移到「tab 激活」，
   * 与 AI 条目（useWikiEntries）同节奏——tab 一打开即取数，故收起态也能显示计数徽章
   * （此前收起时 total=0、徽章不渲染，与生成条目不一致）。
   */
  active?: boolean;
  /** Unified wiki-tab search text (title/summary/tags containment, client-side). */
  query?: string;
  /**
   * 新建卡片全局入口（2026-09-02）：百科 tab 的 ⋯ 菜单递增此计数触发创建，
   * 让「新建卡片」不必依赖卡片区头部按钮（收起时也可达）。
   */
  createSignal?: number;
  /**
   * 新建抽屉全局入口（2026-09-04）：百科 tab ⋯ 菜单递增此计数触发 DrawerEditor，
   * 与 createSignal 同款 render-time 派生状态监听。
   */
  drawerCreateSignal?: number;
  onOpenCard?: (cardId: string) => void;
}) {
  const { t, locale } = useI18n();
  const tk = t.knowledge;
  const tc = t.knowledge.manualCards;
  const td = tc.drawers;
  const [expanded, setExpanded] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [deleteTargets, setDeleteTargets] = useState<
    ManualCardSummary[] | null
  >(null);
  const [drawerEditor, setDrawerEditor] = useState<{
    open: boolean;
    editing: CardDrawer | null;
  }>({ open: false, editing: null });
  // 水平标签条的当前选中标签（2026-09-04）：null = 常驻「我的条目」首页标签
  // （未分组卡片）；抽屉 id = 只看该抽屉的卡片。
  const [activeTab, setActiveTab] = useState<string | null>(null);
  // -> 全部抽屉下拉的开合（2026-09-04）：未悬停头部时下拉按钮隐藏，菜单打开期间
  // 强制保持可见（菜单渲染在 portal，鼠标移入会脱离头部 group-hover）。
  const [drawerMenuOpen, setDrawerMenuOpen] = useState(false);

  // Filtering clears the selection (same rule as the document table);
  // render-time derived-state reset avoids an effect round-trip.
  const [lastQuery, setLastQuery] = useState(query);
  if (lastQuery !== query) {
    setLastQuery(query);
    setSelectedIds(new Set());
  }

  // 新建卡片全局入口（2026-09-02）：⋯ 菜单递增 createSignal → 同款 render-time
  // 派生状态监听变化，打开创建框并展开卡片区（保存后新卡即时可见）。
  const [lastCreateSignal, setLastCreateSignal] = useState(createSignal);
  if (createSignal !== lastCreateSignal) {
    setLastCreateSignal(createSignal);
    setEditingId(null);
    setEditorOpen(true);
    setExpanded(true);
  }

  // 新建抽屉全局入口（2026-09-04）：⋯ 菜单递增 drawerCreateSignal → 同款监听，
  // 打开 DrawerEditor（新建态）并展开卡片区（新抽屉即时可见于行尾）。
  const [lastDrawerCreateSignal, setLastDrawerCreateSignal] =
    useState(drawerCreateSignal);
  if (drawerCreateSignal !== lastDrawerCreateSignal) {
    setLastDrawerCreateSignal(drawerCreateSignal);
    setDrawerEditor({ open: true, editing: null });
    setExpanded(true);
  }

  const searching = query.trim() !== "";
  // 搜索期间强制展开（收起的区永远搜不到）；取数已由 active 门控，与展开无关。
  const effectiveExpanded = expanded || searching;

  // 取数门控 = tab 激活（非分区展开）：与 AI 条目同节奏，收起态也有 total 供计数徽章。
  // 列表「渲染」仍由 effectiveExpanded 门控（下方 JSX）——取数与渲染解耦。
  const cardsQuery = useManualCards(kbId, active);
  const cards = useMemo(() => cardsQuery.data?.items ?? [], [cardsQuery.data]);
  const total = cardsQuery.data?.total ?? 0;

  const visibleCards = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) {
      return cards;
    }
    return cards.filter(
      (card) =>
        card.title.toLowerCase().includes(needle) ||
        card.summary.toLowerCase().includes(needle) ||
        card.tags.some((tag) => tag.toLowerCase().includes(needle)),
    );
  }, [cards, query]);

  const editingCardQuery = useManualCard(kbId, editingId);
  const editingCard =
    editingId !== null ? (editingCardQuery.data ?? null) : null;

  const createCard = useCreateManualCard(kbId);
  const updateCard = useUpdateManualCard(kbId);
  const deleteCard = useDeleteManualCard(kbId);

  // User-defined drawers (2026-09-04): a localStorage partition of the cards
  // inside 我的条目. membership is card->drawerId; unfiled cards (no or stale
  // mapping) lead, then each drawer in order. Deleting a drawer only drops its
  // membership — the cards themselves are never touched.
  const {
    drawers,
    membership,
    createDrawer,
    updateDrawer,
    deleteDrawer,
    setDrawerHidden,
    revealDrawerToFront,
    moveCard,
    moveCards,
  } = useCardDrawers(kbId);

  // 当前标签的卡片（2026-09-04，水平浏览器标签模型）：抽屉 id 失效（被删/切库）
  // 时回落到首页标签。首页 = 未分组（无归属或归属指向已不存在的抽屉）；抽屉标签
  // = 归属等于该抽屉的卡片。分区语义：每卡只出现在一个标签下。
  const drawerIds = useMemo(
    () => new Set(drawers.map((drawer) => drawer.id)),
    [drawers],
  );
  const activeDrawerId =
    activeTab !== null && drawerIds.has(activeTab) ? activeTab : null;
  const activeCards = useMemo(
    () =>
      visibleCards.filter((card) => {
        const owner = membership[card.id];
        return activeDrawerId === null
          ? owner === undefined || !drawerIds.has(owner)
          : owner === activeDrawerId;
      }),
    [visibleCards, membership, activeDrawerId, drawerIds],
  );
  // 标签行只显示未收起的抽屉（2026-09-04）；收起的进右侧 -> 下拉，可从那里恢复。
  const visibleDrawers = useMemo(
    () => drawers.filter((drawer) => !drawer.hidden),
    [drawers],
  );

  // Selection (checkbox model, same as the document table).
  const visibleIds = activeCards.map((card) => card.id);
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
  const toggleSelect = (cardId: string, checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(cardId);
      } else {
        next.delete(cardId);
      }
      return next;
    });
  };
  const handleRowContextMenu = (cardId: string) => {
    if (!selectedIds.has(cardId)) {
      setSelectedIds(new Set([cardId]));
    }
  };
  const selectedCards = () => cards.filter((card) => selectedIds.has(card.id));
  const selectedCardIds = selectedCards().map((card) => card.id);
  // 多选批量移动（req3, 2026-09-04）：目标是否已含全部选中卡片（是则禁用该目标，
  // 避免空操作）；null=未分组（无归属或归属指向已删抽屉）。
  const allSelectedIn = (drawerId: string | null) =>
    selectedCardIds.length > 0 &&
    selectedCardIds.every((id) => {
      const owner = membership[id];
      return drawerId === null
        ? owner === undefined || !drawerIds.has(owner)
        : owner === drawerId;
    });

  const openEdit = (card: ManualCardSummary) => {
    setEditingId(card.id);
    setEditorOpen(true);
  };

  const handleSave = async (body: CardPayload) => {
    try {
      if (editingId !== null) {
        await updateCard.mutateAsync({ cardId: editingId, body });
        toast.success(tc.updateSuccess);
      } else {
        const created = await createCard.mutateAsync(body);
        // 新卡归入「当前展示的条目」（2026-09-04）：首页=未分组不动；抽屉=移入该抽屉。
        // 创建框是模态的，activeDrawerId 在其期间稳定，故保存时读它即触发时的目标条目。
        if (activeDrawerId !== null) {
          moveCard(created.id, activeDrawerId);
        }
        toast.success(tc.createSuccess);
      }
    } catch (error) {
      toast.error(
        error instanceof Error && error.message ? error.message : tc.saveFailed,
      );
      throw error; // Keep the dialog open on failure.
    }
    setEditorOpen(false);
    setEditingId(null);
  };

  const handleToggle = async (card: ManualCardSummary, next: boolean) => {
    try {
      await updateCard.mutateAsync({
        cardId: card.id,
        body: { include_in_wiki_search: next },
      });
    } catch (error) {
      toast.error(
        error instanceof Error && error.message ? error.message : tc.saveFailed,
      );
    }
  };

  const confirmDeleteTargets = async () => {
    if (!deleteTargets) {
      return;
    }
    const removed = new Set(deleteTargets.map((card) => card.id));
    const results = await Promise.allSettled(
      deleteTargets.map((card) => deleteCard.mutateAsync(card.id)),
    );
    if (results.some((result) => result.status === "rejected")) {
      toast.error(tc.deleteFailed);
    } else {
      toast.success(tc.deleteSuccess);
    }
    setSelectedIds(
      (current) => new Set([...current].filter((id) => !removed.has(id))),
    );
    setDeleteTargets(null);
  };

  // Delete a drawer: drop it + its membership (its cards fall back to the
  // 我的条目 home tab). If it was the active tab, return to home. Non-destructive
  // to the cards themselves — no confirm dialog.
  const handleDeleteDrawer = (drawerId: string) => {
    deleteDrawer(drawerId);
    setActiveTab((current) => (current === drawerId ? null : current));
  };

  // 收起抽屉（2026-09-04）：× 只翻 hidden（不删数据/归属），收进右侧 -> 下拉；
  // 若收起的是当前标签，回首页。恢复=下拉里点它（setDrawerHidden(false)+跳转）。
  const handleCloseDrawer = (drawerId: string) => {
    setDrawerHidden(drawerId, true);
    setActiveTab((current) => (current === drawerId ? null : current));
  };

  // 从某条目右键「新建卡片」（2026-09-04）：先切到该条目（首页=null / 抽屉=id）
  // 再开创建框；保存后 handleSave 按 activeDrawerId 把新卡归入该条目。
  const openCreateFor = (drawerId: string | null) => {
    setActiveTab(drawerId);
    setEditingId(null);
    setEditorOpen(true);
    setExpanded(true);
  };

  return (
    <section
      className={cn(
        "bg-card dark:bg-muted flex flex-col overflow-hidden rounded-md border shadow-[0_1px_3px_rgba(26,24,20,0.06)] dark:shadow-[0_2px_6px_rgba(0,0,0,0.35)]",
        // 定高分屏（2026-09-03）：同生成条目——展开=flex-1 吃一份额定高度、收起=shrink-0
        // 细条。不再 mt-auto 钉底：生成条目收起后本区要跟随上移（2026-09-04），而生成
        // 条目展开(flex-1)时本就把本区推到底部，mt-auto 冗余且正是「不上移」的根因。
        effectiveExpanded ? "min-h-0 flex-1" : "shrink-0",
      )}
      data-testid="manual-cards-section"
    >
      {/* Section header: collapse toggle + count badge + select-all pinned to
          the right edge (aligned with the AI entries section header above).
          计数徽章取 total（tab 激活即有），收起态也显示，与生成条目一致。
          整行不再 hover 全亮（2026-09-04）：本区头部有多个条目（我的条目 + 用户
          抽屉），改为每个条目各自 hover 亮起（见标题按钮与 DrawerTab）。 */}
      <div className="group/header flex shrink-0 items-center gap-1 bg-[var(--wiki-card-bg)] pr-3 pl-1.5">
        {/* 箭头 = 唯一的展开/收起控制（2026-09-04）：因为「我的条目」下有多个
            抽屉条目要来回切换，标题本身改为「切回首页」，收起交给这个箭头。 */}
        <button
          aria-expanded={effectiveExpanded}
          aria-label={tc.sectionTitle}
          className="text-muted-foreground hover:text-foreground flex shrink-0 items-center rounded-md py-2 pr-1 pl-4 transition-colors"
          data-testid="manual-cards-collapse"
          type="button"
          onClick={() => setExpanded((value) => !value)}
        >
          {effectiveExpanded ? (
            <ChevronDown className="size-4" />
          ) : (
            <ChevronRight className="size-4" />
          )}
        </button>
        {/* 「我的条目」= 首页/未分组条目：点击切回首页（不收起）；收起态点击则展开。
            图标/标题/计数与「生成条目」逐项一致（size-4 + text-sm + ml-1 计数胶囊）。
            选中某抽屉时本项略淡，提示可点回首页。hover 本项亮起；右键=在首页新建卡片。 */}
        <ContextMenu>
          <ContextMenuTrigger asChild>
            <button
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-md py-2 pr-2 text-left transition-[opacity,background-color] hover:bg-[var(--wiki-card-bg-hover)]",
                effectiveExpanded &&
                  activeDrawerId !== null &&
                  "opacity-55 hover:opacity-90",
              )}
              data-active={activeDrawerId === null}
              data-testid="manual-cards-toggle"
              type="button"
              onClick={() => {
                setActiveTab(null);
                if (!effectiveExpanded) setExpanded(true);
              }}
            >
              <StickyNote className="size-4 shrink-0 text-[var(--wiki-card)]" />
              <span className="text-sm font-medium">{tc.sectionTitle}</span>
              {total > 0 && (
                <span className="bg-card ml-1 inline-flex h-5 items-center rounded-full border border-[var(--wiki-card-ring)] px-1.5 text-xs text-[var(--wiki-card)] tabular-nums">
                  {total}
                </span>
              )}
            </button>
          </ContextMenuTrigger>
          <ContextMenuContent className="w-40">
            <ContextMenuItem
              onSelect={() => runAfterMenuClose(() => openCreateFor(null))}
            >
              <Plus className="size-4" />
              {tc.newCard}
            </ContextMenuItem>
          </ContextMenuContent>
        </ContextMenu>
        {/* 计数后面跟着用户自建抽屉（2026-09-04）：项间竖线 │ 分隔；只显示未收起的抽屉。
            strip 内容宽（不 flex-1）+ min-w-0 + overflow-hidden：标签溢出时收缩裁切、行内
            不横滚，收起/超出的从右侧下拉访问。× = 收起（进下拉可恢复），删除走右键。点抽
            屉签过滤，再点当前签回首页。右侧控件改由后面的 flex-1 垫片顶到栏最右（见下）。 */}
        {effectiveExpanded && (
          <div
            className="flex min-w-0 items-center overflow-hidden"
            data-testid="drawer-tab-strip"
          >
            {visibleDrawers.map((drawer) => (
              <Fragment key={drawer.id}>
                <span
                  aria-hidden="true"
                  className="bg-muted-foreground/40 mx-1 h-4 w-0.5 shrink-0"
                />
                <DrawerTab
                  accent={DRAWER_COLORS[drawer.color].accent}
                  active={activeDrawerId === drawer.id}
                  icon={
                    <DrawerGlyph
                      className="size-4 shrink-0"
                      color={drawer.color}
                      icon={drawer.icon}
                    />
                  }
                  label={drawer.name}
                  testId={`drawer-tab-${drawer.id}`}
                  onClick={() =>
                    setActiveTab((current) =>
                      current === drawer.id ? null : drawer.id,
                    )
                  }
                  onClose={() => handleCloseDrawer(drawer.id)}
                  onCreateCard={() => openCreateFor(drawer.id)}
                  onDelete={() => handleDeleteDrawer(drawer.id)}
                  onEdit={() =>
                    setDrawerEditor({ open: true, editing: drawer })
                  }
                />
              </Fragment>
            ))}
          </div>
        )}
        {/* 行尾 [+] 新建抽屉（req1）：shrink-0，空间够时紧跟最后一个标签；标签溢出、strip
            收缩裁切时它不被裁，正好贴在右侧控件左边（永远可达）。图标用 Plus（不是 FolderPlus）：
            紧跟标签的行尾 + 沿用浏览器「新建标签页」的通用认知，比文件夹图标更直观；带文字的
            菜单项（垫片右键/下拉/移动到抽屉▸/WikiTab ⋯）才用 FolderPlus 表意。 */}
        {effectiveExpanded && (
          <button
            aria-label={td.new}
            className="text-muted-foreground hover:text-foreground flex size-6 shrink-0 items-center justify-center rounded transition-colors hover:bg-[var(--wiki-card-bg-hover)]"
            data-testid="manual-cards-drawer-add"
            type="button"
            onClick={() => setDrawerEditor({ open: true, editing: null })}
          >
            <Plus className="size-4" />
          </button>
        )}
        {/* 抽屉行空白垫片（req1+req3）：flex-1 吃掉多余横向空间，把右侧控件顶到栏最右并随
            栏宽跟随（取代上一轮 strip 的 flex-1）；标签溢出时 basis:0 收缩为 0，[+] 便贴到
            控件左侧。self-stretch 撑满栏高才有可右键面积；右键 = 新建抽屉（空白区在抽屉导
            航行，语义最贴切）。它是独立元素（不含标签），与标签各自的右键菜单不冲突。 */}
        {effectiveExpanded && (
          <ContextMenu>
            <ContextMenuTrigger asChild>
              <div
                className="min-w-0 flex-1 self-stretch"
                data-testid="drawer-strip-spacer"
              />
            </ContextMenuTrigger>
            <ContextMenuContent className="w-40">
              <ContextMenuItem
                onSelect={() =>
                  runAfterMenuClose(() =>
                    setDrawerEditor({ open: true, editing: null }),
                  )
                }
              >
                <FolderPlus className="size-4" />
                {td.new}
              </ContextMenuItem>
            </ContextMenuContent>
          </ContextMenu>
        )}
        {/* 右侧固定保留区（2026-09-04）：全部抽屉下拉（LayoutList 图标，未悬停头部时
            隐藏、只留占位；收起的从这里找回，点击即取消收起+移到最前+跳转；底部新建
            抽屉）+ 全选框（本区有任意卡片即稳定显示，选中当前显示条目里的全部卡片）。 */}
        {effectiveExpanded && (
          <div className="flex shrink-0 items-center gap-1 pl-1">
            <DropdownMenu
              open={drawerMenuOpen}
              onOpenChange={setDrawerMenuOpen}
            >
              <DropdownMenuTrigger asChild>
                <button
                  aria-label={td.allDrawers}
                  className={cn(
                    "text-muted-foreground hover:text-foreground flex size-6 items-center justify-center rounded transition-all hover:bg-[var(--wiki-card-bg-hover)]",
                    // 未悬停头部时隐藏（opacity-0 保留占位不引起布局跳动）；菜单打开
                    // 期间强制可见，避免鼠标移入 portal 菜单脱离 group-hover 后按钮消失。
                    drawerMenuOpen
                      ? "opacity-100"
                      : "pointer-events-none opacity-0 group-hover/header:pointer-events-auto group-hover/header:opacity-100",
                  )}
                  data-testid="manual-cards-drawer-overflow"
                  type="button"
                >
                  <LayoutList className="size-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                {drawers.map((drawer) => (
                  <DropdownMenuItem
                    key={drawer.id}
                    onSelect={() => {
                      // 取消收起并移到最前（紧跟「我的条目」），再选中该抽屉。
                      revealDrawerToFront(drawer.id);
                      setActiveTab(drawer.id);
                    }}
                  >
                    <DrawerGlyph color={drawer.color} icon={drawer.icon} />
                    <span className="truncate">{drawer.name}</span>
                    {activeDrawerId === drawer.id && (
                      <Check className="ml-auto size-4" />
                    )}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={() =>
                    runAfterMenuClose(() =>
                      setDrawerEditor({ open: true, editing: null }),
                    )
                  }
                >
                  <FolderPlus className="size-4" />
                  {td.new}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            {cards.length > 0 && (
              <Checkbox
                aria-label={tk.selectAllDocuments}
                checked={headerChecked}
                onCheckedChange={toggleSelectAll}
              />
            )}
          </div>
        )}
      </div>

      {effectiveExpanded && (
        <ContextMenu>
          <ContextMenuTrigger asChild>
            <div
              className="flex min-h-0 flex-1 flex-col"
              data-testid="manual-cards-content"
            >
              {/* 批量栏退役（2026-09-02）：插入式条推挤内容产生抖动；
              删除所选/取消选择全部由右键菜单承接 */}

              {cardsQuery.isLoading ? (
                <div className="text-muted-foreground flex flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
                  <Loader2 className="size-8 animate-spin" />
                  <p className="text-sm">{tc.loading}</p>
                </div>
              ) : activeCards.length === 0 ? (
                // 空态居中 + 放大图标（2026-09-04）：flex-1 撑满剩余高度、内容垂直水平居中；
                // StickyNote 放大淡化置于说明文字上方（对应本区图标，与生成条目 BookOpen 对称）。
                <div className="text-muted-foreground flex flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
                  <StickyNote className="size-8 opacity-40" />
                  <p className="text-sm">
                    {cards.length > 0 && searching ? tc.noMatches : tc.empty}
                  </p>
                </div>
              ) : (
                <ScrollArea
                  className="min-h-0 flex-1"
                  scrollHideDelay={2000}
                  type="scroll"
                >
                  <ul
                    className="flex flex-col px-2 pb-2"
                    data-testid="manual-card-list"
                  >
                    {activeCards.map((card) => {
                      const isSelected = selectedIds.has(card.id);
                      const currentDrawerId = membership[card.id];
                      // 行图标跟随所属抽屉（2026-09-05，与详情抽屉头部同源）：
                      // 用户自建抽屉带 icon+color；未归档/归属已删回退 StickyNote。
                      const ownerDrawer = drawers.find(
                        (d) => d.id === currentDrawerId,
                      );
                      // 剥掉摘要开头的「# 标题」markdown 行（2026-09-03）
                      const summaryText = stripSummaryHeading(card.summary);
                      return (
                        <li key={card.id}>
                          <ContextMenu>
                            <ContextMenuTrigger asChild>
                              <div
                                className={cn(
                                  "group hover:bg-muted/50 flex h-10 items-center gap-2 rounded-md px-2",
                                  isSelected && "bg-muted/60",
                                )}
                                data-selected={isSelected}
                                onContextMenu={(event) => {
                                  // 阻止冒泡到内容区外层「新建卡片」右键菜单（req2）：
                                  // 卡片行只开自己的行级菜单。
                                  event.stopPropagation();
                                  handleRowContextMenu(card.id);
                                }}
                              >
                                <Checkbox
                                  aria-label={`${tc.selectCard}: ${card.title}`}
                                  checked={isSelected}
                                  className={cn(
                                    "shrink-0 opacity-0 transition-opacity group-hover:opacity-100 data-[state=checked]:opacity-100",
                                    selectedIds.size > 0 && "opacity-100",
                                  )}
                                  onCheckedChange={(checked) =>
                                    toggleSelect(card.id, checked === true)
                                  }
                                />
                                {/* 单行内联（2026-09-03）：图标 + 标题(hug,≤45%) + 摘要(fill,truncate,剥H1行+淡化 /70) 连读；
                              混入搜索徽章/时间/⋯ 靠右；tags 移入详情抽屉不再占行。 */}
                                <button
                                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                                  data-testid={`manual-card-row-${card.id}`}
                                  type="button"
                                  onClick={() => onOpenCard?.(card.id)}
                                >
                                  {ownerDrawer ? (
                                    <DrawerGlyph
                                      color={ownerDrawer.color}
                                      icon={ownerDrawer.icon}
                                    />
                                  ) : (
                                    <StickyNote className="text-muted-foreground size-4 shrink-0" />
                                  )}
                                  <span className="max-w-[45%] shrink-0 truncate text-sm font-medium">
                                    {card.title}
                                  </span>
                                  <span className="text-muted-foreground/70 min-w-0 flex-1 truncate text-xs">
                                    {summaryText}
                                  </span>
                                </button>
                                {card.include_in_wiki_search && (
                                  <Badge
                                    className="h-5 shrink-0 py-0"
                                    variant="secondary"
                                  >
                                    {tc.includeInSearch}
                                  </Badge>
                                )}
                                <Tooltip
                                  content={`${tc.updatedAt} ${formatKnowledgeTimestamp(card.updated_at, locale)}`}
                                >
                                  <span className="text-muted-foreground w-[72px] shrink-0 truncate text-right text-xs tabular-nums">
                                    {formatKnowledgeRelativeTime(
                                      card.updated_at,
                                      locale,
                                    )}
                                  </span>
                                </Tooltip>
                                {/* 行尾 ⋯（2026-09-03）：镜像右键行级子集（含混入搜索开关），取代
                              hover 浮现的 Switch/编辑/删除；opacity 门控淡入、打开时常驻。 */}
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
                                              onOpenCard?.(card.id),
                                            )
                                          }
                                        >
                                          <StickyNote className="size-4" />
                                          {tc.openCard}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem
                                          onSelect={() =>
                                            runAfterMenuClose(() =>
                                              openEdit(card),
                                            )
                                          }
                                        >
                                          <Pencil className="size-4" />
                                          {tc.editCard}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem
                                          onSelect={() =>
                                            void handleToggle(
                                              card,
                                              !card.include_in_wiki_search,
                                            )
                                          }
                                        >
                                          {card.include_in_wiki_search ? (
                                            <SearchX className="size-4" />
                                          ) : (
                                            <SearchCheck className="size-4" />
                                          )}
                                          {card.include_in_wiki_search
                                            ? tc.includeOff
                                            : tc.includeOn}
                                        </DropdownMenuItem>
                                        <DropdownMenuSub>
                                          <DropdownMenuSubTrigger>
                                            <FolderInput className="size-4" />
                                            {td.moveTo}
                                          </DropdownMenuSubTrigger>
                                          <DropdownMenuSubContent>
                                            <DropdownMenuItem
                                              disabled={
                                                currentDrawerId === undefined
                                              }
                                              onSelect={() =>
                                                moveCard(card.id, null)
                                              }
                                            >
                                              <span className="flex size-4 items-center justify-center">
                                                {currentDrawerId ===
                                                  undefined && (
                                                  <Check className="size-4" />
                                                )}
                                              </span>
                                              {td.unfiled}
                                            </DropdownMenuItem>
                                            {drawers.map((drawer) => (
                                              <DropdownMenuItem
                                                key={drawer.id}
                                                disabled={
                                                  currentDrawerId === drawer.id
                                                }
                                                onSelect={() =>
                                                  moveCard(card.id, drawer.id)
                                                }
                                              >
                                                <span className="flex size-4 items-center justify-center">
                                                  {currentDrawerId ===
                                                    drawer.id && (
                                                    <Check className="size-4" />
                                                  )}
                                                </span>
                                                <DrawerGlyph
                                                  color={drawer.color}
                                                  icon={drawer.icon}
                                                />
                                                <span className="truncate">
                                                  {drawer.name}
                                                </span>
                                              </DropdownMenuItem>
                                            ))}
                                            <DropdownMenuSeparator />
                                            <DropdownMenuItem
                                              onSelect={() =>
                                                runAfterMenuClose(() =>
                                                  setDrawerEditor({
                                                    open: true,
                                                    editing: null,
                                                  }),
                                                )
                                              }
                                            >
                                              <FolderPlus className="size-4" />
                                              {td.newFromMenu}
                                            </DropdownMenuItem>
                                          </DropdownMenuSubContent>
                                        </DropdownMenuSub>
                                        <DropdownMenuSeparator />
                                        <DropdownMenuItem
                                          variant="destructive"
                                          onSelect={() =>
                                            runAfterMenuClose(() =>
                                              setDeleteTargets([card]),
                                            )
                                          }
                                        >
                                          <Trash2 className="size-4" />
                                          {tc.deleteCard}
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
                                  {/* 结构节奏同文档右键菜单（2026-09-02 定稿）：普通动作
                                （批量移动到抽屉）→ 取消选择（X）→ 分隔线 → 危险操作沉底隔离 */}
                                  <ContextMenuSub>
                                    <ContextMenuSubTrigger>
                                      <FolderInput className="size-4" />
                                      {td.moveTo}
                                    </ContextMenuSubTrigger>
                                    <ContextMenuSubContent>
                                      <ContextMenuItem
                                        disabled={allSelectedIn(null)}
                                        onSelect={() =>
                                          moveCards(selectedCardIds, null)
                                        }
                                      >
                                        <span className="flex size-4 items-center justify-center">
                                          {allSelectedIn(null) && (
                                            <Check className="size-4" />
                                          )}
                                        </span>
                                        {td.unfiled}
                                      </ContextMenuItem>
                                      {drawers.map((drawer) => (
                                        <ContextMenuItem
                                          key={drawer.id}
                                          disabled={allSelectedIn(drawer.id)}
                                          onSelect={() =>
                                            moveCards(
                                              selectedCardIds,
                                              drawer.id,
                                            )
                                          }
                                        >
                                          <span className="flex size-4 items-center justify-center">
                                            {allSelectedIn(drawer.id) && (
                                              <Check className="size-4" />
                                            )}
                                          </span>
                                          <DrawerGlyph
                                            color={drawer.color}
                                            icon={drawer.icon}
                                          />
                                          <span className="truncate">
                                            {drawer.name}
                                          </span>
                                        </ContextMenuItem>
                                      ))}
                                      <ContextMenuSeparator />
                                      <ContextMenuItem
                                        onSelect={() =>
                                          runAfterMenuClose(() =>
                                            setDrawerEditor({
                                              open: true,
                                              editing: null,
                                            }),
                                          )
                                        }
                                      >
                                        <FolderPlus className="size-4" />
                                        {td.newFromMenu}
                                      </ContextMenuItem>
                                    </ContextMenuSubContent>
                                  </ContextMenuSub>
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
                                        setDeleteTargets(selectedCards()),
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
                                      runAfterMenuClose(() =>
                                        onOpenCard?.(card.id),
                                      )
                                    }
                                  >
                                    <StickyNote className="size-4" />
                                    {tc.openCard}
                                  </ContextMenuItem>
                                  <ContextMenuItem
                                    onSelect={() =>
                                      runAfterMenuClose(() => openEdit(card))
                                    }
                                  >
                                    <Pencil className="size-4" />
                                    {tc.editCard}
                                  </ContextMenuItem>
                                  <ContextMenuItem
                                    onSelect={() =>
                                      void handleToggle(
                                        card,
                                        !card.include_in_wiki_search,
                                      )
                                    }
                                  >
                                    {card.include_in_wiki_search ? (
                                      <SearchX className="size-4" />
                                    ) : (
                                      <SearchCheck className="size-4" />
                                    )}
                                    {card.include_in_wiki_search
                                      ? tc.includeOff
                                      : tc.includeOn}
                                  </ContextMenuItem>
                                  <ContextMenuSub>
                                    <ContextMenuSubTrigger>
                                      <FolderInput className="size-4" />
                                      {td.moveTo}
                                    </ContextMenuSubTrigger>
                                    <ContextMenuSubContent>
                                      <ContextMenuItem
                                        disabled={currentDrawerId === undefined}
                                        onSelect={() => moveCard(card.id, null)}
                                      >
                                        <span className="flex size-4 items-center justify-center">
                                          {currentDrawerId === undefined && (
                                            <Check className="size-4" />
                                          )}
                                        </span>
                                        {td.unfiled}
                                      </ContextMenuItem>
                                      {drawers.map((drawer) => (
                                        <ContextMenuItem
                                          key={drawer.id}
                                          disabled={
                                            currentDrawerId === drawer.id
                                          }
                                          onSelect={() =>
                                            moveCard(card.id, drawer.id)
                                          }
                                        >
                                          <span className="flex size-4 items-center justify-center">
                                            {currentDrawerId === drawer.id && (
                                              <Check className="size-4" />
                                            )}
                                          </span>
                                          <DrawerGlyph
                                            color={drawer.color}
                                            icon={drawer.icon}
                                          />
                                          <span className="truncate">
                                            {drawer.name}
                                          </span>
                                        </ContextMenuItem>
                                      ))}
                                      <ContextMenuSeparator />
                                      <ContextMenuItem
                                        onSelect={() =>
                                          runAfterMenuClose(() =>
                                            setDrawerEditor({
                                              open: true,
                                              editing: null,
                                            }),
                                          )
                                        }
                                      >
                                        <FolderPlus className="size-4" />
                                        {td.newFromMenu}
                                      </ContextMenuItem>
                                    </ContextMenuSubContent>
                                  </ContextMenuSub>
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
                                        setDeleteTargets([card]),
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
            </div>
          </ContextMenuTrigger>
          <ContextMenuContent className="w-40">
            <ContextMenuItem
              onSelect={() =>
                runAfterMenuClose(() => openCreateFor(activeDrawerId))
              }
            >
              <Plus className="size-4" />
              {tc.newCard}
            </ContextMenuItem>
          </ContextMenuContent>
        </ContextMenu>
      )}

      {/* Create opens immediately; edit waits for the detail fetch. */}
      {editorOpen && (editingId === null || editingCard !== null) && (
        <ManualCardEditor
          key={editingId ?? "create"}
          initial={editingCard}
          open={editorOpen}
          saving={createCard.isPending || updateCard.isPending}
          onOpenChange={(open) => {
            setEditorOpen(open);
            if (!open) {
              setEditingId(null);
            }
          }}
          onSave={handleSave}
        />
      )}

      {/* User-defined drawer create/edit (2026-09-04): sparse Qoder-style
          dialog; `editing` non-null pre-fills for edit. The `key` remounts on
          target switch so the form re-seeds from `initial`. Deleting a drawer
          is inline (the label ×) and non-destructive — no confirm dialog. */}
      <DrawerEditor
        key={
          drawerEditor.editing
            ? `drawer-${drawerEditor.editing.id}`
            : "drawer-new"
        }
        initial={drawerEditor.editing}
        open={drawerEditor.open}
        onOpenChange={(open) => setDrawerEditor((prev) => ({ ...prev, open }))}
        onSubmit={(name, icon, color) => {
          if (drawerEditor.editing) {
            updateDrawer(drawerEditor.editing.id, { name, icon, color });
          } else {
            createDrawer({ name, icon, color });
          }
          setDrawerEditor({ open: false, editing: null });
        }}
      />

      {/* Delete confirm — the copy states irreversibility (卡片与向量一并删除);
          the title carries the count in the batch case. */}
      <Dialog
        open={deleteTargets !== null}
        onOpenChange={(open) => !open && setDeleteTargets(null)}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>
              {deleteTargets && deleteTargets.length > 1
                ? tc.deleteBatchTitle(deleteTargets.length)
                : tc.deleteConfirmTitle}
            </DialogTitle>
            <DialogDescription>{tc.deleteConfirmDescription}</DialogDescription>
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
