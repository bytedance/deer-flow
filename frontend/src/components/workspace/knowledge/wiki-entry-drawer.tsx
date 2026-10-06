"use client";

import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronDown, ExternalLink } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ChunkCard } from "@/components/workspace/knowledge/chunk-card";
import { MarkdownContent } from "@/components/workspace/messages/markdown-content";
import { useI18n } from "@/core/i18n/hooks";
import { listChunksByIds } from "@/core/knowledge/api";
import { formatKnowledgeTimestamp } from "@/core/knowledge/format";
import { useWikiEntry } from "@/core/knowledge/hooks";
import { cn } from "@/lib/utils";

/**
 * 展示层去重（2026-09-05 阅读卡重设计）：条目 markdown 首行常为与标题同名的
 * `# H1`，头部已渲染标题，剥掉首行避免「标题出现两次」。仅作用于抽屉渲染，
 * 不改动存储内容。
 */
function stripTitleHeading(content: string, title: string): string {
  const match = /^#\s+(.+)\r?\n/.exec(content);
  if (match && match[1]?.trim() === title.trim()) return content.slice(match[0].length);
  return content;
}

/**
 * Wiki entry full-text drawer (phase-2 batch-1). This is the *overlay* for
 * citation clicks: opening it never switches the middle-column tab, so the
 * reading context survives (验证性动作). The explicit 在百科 tab 中查看
 * button is the only path that navigates into the management view
 * (导航性动作) — 2026-09-05 起置顶在头部，长条目滚动中随时可点。
 */
export function WikiEntryDrawer({
  kbId,
  entryId,
  open,
  onOpenChange,
  onRevealInTab,
}: {
  kbId: string | null;
  entryId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRevealInTab?: (entryId: string) => void;
}) {
  const { locale, t } = useI18n();
  const tw = t.knowledge.wikiDrawer;
  const tk = t.knowledge.wikiPanel;
  const query = useWikiEntry(open ? kbId : null, open ? entryId : null);
  const entry = query.data;
  const metaLine = entry
    ? `${entry.source_chunk_ids.length} ${tw.sourceChunks} · ${tk.updatedAt} ${formatKnowledgeTimestamp(entry.updated_at, locale)}`
    : tw.loading;

  // 血缘展开（2026-09-05）：source_chunk_ids → 只读 ChunkCard 列表，展开时才拉。
  const [lineageOpen, setLineageOpen] = useState(false);
  const sourceIds = entry?.source_chunk_ids ?? [];
  const lineageQuery = useQuery({
    queryKey: ["knowledge", "wiki-entry-lineage", kbId, entryId],
    queryFn: () => listChunksByIds(kbId ?? "", sourceIds),
    enabled: lineageOpen && Boolean(kbId) && sourceIds.length > 0,
  });

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
          {/* 单行紧凑头（2026-09-05，切片抽屉同款配方）：百科图标 + 标题 + dirty 芯片；
              导航动作升为头部 outline 按钮。 */}
          <SheetHeader className="sticky top-0 z-10 border-b bg-background/95 px-4 py-2.5 backdrop-blur-sm">
            <div className="flex items-center justify-between gap-2 pr-8">
              <div className="flex min-w-0 items-center gap-1.5">
                <BookOpen className="text-muted-foreground size-4 shrink-0" />
                <SheetTitle className="truncate">
                  {entry?.title ?? tw.loading}
                </SheetTitle>
                {entry?.status === "dirty" && (
                  <Badge className="shrink-0 text-[10px]" variant="outline">
                    {tk.dirty}
                  </Badge>
                )}
              </div>
              {entry && onRevealInTab && (
                <Button
                  className="shrink-0"
                  onClick={() => onRevealInTab(entry.id)}
                  size="sm"
                  variant="outline"
                >
                  <ExternalLink className="mr-1 size-3.5" />
                  {tw.openInTab}
                </Button>
              )}
            </div>
            {/* sr-only 描述复述元信息行（不复述标题，避免与 SheetTitle 文本重复）。 */}
            <SheetDescription className="sr-only">{metaLine}</SheetDescription>
          </SheetHeader>
          {/* 空/加载态：absolute inset-0 锚 ScrollArea Root 垂直居中（项目既定配方）。 */}
          {query.isLoading && (
            <p className="text-muted-foreground absolute inset-0 flex items-center justify-center text-xs">
              {tw.loading}
            </p>
          )}
          {!query.isLoading && !entry && (
            <p className="text-muted-foreground absolute inset-0 flex items-center justify-center text-sm">
              {tw.notFound}
            </p>
          )}
          {entry && (
            <div className="flex flex-col gap-2 px-4 pt-4 pb-6">
              {/* 阅读卡（切片卡 / 设置-集成 Card 同款配方）：bg-card + border + shadow-xs，
                  正文不再裸铺窗底；卡内 markdown 标题降档避免巨型 h1。 */}
              <div className="bg-card text-card-foreground rounded-lg border p-4 shadow-xs">
                <MarkdownContent
                  className="text-sm [&_blockquote]:my-1.5 [&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-semibold [&_h4]:text-sm [&_h4]:font-medium [&_li]:my-0.5 [&_ol]:my-1.5 [&_p]:my-1.5 [&_pre]:my-2 [&_ul]:my-1.5"
                  content={stripTitleHeading(entry.content, entry.title)}
                  isLoading={false}
                />
              </div>
              <p className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                {sourceIds.length > 0 && (
                  <Button
                    aria-expanded={lineageOpen}
                    className="h-6 px-2 text-[10px] tabular-nums"
                    onClick={() => setLineageOpen((value) => !value)}
                    size="sm"
                    variant="outline"
                  >
                    {sourceIds.length} {tw.sourceChunks}
                    <ChevronDown
                      className={cn("ml-1 size-3 transition-transform", lineageOpen && "rotate-180")}
                    />
                  </Button>
                )}
                <span>
                  {tk.updatedAt} {formatKnowledgeTimestamp(entry.updated_at, locale)}
                </span>
              </p>
              {lineageOpen && sourceIds.length > 0 && (
                <div className="flex flex-col gap-2">
                  {lineageQuery.isLoading && (
                    <p className="text-muted-foreground py-2 text-center text-xs">{tw.loading}</p>
                  )}
                  {(lineageQuery.data ?? []).map((chunk, position) => (
                    <ChunkCard
                      docId={chunk.doc_id}
                      docName={chunk.doc_name ?? undefined}
                      entities={chunk.entities}
                      headingPath={chunk.heading_path}
                      index={position}
                      kbId={kbId ?? undefined}
                      key={chunk.chunk_id}
                      page={chunk.page}
                      text={chunk.text}
                      tokenCount={chunk.token_count}
                    />
                  ))}
                  {lineageQuery.data && sourceIds.length > lineageQuery.data.length && (
                    <p className="text-muted-foreground text-xs">
                      {sourceIds.length - lineageQuery.data.length} {tw.deletedSources}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
