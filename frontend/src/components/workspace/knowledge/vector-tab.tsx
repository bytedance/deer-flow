"use client";

/**
 * 向量空间面板（2026-08-15 spec §8 P5）：工具栏（collection chips / 2D·3D /
 * 算法 / 重新计算）+ echarts 散点画布。本组件持有全部数据与交互逻辑
 * （纯 React 可测）；canvas 适配层经 next/dynamic 懒加载隔离（jsdom 中
 * 整体 mock）。3D 切换与重新计算在 Task 7 接通，本任务渲染禁用态。
 *
 * 工具栏三档降级（2026-08-17 二迭代，窄栏防重叠错位）：
 * ① 档0——chips 色点+文字、右侧控件内联；
 * ② 档1——chips 仅色点（aria-label + tooltip 兜底，未激活色点降透明度）；
 * ③ 档2——2D/3D 与算法收进 ⋯ 菜单，重算图标常驻。
 * 升档不走固定像素断点——溢出检测（scrollWidth > clientWidth）自校准；
 * flex-nowrap 保证任何档位不换行、无两行跳高。全部控件统一 24px
 * （h-6/size-6；SelectTrigger 需 h-6! 压过 data-[size] 高特异性高度）——本栏钉
 * h-9(36px) 对齐表头，控件 24px 占比 67%≈搜索框(28px)在 44px 栏的 64%，视觉协调
 * （原 h-7=28 占 78% 显笨重）；搜索框 Input 仍 h-7（它在 44px 搜索栏，另一节奏）。
 * chips 选中态 = collection 同色浅底（hex alpha），outline 变体常驻边框，
 * 选中/取消切换不改变按钮宽度。
 */
