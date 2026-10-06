"use client";

import { StickyNote } from "lucide-react";
import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useI18n } from "@/core/i18n/hooks";
import { readCardDrawers } from "@/core/knowledge/card-drawers";
import { formatKnowledgeTimestamp } from "@/core/knowledge/format";
import { useManualCard } from "@/core/knowledge/hooks";

import { DrawerGlyph } from "./drawer-icon";

/**
 * Manual knowledge card full-text drawer (Phase-3 P6 fix). The card
 * counterpart of WikiEntryDrawer: recall-test wiki-path hits can be manual
 * cards (spec §8 混排), and clicking one must open THIS drawer with the card
 * id — the wiki entry drawer 404s on card ids (「条目不存在或已删除」).
 * Same overlay rule: opening never switches the middle-column tab.
 * 2026-09-05 阅读卡重设计：sticky 单行头 + bg-card 容器 + 卡下元信息行。
 */
export function ManualCardDrawer({
  kbId,
  cardId,
  open,
  onOpenChange,
}: {
  kbId: string | null;
  cardId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { locale, t } = useI18n();
  const tm = t.knowledge.manualCards;
  const tc = t.knowledge.chat;
  const query = useManualCard(open ? kbId : null, open ? cardId : null);
  const card = query.data;
  const metaLine = card
    ? `${tm.updatedAt} ${formatKnowledgeTimestamp(card.updated_at, locale)}`
    : tm.loading;

  // 图标跟随卡片所属抽屉（2026-09-05）：用户自建抽屉带 icon+color，卡片可在
  // 抽屉间移动——打开时直读 localStorage（面板侧 hook 实例的状态会陈旧）。
  const drawer = useMemo(() => {
    if (!open || !kbId || !card) return undefined;
    const state = readCardDrawers(kbId);
    return state.drawers.find((d) => d.id === state.membership[card.id]);
  }, [open, kbId, card]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-hidden sm:max-w-xl" side="right">
        {/* 百科 Tab 容器同款 overlay 滚动条（2026-09-04，EvalRunDrawer 同款）：整抽屉经
            ScrollArea 滚动。 */}
        <ScrollArea
          className="min-h-0 flex-1"
          scrollHideDelay={2000}
          type="scroll"
        >
          {/* 单行紧凑头（切片抽屉同款配方）：卡片图标 + 标题 + 身份/混搜芯片。 */}
          <SheetHeader className="sticky top-0 z-10 border-b bg-background/95 px-4 py-2.5 backdrop-blur-sm">
            <div className="flex min-w-0 items-center gap-1.5 pr-8">
              {drawer ? (
                <DrawerGlyph color={drawer.color} icon={drawer.icon} />
              ) : (
                <StickyNote className="text-muted-foreground size-4 shrink-0" />
              )}
              <SheetTitle className="truncate">
                {card?.title ?? tm.loading}
              </SheetTitle>
              {card && (
                <Badge className="shrink-0 text-[10px]" variant="secondary">
                  {tc.sourceTypeManual}
                </Badge>
              )}
              {drawer && (
                <Badge className="shrink-0 text-[10px]" variant="outline">
                  {drawer.name}
                </Badge>
              )}
              {card?.include_in_wiki_search && (
                <Badge className="shrink-0 text-[10px]" variant="outline">
                  {tm.includeInSearch}
                </Badge>
              )}
            </div>
            {/* sr-only 描述复述元信息行（不复述标题，避免与 SheetTitle 文本重复）。 */}
            <SheetDescription className="sr-only">{metaLine}</SheetDescription>
          </SheetHeader>
          {/* 空/加载态：absolute inset-0 锚 ScrollArea Root 垂直居中（项目既定配方）。 */}
          {query.isLoading && (
            <p className="text-muted-foreground absolute inset-0 flex items-center justify-center text-xs">
              {tm.loading}
            </p>
          )}
          {!query.isLoading && !card && (
            <p className="text-muted-foreground absolute inset-0 flex items-center justify-center text-sm">
              {tm.drawerNotFound}
            </p>
          )}
          {card && (
            <div className="flex flex-col gap-2 px-4 pt-4 pb-6">
              {/* 阅读卡（切片卡 / 设置-集成 Card 同款配方）：标签行卡顶、border-b 与正文分隔。 */}
              <div className="bg-card text-card-foreground rounded-lg border p-4 shadow-xs">
                {card.tags.length > 0 && (
                  <div className="mb-2 flex flex-wrap gap-1.5 border-b border-border/60 pb-2">
                    {card.tags.map((tag) => (
                      <Badge className="text-[10px]" key={tag} variant="outline">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                )}
                <p className="text-sm leading-6 whitespace-pre-wrap">
                  {card.content}
                </p>
              </div>
              <p className="text-muted-foreground text-xs">{metaLine}</p>
            </div>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
