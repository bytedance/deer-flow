"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
import { useI18n } from "@/core/i18n/hooks";
import { listDocumentChunks } from "@/core/knowledge/api";
import { knowledgeChunksKey } from "@/core/knowledge/hooks";
import type { KnowledgeChunk, KnowledgeDocument } from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

import { ChunkCard } from "./chunk-card";
import { FileTypeBadge } from "./file-type-badge";

const PAGE_SIZE = 20;
/** 单文档切片在该阈值内一次性全量加载（2026-09-05 切片导航）：跳转纯前端；
    超过才退回「加载更多」。 */
const FULL_LOAD_CAP = 300;

/**
 * Chunk preview drawer (spec §3.6): opens from a document row click and
 * paginates through the chunks endpoint. Read-only in the first phase —
 * editing, re-extraction and deletion are post-phase.
 */
export function ChunkDrawer({
  kbId,
  doc,
  open,
  onOpenChange,
}: {
  kbId: string;
  doc: KnowledgeDocument;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const tc = t.knowledge.chunkDrawer;
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [activeIndex, setActiveIndex] = useState(0);
  const [flashIndex, setFlashIndex] = useState<number | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const headerRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef(new Map<number, HTMLDivElement>());
  const pendingJumpRef = useRef<number | null>(null);

  // Use raw query for configurable polling when pending extraction detected
  const query = useQuery({
    queryKey: knowledgeChunksKey(kbId, doc.id, 0, limit),
    queryFn: () => listDocumentChunks(kbId, doc.id, { offset: 0, limit }),
    enabled: open,
  });
  const page = query.data;
  const isLoading = query.isLoading;
  // useMemo 稳定引用：items 是多个 effect/memo 的依赖，裸 ?? [] 每渲染新数组
  // 会让它们每帧重跑（react-hooks/exhaustive-deps）。
  const items = useMemo(() => page?.items ?? [], [page]);

  const total = page?.total ?? 0;
  const hasMore = items.length < total;

  // 阈值内一次性全量加载（2026-09-05 切片导航）：跳转纯前端；超过
  // FULL_LOAD_CAP 才退回「加载更多」。
  useEffect(() => {
    if (total > 0 && total <= FULL_LOAD_CAP) {
      setLimit((value) => (value < total ? total : value));
    }
  }, [total]);

  // ── 切片导航（2026-09-05）：sticky 头部位置感 + ↑↓ 跳转 ──────────
  const itemsRef = useRef<KnowledgeChunk[]>([]);
  itemsRef.current = items;

  const scrollToIndex = useCallback((index: number) => {
    const viewport = viewportRef.current;
    const card = cardRefs.current.get(index);
    if (!viewport || !card) return;
    const headerHeight = headerRef.current?.offsetHeight ?? 0;
    const top =
      card.getBoundingClientRect().top -
      viewport.getBoundingClientRect().top +
      viewport.scrollTop -
      headerHeight -
      8;
    viewport.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    setFlashIndex(index);
    window.setTimeout(
      () => setFlashIndex((value) => (value === index ? null : value)),
      1200,
    );
  }, []);

  const jumpTo = useCallback(
    (index: number) => {
      if (index < 0 || index >= total) return;
      if (index >= itemsRef.current.length) {
        // 目标尚未加载：先扩 limit，数据到位后由下方 effect 续跳。
        pendingJumpRef.current = index;
        setLimit((value) =>
          Math.max(value, Math.ceil((index + 1) / PAGE_SIZE) * PAGE_SIZE),
        );
        return;
      }
      scrollToIndex(index);
    },
    [total, scrollToIndex],
  );

  useEffect(() => {
    const pending = pendingJumpRef.current;
    if (pending === null || pending >= items.length) return;
    pendingJumpRef.current = null;
    requestAnimationFrame(() => scrollToIndex(pending));
  }, [items, scrollToIndex]);

  // active = 顶部越过视口上 1/3 带的最后一张卡；rAF 节流的 scroll 监听挂在
  // Radix viewport 元素上（ScrollArea 经 viewportRef 外露）。
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const band =
        viewport.getBoundingClientRect().top + viewport.clientHeight * 0.35;
      let current = 0;
      for (const [position] of itemsRef.current.entries()) {
        const card = cardRefs.current.get(position);
        if (!card || card.getBoundingClientRect().top > band) break;
        current = position;
      }
      setActiveIndex(current);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    viewport.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      if (frame) cancelAnimationFrame(frame);
      viewport.removeEventListener("scroll", onScroll);
    };
  }, [open, items]);

  return (
    <Sheet onOpenChange={onOpenChange} open={open}>
      <SheetContent className="w-full overflow-hidden sm:max-w-xl" side="right">
        {/* 百科 Tab 容器同款 overlay 滚动条（2026-09-04）：整抽屉经
            ScrollArea 滚动；头部 sticky 留在视口内承担位置感（2026-09-05 切片导航）。 */}
        <div className="relative flex min-h-0 flex-1 flex-col">
          <ScrollArea
            className="min-h-0 w-full flex-1"
            scrollHideDelay={2000}
            type="scroll"
            viewportRef={viewportRef}
          >
            <SheetHeader
              className="sticky top-0 z-10 border-b bg-background/95 px-4 py-2.5 backdrop-blur-sm"
              ref={headerRef}
            >
              {/* 单行紧凑头（2026-09-05 头部重设计）：文档名主标题 + 类型徽章，
                  计数/当前位置徽章芯片化（不再裸文字）；描述仅 sr-only 供无障碍。 */}
              <div className="flex items-center justify-between gap-2 pr-8">
                <div className="flex min-w-0 items-center gap-1.5">
                  {/* 文档类型图标（2026-09-05）：复用文档列表同款 FileTypeBadge
                      （size-5 = 保住折角细节的 S 档），标题与列表视觉同源。 */}
                  <FileTypeBadge className="size-5 shrink-0" fileName={doc.name} />
                  <SheetTitle className="truncate">{doc.name}</SheetTitle>
                  <Badge className="shrink-0 text-[10px]" variant="secondary">
                    {tc.title}
                  </Badge>
                  <Badge className="shrink-0 text-[10px] tabular-nums" variant="outline">
                    {total} {tc.chunkUnit}
                  </Badge>
                  {total > 0 && (
                    <Badge className="shrink-0 text-[10px] tabular-nums" variant="outline">
                      {tc.current} #{activeIndex + 1}
                    </Badge>
                  )}
                </div>
                <div className="flex shrink-0 gap-0.5">
                  <Button
                    aria-label={tc.prevChunk}
                    className="size-7"
                    disabled={activeIndex <= 0}
                    onClick={() => jumpTo(activeIndex - 1)}
                    size="icon"
                    title={tc.prevChunk}
                    variant="ghost"
                  >
                    <ChevronUp className="size-4" />
                  </Button>
                  <Button
                    aria-label={tc.nextChunk}
                    className="size-7"
                    disabled={activeIndex >= total - 1}
                    onClick={() => jumpTo(activeIndex + 1)}
                    size="icon"
                    title={tc.nextChunk}
                    variant="ghost"
                  >
                    <ChevronDown className="size-4" />
                  </Button>
                </div>
              </div>
              <SheetDescription className="sr-only">
                {total} {tc.chunkUnit}
                {total > 0 ? ` · ${tc.current} #${activeIndex + 1}` : ""}
              </SheetDescription>
            </SheetHeader>
            <div className="flex flex-col gap-2 px-4 pt-4 pb-6">
              {items.length === 0 && !isLoading ? (
                <p className="text-muted-foreground py-8 text-center text-sm">
                  {tc.empty}
                </p>
              ) : (
                items.map((chunk, position) => (
                  <div
                    className={cn(
                      "rounded-md transition-shadow duration-500",
                      flashIndex === position && "ring-ring/60 ring-2",
                    )}
                    data-chunk-id={chunk.chunk_id}
                    key={chunk.chunk_id}
                    ref={(el) => {
                      // refs 以列表位置为键（2026-09-05 序号统一）：chunk_index 是
                      // 稳定身份（删除留空洞），UI 序号/跳转/active 全走位置序。
                      if (el) cardRefs.current.set(position, el);
                      else cardRefs.current.delete(position);
                    }}
                  >
                    <ChunkCard
                      chunkId={chunk.chunk_id}
                      docId={doc.id}
                      entities={chunk.entities}
                      headingPath={chunk.heading_path}
                      index={position}
                      kbId={kbId}
                      page={chunk.page}
                      text={chunk.text}
                      tokenCount={chunk.token_count}
                    />
                  </div>
                ))
              )}
              {isLoading && (
                <p className="text-muted-foreground py-4 text-center text-xs">
                  {tc.loading}
                </p>
              )}
              {hasMore && !isLoading && (
                <Button
                  className="self-center"
                  onClick={() => setLimit((value) => value + PAGE_SIZE)}
                  size="sm"
                  variant="ghost"
                >
                  {tc.loadMore}
                </Button>
              )}
            </div>
          </ScrollArea>
        </div>
      </SheetContent>
    </Sheet>
  );
}