import { MoreHorizontal, RefreshCw, Search, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import {
  useProjectVectorQuery,
  useRecomputeVectorProjection,
  useVectorProjection,
} from "@/core/knowledge/hooks";
import type {
  VectorProjectionAlgo,
  VectorProjectionPoint,
  VectorRetrievalOverlay,
} from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

import { toast } from "./kb-toast";
import type { VectorCanvasProps } from "./vector-canvas";

// ssr:false —— echarts 依赖 DOM/WebGL，且不进首屏 chunk（性能预算体系只测
// SSR HTML 引用资源，异步 chunk 天然豁免）。
const VectorCanvas = dynamic<VectorCanvasProps>(() => import("./vector-canvas"), { ssr: false });

export type VectorCollectionKey = "chunks" | "entities" | "wiki" | "cards";
const ALL_COLLECTIONS: readonly VectorCollectionKey[] = ["chunks", "entities", "wiki", "cards"];

/** 搜索范围（2026-09-05）：全部 / 单类——客户端过滤，不重拉投影、不丢空间上下文。 */
type SearchScope = "all" | VectorCollectionKey;

/** source_type → collection key（全量搜索的范围过滤与命中分组计数共用）。 */
const COLLECTION_OF_SOURCE: Record<string, VectorCollectionKey> = {
  chunk: "chunks",
  entity: "entities",
  wiki: "wiki",
  card: "cards",
};

/** One legend series: points sharing one collection color (spec §8 2026-08-15 UX 迭代). */
export interface VectorSeriesGroup {
  key: string;
  sourceType: string;
  /** 图例显示名：四类固定文案（切片/实体/百科/条目，均两字对齐）。 */
  label: string;
  color: string;
  points: VectorProjectionPoint[];
}

/**
 * 四类固定色（2026-08-15 用户拍板 UX 迭代）：文档一多，按个体（doc_id/type）
 * 分组会让图例和画面太花——改为每类 collection 统一一色，图例恒四项。
 * 与工具栏 chips 色点同源。
 * 2026-08-17：用户拍板采用 Material Design 400 级色板（对齐参考实现）——
 * 介于 echarts 默认高饱和与降饱和柔和版之间。曾试过经典四色（太浓）、
 * 降饱和版（灰蒙蒙）、参考图采样浅色版，均弃。
 */
const SOURCE_COLORS: Record<string, string> = {
  chunk: "#42a5f5",
  entity: "#66bb6a",
  wiki: "#ab47bc",
  card: "#ff7043",
};

/** chips 色点直接复用四类固定色。 */
const CHIP_COLORS: Record<VectorCollectionKey, string> = {
  chunks: SOURCE_COLORS.chunk!,
  entities: SOURCE_COLORS.entity!,
  wiki: SOURCE_COLORS.wiki!,
  cards: SOURCE_COLORS.card!,
};

/** 着色分组（UX 迭代后）：按 source_type 聚为四组，各一色，图例固定文案。 */
export function groupPointsIntoSeries(
  points: readonly VectorProjectionPoint[],
  labels: { chunks: string; entities: string; wiki: string; cards: string },
): VectorSeriesGroup[] {
  const labelFor: Record<string, string> = {
    chunk: labels.chunks,
    entity: labels.entities,
    wiki: labels.wiki,
    card: labels.cards,
  };
  const groups = new Map<string, VectorSeriesGroup>();
  for (const point of points) {
    let group = groups.get(point.source_type);
    if (!group) {
      group = {
        key: point.source_type,
        sourceType: point.source_type,
        label: labelFor[point.source_type] ?? point.source_type,
        color: SOURCE_COLORS[point.source_type] ?? "#73c0de",
        points: [],
      };
      groups.set(point.source_type, group);
    }
    group.points.push(point);
  }
  return [...groups.values()];
}

/** 档级：0=全量（chips 色点+文字、控件内联） 1=chips 仅色点 2=控件收进 ⋯ 菜单。 */
type ToolbarTier = 0 | 1 | 2;

/**
 * 工具栏自适应降级：固定像素断点估不准真实渲染宽度（字体/缩放/文案都会变），
 * 改为直接检测溢出——scrollWidth > clientWidth 即升档；回落不猜节省量，升档时
 * 记录当前档位内容的 scrollWidth 作为恢复点，宽度回到该值即降档（+4px 防亚像素抖动）。
 * jsdom 无布局（scrollWidth 恒 0）→ 恒 0 档，单测只见宽档控件（窄档用例钉
 * scrollWidth 模拟溢出）。
 */
function useToolbarTier(ref: RefObject<HTMLDivElement | null>): ToolbarTier {
  const [tier, setTier] = useState<ToolbarTier>(0);
  const tierRef = useRef<ToolbarTier>(0);
  const restoreWidth = useRef<[number, number, number]>([0, 0, 0]);

  const evaluate = useCallback(() => {
    const element = ref.current;
    if (!element) return;
    const width = element.clientWidth;
    const overflow = element.scrollWidth > width + 1;
    const current = tierRef.current;
    if (overflow && current < 2) {
      // 记录当前档位内容的需求宽度——升档后回落到本档的精确触发点。
      restoreWidth.current[current + 1] = element.scrollWidth + 4;
      tierRef.current = (current + 1) as ToolbarTier;
      setTier(tierRef.current);
    } else if (!overflow && current > 0 && width >= restoreWidth.current[current]) {
      tierRef.current = (current - 1) as ToolbarTier;
      setTier(tierRef.current);
    }
  }, [ref]);

  // 每次渲染后校准（幂等：档级不变则不 setState，不自激）——覆盖内容变化
  // （采样徽标出现/消失）与档级切换后的级联再评估。
  useEffect(() => {
    evaluate();
  });
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(evaluate);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, evaluate]);

  return tier;
}

