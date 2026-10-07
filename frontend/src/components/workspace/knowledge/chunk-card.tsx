"use client";

import { Code2, Eye, ImageOff } from "lucide-react";
import { type ComponentProps, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { MarkdownContent } from "@/components/workspace/messages/markdown-content";
import { useI18n } from "@/core/i18n/hooks";
import { documentFileUrl } from "@/core/knowledge/api";

/** 实体徽章展示上限（2026-09-05 切片导航卡片减重）：超出折成 +N，title 列其余。 */
const ENTITY_CAP = 6;

/**
 * Chunk markdown image (2026-08-22 切片图片显示): MinerU-parsed images are
 * referenced as relative `images/…` paths; the worker persists them next to
 * the source document and the gateway serves them via the files route, so the
 * ref is rewritten when the card knows its kb/doc. Absolute/data URLs pass
 * through untouched; a failed load degrades to the caption (alt) line instead
 * of the renderer's generic "Image not available" placeholder.
 */
export function ChunkImage({
  src,
  alt,
  kbId,
  docId,
  unavailableLabel,
  node: _node,
  ...props
}: ComponentProps<"img"> & { kbId?: string; docId?: string; unavailableLabel: string; node?: unknown }) {
  const [failed, setFailed] = useState(false);
  if (typeof src !== "string" || !src) return null;
  const resolved = kbId && docId && !/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(src) ? documentFileUrl(kbId, docId, src) : src;
  if (failed) {
    return (
      <span className="text-muted-foreground my-1.5 flex items-start gap-1.5 rounded-md border border-dashed px-2.5 py-1.5 text-xs">
        <ImageOff className="mt-0.5 size-3.5 shrink-0" />
        <span className="min-w-0 break-words">
          {unavailableLabel}
          {alt?.trim() ? `：${alt.trim()}` : ""}
        </span>
      </span>
    );
  }
  return (
    <img
      {...props}
      alt={alt}
      className="my-1.5 max-w-full rounded-md border"
      decoding="async"
      loading="lazy"
      onError={() => setFailed(true)}
      src={resolved}
    />
  );
}

/**
 * Shared chunk card (spec §3.6 切片可视化 / §4.6 引用展开): the chunk drawer
 * renders the full-metadata form; the citation card expands to the same
 * component with just doc name + text. Read-only in the first phase.
 */
export function ChunkCard({
  chunkId: _chunkId,
  text,
  headingPath,
  index,
  page,
  tokenCount,
  entities,
  docName,
  kbId,
  docId,
}: {
  /** Kept for call-site compatibility; the read-only card never reads it. */
  chunkId?: string;
  text: string;
  headingPath?: string[];
  /** 0-based 切片序号（2026-09-05 切片导航）：抽屉传入后卡片头部显示 #N；
      引用/召回等复用方不传则不显序号。 */
  index?: number;
  page?: number | null;
  tokenCount?: number;
  entities?: string[];
  docName?: string;
  /** Enable in-place image rendering: relative `images/…` refs resolve via the document files route. */
  kbId?: string;
  docId?: string;
}) {
  const { t } = useI18n();
  const tc = t.knowledge.chunkDrawer;
  // 渲染/原始切换（2026-08-22 展示增强）：查看态默认渲染 Markdown，调试切片
  // 边界时可切回原始文本（单换行、# 符号等原样保留）。
  const [viewMode, setViewMode] = useState<"rendered" | "raw">("rendered");
  const [entitiesExpanded, setEntitiesExpanded] = useState(false);
  const components = useMemo(
    () => ({
      img: (props: ComponentProps<"img">) => <ChunkImage docId={docId} kbId={kbId} unavailableLabel={tc.imageUnavailable} {...props} />,
    }),
    [docId, kbId, tc.imageUnavailable],
  );

  const hasHeader =
    index != null || Boolean(docName ?? (headingPath && headingPath.length > 0));
  const visibleEntities = entities
    ? entitiesExpanded
      ? entities
      : entities.slice(0, ENTITY_CAP)
    : entities;
  // 页脚栏渲染条件：有度量（tokens/页码）时才加分隔线。
  const hasFooterMeta = page != null || tokenCount != null;

  return (
    // 底色复用项目标准面板配方（2026-09-05 三改，同设置-集成 Card）：bg-card
    // （light 纯白 / dark 与 background 同档差）+ border，在 bg-background 窗底上
    // 自然分层；shadow 比 Card 的 shadow-sm 轻一档适配列表密度。
    <div className="bg-card text-card-foreground flex flex-col gap-1.5 rounded-md border p-3 text-sm shadow-xs">
      <div className="flex items-start justify-between gap-2">
        {hasHeader ? (
          <div className="text-muted-foreground flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs">
            {index != null && (
              <span className="font-mono tabular-nums opacity-80">#{index + 1}</span>
            )}
            {docName && <span className="font-medium">{docName}</span>}
            {headingPath && headingPath.length > 0 && <span>{headingPath.join(" / ")}</span>}
          </div>
        ) : (
          <span />
        )}
        <ToggleGroup
          className="ml-auto shrink-0"
          size="sm"
          type="single"
          value={viewMode}
          variant="outline"
          onValueChange={(value) => {
            if (value) {
              setViewMode(value as "rendered" | "raw");
            }
          }}
        >
          <ToggleGroupItem aria-label={tc.viewRendered} className="h-7 px-2" value="rendered">
            <Eye className="size-3.5" />
          </ToggleGroupItem>
          <ToggleGroupItem aria-label={tc.viewRaw} className="h-7 px-2" value="raw">
            <Code2 className="size-3.5" />
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

      {viewMode === "rendered" ? (
        <MarkdownContent
          className="text-sm [&_blockquote]:my-1.5 [&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-semibold [&_h4]:text-sm [&_h4]:font-medium [&_li]:my-0.5 [&_ol]:my-1.5 [&_p]:my-1.5 [&_pre]:my-2 [&_ul]:my-1.5"
          components={components}
          content={text}
          isLoading={false}
        />
      ) : (
        <p className="text-sm break-words whitespace-pre-wrap">{text}</p>
      )}
      {entities && entities.length > 0 && (
        <span className="text-muted-foreground flex flex-wrap items-center gap-1 text-xs">
          <span className="shrink-0">{tc.entities}:</span>
          {visibleEntities?.map((entity) => (
            <Badge className="text-[10px]" key={entity} variant="secondary">
              {entity}
            </Badge>
          ))}
          {entities.length > ENTITY_CAP && !entitiesExpanded && (
            <button
              onClick={() => setEntitiesExpanded(true)}
              title={entities.slice(ENTITY_CAP).join(", ")}
              type="button"
            >
              <Badge className="text-[10px]" variant="outline">
                +{entities.length - ENTITY_CAP}
              </Badge>
            </button>
          )}
        </span>
      )}
      {/* 页脚栏（2026-09-05 卡片重设计）：border-t 把度量与正文分层；
          tokens/页码不再夹在正文与按钮之间。 */}
      {hasFooterMeta && (
        <div className="flex flex-col gap-1 border-t border-border/60 pt-1.5">
          <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
            <span className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              {page != null && (
                <span>
                  {tc.page} {page}
                </span>
              )}
              {tokenCount != null && (
                <span>
                  {tokenCount} {tc.tokens}
                </span>
              )}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