export function VectorTab({
  kbId,
  enabled,
  indexingCount = 0,
  overlay,
  onOpenChunk,
  onOpenWikiEntry,
  onOpenManualCard,
  followChat: followChatProp,
  onFollowChatChange,
}: {
  kbId: string;
  /** keep-alive pane 的懒加载门：仅 tab 激活后才发起投影请求。 */
  enabled: boolean;
  /** 仍在索引管线中的文档数（>0 时提示投影可能不完整）。 */
  indexingCount?: number;
  /**
   * P6 检索联动（2026-08-15 spec §9）：page 层共享的叠加请求。recall 一键
   * 跳转（显式动作，恒应用）与 chat 每轮跟随（受「跟随对话」开关管辖）共用。
   */
  overlay?: VectorRetrievalOverlay | null;
  /** chunk 点击：(doc_id, chunk_id) —— page 层回查完整 doc 再开抽屉。 */
  onOpenChunk: (docId: string, chunkId: string) => void;
  onOpenWikiEntry: (entryId: string) => void;
  onOpenManualCard: (cardId: string) => void;
  /**
   * 「跟随对话」开关（2026-08-19 spec §7：与知识图谱 tab 共享状态——page 层
   * 下发时受控）；缺省 = 内部状态（默认开）。
   */
  followChat?: boolean;
  onFollowChatChange?: (next: boolean) => void;
}) {
  const { t } = useI18n();
  const tv = t.knowledge.vectorSpace;
  const [collections, setCollections] = useState<VectorCollectionKey[]>([...ALL_COLLECTIONS]);
  const [algo, setAlgo] = useState<VectorProjectionAlgo>("pca");
  const [dims, setDims] = useState<2 | 3>(2);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const toolbarTier = useToolbarTier(toolbarRef);
  // 聚焦交互（2026-09-05 全量搜索泛化）：搜索框匹配四类点 label（文档名/
  // 实体名/条目标题）→ 命中点全亮、未命中全类浅淡出（看命中邻居，
  // canvas 侧 SEARCH_DIMMED_OPACITY）；范围下拉限定匹配类别；清空恢复。
  // 搜索锁定优先于 hover 聚焦（canvas 内合成）。
  const [searchQuery, setSearchQuery] = useState("");
  const [searchScope, setSearchScope] = useState<SearchScope>("all");

  const projectionQuery = useVectorProjection(kbId, { collections, algo, dims }, enabled);
  const projection = projectionQuery.data;
  const recompute = useRecomputeVectorProjection(kbId);

  // ── P6 检索联动叠加（spec §9）──────────────────────────────────────────
  // params 镜像当前视图：服务端缓存键含 collections/algo/dims，错位即 409。
  const projectQuery = useProjectVectorQuery(kbId, { collections, algo, dims });
  /** 「跟随对话」开关（默认开）：关闭后 chat 通道叠加冻结，供手动探索。
      受控/非受控混合——page 层共享状态（与图谱 tab 同步）时经 props 下发。 */
  const [internalFollowChat, setInternalFollowChat] = useState(true);
  const followChat = followChatProp ?? internalFollowChat;
  const setFollowChat = onFollowChatChange ?? setInternalFollowChat;
  const [activeOverlay, setActiveOverlay] = useState<{
    query: { x: number; y: number; z?: number; label: string };
    hits: VectorRetrievalOverlay["hits"];
    fingerprint: string;
  } | null>(null);
  // 当前指纹的穿透 ref：query 投影回调到达时投影可能已换（重算），比对必须读最新值。
  const fingerprint = projection?.fingerprint;
  const fingerprintRef = useRef(fingerprint);
  fingerprintRef.current = fingerprint;
  const activeOverlayRef = useRef(activeOverlay);
  activeOverlayRef.current = activeOverlay;
  // 请求去重句柄：同一 overlay 对象在同一 algo 下只投影一次；algo 切走再切回
  // 允许重投影（umap 下被禁用的请求回到 pca 后应能生效）。
  const consumedRef = useRef<{ overlay: VectorRetrievalOverlay; algo: string } | null>(null);

  // 叠加请求 → 投影 query 文本（POST /vector-projection/query 复用缓存模型）。
  useEffect(() => {
    if (!overlay || !fingerprint) {
      return; // 无请求，或投影未就绪（enabled 门 / 加载中）——等 projection 落地后重跑
    }
    const consumed = consumedRef.current;
    if (consumed?.overlay === overlay && consumed.algo === algo) {
      return;
    }
    if (overlay.source === "chat" && !followChat) {
      return; // 冻结：不写 consumed——解冻后 effect 重跑即应用最新一轮
    }
    consumedRef.current = { overlay, algo };
    if (algo !== "pca") {
      // spec §9 公共边界：query 投影仅支持 PCA（UMAP transform 不稳定）。
      toast.info(tv.overlayPcaOnly);
      return;
    }
    projectQuery.mutate(overlay.text, {
      onSuccess: (result) => {
        if (result.fingerprint !== fingerprintRef.current) {
          // 坐标系已换：旧叠加留在图上就是误导（spec §11 坐标漂移风险）。
          setActiveOverlay(null);
          toast.info(tv.overlayStale);
          return;
        }
        setActiveOverlay({
          query: { x: result.x, y: result.y, z: result.z, label: overlay.text },
          hits: overlay.hits,
          fingerprint: result.fingerprint,
        });
      },
      onError: () => {
        // 不再静默（用户可感 bug）：409 = 缓存键错位/缓存被清；500 = embedder
        // 故障——提示重试，detail 留 console。
        toast.info(tv.overlayFailed);
      },
    });
  }, [overlay, fingerprint, algo, followChat, projectQuery, tv]);

  // 投影指纹变化（重新计算 / 内容变更）→ 丢弃基于旧坐标系的叠加并提示。
  useEffect(() => {
    const current = activeOverlayRef.current;
    if (current && fingerprint && current.fingerprint !== fingerprint) {
      setActiveOverlay(null);
      toast.info(tv.overlayStale);
    }
  }, [fingerprint, tv]);

  const series = useMemo(
    () =>
      groupPointsIntoSeries(projection?.points ?? [], {
        chunks: tv.chips.chunks,
        entities: tv.chips.entities,
        wiki: tv.chips.wiki,
        cards: tv.chips.cards,
      }),
    [projection, tv],
  );

  /**
   * 全量搜索（2026-09-05）：四类点 label 大小写不敏感子串匹配（范围下拉
   * 过滤参与类别）→ 命中点 id 集合。搜文档名时该文档全部切片同 label
   * 自然全命中，旧语义无损保留。命中反馈不走芯片（按类计数已退役，
   * 用户实测效果不佳），由画布侧命中强调承载（提满不透明+放大）。
   */
  const searchedPointIds = useMemo(() => {
    const needle = searchQuery.trim().toLowerCase();
    if (!needle) return null;
    const ids = new Set<string>();
    for (const point of projection?.points ?? []) {
      const collection = COLLECTION_OF_SOURCE[point.source_type];
      if (!collection) continue;
      if (searchScope !== "all" && collection !== searchScope) continue;
      if (point.label.toLowerCase().includes(needle)) {
        ids.add(point.id);
      }
    }
    return ids;
  }, [searchQuery, searchScope, projection]);

  const handleDimsChange = (value: string) => {
    if (value === "2" || value === "3") {
      setDims(Number(value) as 2 | 3);
    }
  };

  const handleAlgoChange = (value: string) => setAlgo(value as VectorProjectionAlgo);

  const toggleCollection = (key: VectorCollectionKey) => {
    setCollections((previous) => {
      const next = previous.includes(key) ? previous.filter((k) => k !== key) : [...previous, key];
      // 保持 ALL_COLLECTIONS 声明顺序，请求参数稳定（缓存键友好）。
      return ALL_COLLECTIONS.filter((k) => next.includes(k));
    });
  };

  /** 点击分发（spec §8：复用现有抽屉链路；entity 无详情目标，保持惰性）。 */
  const handlePointClick = (point: VectorProjectionPoint) => {
    if (point.source_type === "chunk") {
      onOpenChunk(point.color_key, point.id);
    } else if (point.source_type === "wiki") {
      onOpenWikiEntry(point.id);
    } else if (point.source_type === "card") {
      onOpenManualCard(point.id);
    }
  };

  const points = projection?.points ?? [];
  const showCanvas = !projectionQuery.isLoading && !projectionQuery.isError && points.length > 0;

  // 叠加徽标命中数（2026-08-19 UX 迭代）：命中点可能不在当前投影中（采样丢弃 /
  // collection 被关）——此前静默跳过，现在「命中 m/n」让缺口可见。
  // 依赖 projection（稳定引用）而非 points（?? [] 兜底每渲染新引用会击穿 useMemo）。
  const overlayHitCounts = useMemo(() => {
    if (!activeOverlay) return null;
    const ids = new Set((projection?.points ?? []).map((point) => point.id));
    const matched = activeOverlay.hits.filter((hit) => ids.has(hit.pointId)).length;
    return { matched, total: activeOverlay.hits.length };
  }, [activeOverlay, projection]);

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="vector-tab">
      {/* 搜索栏（wiki-tab 同款独立一栏，置于工具栏上方；2026-09-05 全量搜索）：
          匹配四类点 label → 命中强调（提满不透明+放大），未命中深淡出；右侧
          范围下拉限定匹配类别（客户端过滤）。命中计数芯片已退役（用户实测
          效果不佳，反馈由画布命中强调承载）。
          去 border-b（2026-09-02）：这条线正是下方工具栏的「上边线」，用户反馈
          工具栏被上下两条线夹住；去掉后搜索栏与工具栏靠留白分界，且 border 不再
          参与盒高，本栏高度从 44.67 落到 44.00，与文档/评测工具栏对齐。 */}
      <div className="shrink-0 px-4 py-2">
        <div className="flex items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <Search className="text-muted-foreground absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
            <Input
              aria-label={tv.searchAll}
              className="h-7 pr-2 pl-7 text-xs"
              placeholder={tv.searchAll}
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>
          <Select
            value={searchScope}
            onValueChange={(value) => setSearchScope(value as SearchScope)}
          >
            <SelectTrigger
              aria-label={tv.searchScopeLabel}
              className="h-7! w-auto shrink-0 gap-1 px-2 text-xs"
              size="sm"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{tv.searchScopes.all}</SelectItem>
              <SelectItem value="chunks">{tv.searchScopes.chunks}</SelectItem>
              <SelectItem value="entities">{tv.searchScopes.entities}</SelectItem>
              <SelectItem value="wiki">{tv.searchScopes.wiki}</SelectItem>
              <SelectItem value="cards">{tv.searchScopes.cards}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* 工具栏：collection chips + 维度/算法/重算（flex-nowrap + 溢出检测降级，任何档位不换行）。
          高度钉 h-9（36px，2026-09-02）：与文档/评测 tab 的表头（thead h-9=36px）对齐——
          向量空间顶部两行对应文档「工具栏(44)+表头(36)」节奏，本行是第二行、扮演表头角色。
          控件统一 h-6/size-6（24px，2026-09-02）：24px 在 36px 栏占比 67%≈搜索框(28px)
          在 44px 栏的 64%，视觉协调（原 h-7=28 占 78% 显笨重）。
          pb-1 光学补偿（2026-09-02 恢复）：控件缩到 24px 后纯几何居中(6/6)仍显靠下——
          下方 inset 发丝线是强视觉锚点，其视觉重量与控件大小无关，只要下方有线就需补偿；
          pb-1 让控件几何偏上（topGap 4 / bottomGap 8），视觉上才居中。
          下方发丝线用 inset 阴影而非 border-b：border 参与盒高会击穿 36px 钉高（阴影不参与
          布局），同时保留工具栏与下方画布的分隔线（画布无表头，需要这条线）。 */}
      <div
        ref={toolbarRef}
        className="flex h-9 flex-nowrap items-center gap-1.5 overflow-hidden px-4 pb-1 shadow-[inset_0_-1px_0_var(--border)]"
        data-testid="vector-toolbar"
      >
        {ALL_COLLECTIONS.map((key) => {
          const active = collections.includes(key);
          return (
            <Tooltip key={key}>
              <TooltipTrigger asChild>
                {/* 选中态 = collection 同色浅底 + 同色边框（hex alpha）；outline
                    常驻边框 → 选中/取消切换不改变宽度。 */}
                <Button
                  aria-label={tv.chips[key]}
                  aria-pressed={active}
                  className={cn("h-6 gap-1.5 px-2 text-xs", !active && "text-muted-foreground")}
                  size="sm"
                  style={
                    active
                      ? {
                          backgroundColor: `${CHIP_COLORS[key]}1f`,
                          borderColor: `${CHIP_COLORS[key]}80`,
                        }
                      : undefined
                  }
                  variant="outline"
                  onClick={() => toggleCollection(key)}
                >
                  <span
                    aria-hidden
                    className={cn("size-2 rounded-full", !active && "opacity-40")}
                    style={{ backgroundColor: CHIP_COLORS[key] }}
                  />
                  {toolbarTier === 0 && <span>{tv.chips[key]}</span>}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{tv.chips[key]}</TooltipContent>
            </Tooltip>
          );
        })}
        <div className="ml-auto flex items-center gap-2">
          {projection?.sampled && (
            <Badge className="shrink-0 text-xs" variant="secondary">
              {tv.sampledBadge(projection.shown_points, projection.total_points)}
            </Badge>
          )}
          {/* 档0/1：控件内联（档2 收进 ⋯ 菜单） */}
          {toolbarTier < 2 && (
            <>
              <ToggleGroup
                size="sm"
                type="single"
                value={String(dims)}
                variant="outline"
                onValueChange={handleDimsChange}
              >
                <ToggleGroupItem aria-label="2D" className="h-6 px-2 text-xs" value="2">
                  2D
                </ToggleGroupItem>
                <ToggleGroupItem aria-label="3D" className="h-6 px-2 text-xs" value="3">
                  3D
                </ToggleGroupItem>
              </ToggleGroup>
              {/* 算法 label 省略（PCA/UMAP 值自解释）；Select 收窄 + h-6!
                  压过 data-[size] 高特异性高度，与全栏 24px 对齐；px-2/gap-1.5
                  紧凑内距，防下拉箭头遮挡 UMAP 文字。 */}
              <Select value={algo} onValueChange={handleAlgoChange}>
                <SelectTrigger aria-label={tv.algoLabel} className="h-6! w-20 gap-1.5 px-2 text-xs" size="sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pca">PCA</SelectItem>
                  <SelectItem value="umap">UMAP</SelectItem>
                </SelectContent>
              </Select>
            </>
          )}
          {/* 档2：⋯ 菜单（RadioItem 承载切换，无嵌套弹层，交互稳健） */}
          {toolbarTier === 2 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button aria-label={tv.moreOptions} className="size-6" size="icon" variant="outline">
                  <MoreHorizontal className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>{tv.dimsLabel}</DropdownMenuLabel>
                <DropdownMenuRadioGroup value={String(dims)} onValueChange={handleDimsChange}>
                  <DropdownMenuRadioItem value="2">2D</DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="3">3D</DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>{tv.algoLabel}</DropdownMenuLabel>
                <DropdownMenuRadioGroup value={algo} onValueChange={handleAlgoChange}>
                  <DropdownMenuRadioItem value="pca">PCA</DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="umap">UMAP</DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          {/* P6「跟随对话」开关（spec §9 通道二）：默认开；关闭后 chat 通道
              叠加冻结，供手动探索。常驻各档（不进 … 菜单）。 */}
          <Tooltip>
            <TooltipTrigger asChild>
              <label className="text-muted-foreground flex shrink-0 cursor-pointer items-center gap-1.5 text-xs">
                <Switch
                  aria-label={tv.followChat}
                  checked={followChat}
                  className="shrink-0"
                  onCheckedChange={setFollowChat}
                />
                {toolbarTier === 0 && <span className="whitespace-nowrap">{tv.followChat}</span>}
              </label>
            </TooltipTrigger>
            <TooltipContent>{tv.followChat}</TooltipContent>
          </Tooltip>
          {/* 重新计算：低频操作降级为图标按钮（aria-label/tooltip 兑底可发现性），
              pending 时图标自旋。 */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                aria-label={tv.recompute}
                className="size-6"
                disabled={recompute.isPending}
                size="icon"
                variant="outline"
                onClick={() => recompute.mutate({ collections, algo, dims })}
              >
                <RefreshCw className={cn("size-3.5", recompute.isPending && "animate-spin")} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{tv.recompute}</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* 索引中提示（投影可能不完整） */}
      {indexingCount > 0 && (
        <div className="border-b px-4 py-1.5 text-xs text-amber-600 dark:text-amber-500">
          {tv.indexingHint(indexingCount)}
        </div>
      )}

      {/* 主体：三态 + 画布（relative 供叠加徽标浮层定位） */}
      <div className="relative min-h-0 flex-1">
        {projectionQuery.isLoading && (
          <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
            {tv.loading}
          </div>
        )}
        {projectionQuery.isError && (
          <div className="flex h-full flex-col items-center justify-center gap-1 text-sm">
            <span className="text-destructive">{tv.loadFailed}</span>
            {projectionQuery.error instanceof Error && projectionQuery.error.message && (
              <span className="text-muted-foreground max-w-md text-center text-xs">
                {projectionQuery.error.message}
              </span>
            )}
          </div>
        )}
        {!projectionQuery.isLoading && !projectionQuery.isError && points.length === 0 && (
          <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
            {tv.empty}
          </div>
        )}
        {showCanvas && (
          <VectorCanvas
            dims={dims}
            overlay={activeOverlay}
            searchedPointIds={searchedPointIds}
            series={series}
            onPointClick={handlePointClick}
          />
        )}
        {/* 叠加徽标（2026-08-19 UX 迭代）：地图式左上浮层——当前叠加的 query 文本
            + 命中 m/n + × 清除。此前叠加一旦激活无出口（只能等指纹漂移），用户
            无法主动取消连线。 */}
        {showCanvas && activeOverlay && overlayHitCounts && (
          <div
            className="bg-background/80 absolute top-2 left-2 z-10 flex max-w-[70%] items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs shadow-sm backdrop-blur"
            data-testid="vector-overlay-badge"
          >
            <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ backgroundColor: "#f5222d" }} />
            <span className="min-w-0 truncate" title={activeOverlay.query.label}>
              {activeOverlay.query.label}
            </span>
            <span className="text-muted-foreground shrink-0">
              {tv.overlayHits(overlayHitCounts.matched, overlayHitCounts.total)}
            </span>
            <button
              aria-label={tv.clearOverlay}
              className="text-muted-foreground hover:text-foreground ml-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-full"
              type="button"
              onClick={() => setActiveOverlay(null)}
            >
              <X className="size-3" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
