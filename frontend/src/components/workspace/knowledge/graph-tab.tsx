"use client";

/**
 * 知识图谱面板（2026-08-19 spec §5 P2）：数据/状态/钻取分发。持有
 * useKnowledgeGraph 查询与实体详情抽屉；画布经 next/dynamic 懒加载隔离
 * （jsdom 中整体 mock）。
 *
 * 钻取链路：点击节点 → 右侧抽屉（实体详情 + 关联切片列表）→ 点击切片
 * → onOpenChunk(docId, chunkId) 复用文档抽屉链路（chunk_id 内嵌 doc_id，
 * 前端无需二次查询）。
 */
import { AlignLeft, ChevronLeft, ChevronRight, FileText, Search, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useI18n } from "@/core/i18n/hooks";
import { useChunkPositions, useKnowledgeGraph } from "@/core/knowledge/hooks";
import type {
  GraphRetrievalOverlay,
  KnowledgeDocument,
  KnowledgeGraphNode,
} from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

import type { GraphCanvasProps } from "./graph-canvas";
import {
  buildCommunityColorMap,
  communityColor,
  filterNeighborhood,
  type GraphColorBy,
  GRAPH_FOCUS_ZOOM,
  isNodeRenderedAtZoom,
  matchEntityNames,
  type RenderTier,
  typeColor,
} from "./graph-utils";
import { toast } from "./kb-toast";

// ssr:false —— echarts 依赖 DOM，且不进首屏 chunk（对齐 vector-tab 先例）。
const GraphCanvas = dynamic<GraphCanvasProps>(() => import("./graph-canvas"), {
  ssr: false,
});

/** chunk_id（`{doc_id}#%04d`）→ doc_id；格式异常时返回 null（防御）。 */
function docIdOfChunk(chunkId: string): string | null {
  const sep = chunkId.lastIndexOf("#");
  return sep > 0 ? chunkId.slice(0, sep) : null;
}

export function GraphTab({
  kbId,
  enabled,
  documents,
  onOpenChunk,
  overlay,
  followChat: followChatProp,
  onFollowChatChange,
}: {
  kbId: string;
  /** keep-alive pane 的懒加载门：仅 tab 激活后才发起图数据请求。 */
  enabled: boolean;
  /** 文档列表（切片条目显示所属文档名；page 层已有，直接透传）。 */
  documents: readonly KnowledgeDocument[];
  /** 切片点击：(doc_id, chunk_id) —— page 层打开文档抽屉。 */
  onOpenChunk: (docId: string, chunkId: string) => void;
  /**
   * P4 检索联动（2026-08-19 spec §7）：page 层共享的 graph_search 轨迹叠加
   * 请求。chat 通道受「跟随对话」开关管辖（冻结语义在本组件内）。
   */
  overlay?: GraphRetrievalOverlay | null;
  /** 「跟随对话」开关（与向量空间共享状态，spec §7）；缺省 = 内部状态。 */
  followChat?: boolean;
  onFollowChatChange?: (next: boolean) => void;
}) {
  const { t } = useI18n();
  const tg = t.knowledge.graphSpace;
  // 行内「切片 #K」文案与检索测试悬浮气泡/切片抽屉徽章单一源。
  const tr = t.knowledge.recallTest;
  const graphQuery = useKnowledgeGraph(kbId, enabled);
  const graph = graphQuery.data;

  /** 当前打开的实体抽屉（null = 关闭）。 */
  const [selected, setSelected] = useState<KnowledgeGraphNode | null>(null);
  /** 着色模式（spec §6：默认按社区，结构洞察优先）。 */
  const [colorBy, setColorBy] = useState<GraphColorBy>("community");
  /** 搜索框输入与定位目标（命中节点居中高亮）。 */
  const [query, setQuery] = useState("");
  const [focusNode, setFocusNode] = useState<string | null>(null);
  /** 局部图模式（spec §6：双击节点进入，面包屑返回全局）。 */
  const [neighborhood, setNeighborhood] = useState<{
    focusId: string;
    hops: 1 | 2;
  } | null>(null);
  /** 当前 LOD 渲染档位（canvas 上报；guide 档显示引导提示）。 */
  const [renderTier, setRenderTier] = useState<RenderTier>("full");

  // ── P4 检索路径叠加（spec §7）──────────────────────────────────────────
  // 受控/非受控混合：page 层共享「跟随对话」状态时经 props 下发，独立使用时
  // 回落内部状态（与 vector-tab 同模式）。
  const [internalFollowChat, setInternalFollowChat] = useState(true);
  const followChat = followChatProp ?? internalFollowChat;
  const setFollowChat = onFollowChatChange ?? setInternalFollowChat;

  /** 已应用的叠加 + 应用时的图指纹（node_count:edge_count，stats 现成廉价）。 */
  const [activeOverlay, setActiveOverlay] = useState<{
    overlay: GraphRetrievalOverlay;
    fingerprint: string;
  } | null>(null);
  /** 请求去重句柄：同一 overlay 对象只应用一次（流式重渲染不重复叠加）。 */
  const consumedOverlayRef = useRef<GraphRetrievalOverlay | null>(null);
  const fingerprint = graph
    ? `${graph.stats.node_count}:${graph.stats.edge_count}`
    : null;
  const activeOverlayRef = useRef(activeOverlay);
  activeOverlayRef.current = activeOverlay;

  // 叠加消费：图数据就绪（指纹可用）才应用——keep-alive pane 的查询是懒门控，
  // 用户未到访过图谱 tab 时等图落地后再应用（effect 随 fingerprint 重跑）。
  // chat 通道受「跟随对话」管辖：冻结时不写 consumed——解冻后重跑即应用最新一轮。
  useEffect(() => {
    if (!overlay || !fingerprint) return;
    if (consumedOverlayRef.current === overlay) return;
    if (overlay.source === "chat" && !followChat) return;
    consumedOverlayRef.current = overlay;
    setActiveOverlay({ overlay, fingerprint });
  }, [overlay, fingerprint, followChat]);

  // 指纹漂移（文档增删改 → 图数据变化）→ 旧叠加留在图上就是误导，清除并提示。
  useEffect(() => {
    const current = activeOverlayRef.current;
    if (current && fingerprint && current.fingerprint !== fingerprint) {
      setActiveOverlay(null);
      toast.info(tg.overlayStale);
    }
  }, [fingerprint, tg]);

  /** 可见子图：实体局部图（N 跳邻居）/ 全量。 */
  const visible = useMemo(() => {
    if (!graph) return { nodes: [], edges: [] };
    if (!neighborhood) return { nodes: graph.nodes, edges: graph.edges };
    return filterNeighborhood(
      graph.nodes,
      graph.edges,
      neighborhood.focusId,
      neighborhood.hops,
    );
  }, [graph, neighborhood]);

  /** 局部图模式下社区汇总同步裁剪（hub 层枢纽选择只覆盖可见社区；全局模式全量）。 */
  const visibleCommunities = useMemo(() => {
    if (!graph) return [];
    if (!neighborhood) return graph.communities;
    const visibleCommunityIds = new Set(
      visible.nodes.map((node) => node.community),
    );
    return graph.communities.filter((community) =>
      visibleCommunityIds.has(community.id),
    );
  }, [graph, visible, neighborhood]);

  /** 搜索提交：模糊匹配第一个命中 → 画布升档居中高亮；无命中提示。
      LOD 兜底（2026-09-08）：命中实体在定位档也渲染不出来（>2000 实体熔断 guide
      档 / mention=1 长尾）→ 自动进该实体 1 跳局部图，裁剪后必渲染可居中——即
      guide 档引导文案「放大或双击节点进入局部图」的自动化执行。 */
  const handleSearch = (event: React.FormEvent) => {
    event.preventDefault();
    const [first] = matchEntityNames(visible.nodes, query);
    if (first) {
      if (!isNodeRenderedAtZoom(visible.nodes, visibleCommunities, GRAPH_FOCUS_ZOOM, first)) {
        setNeighborhood({ focusId: first, hops: 1 });
      }
      setFocusNode(first);
    } else if (query.trim()) {
      toast.info(tg.searchNoMatch);
    }
  };

  /** doc_id → 文档名（切片条目的可辨识跳转目标）。 */
  const docNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const doc of documents) map.set(doc.id, doc.name);
    return map;
  }, [documents]);

  /** 社区色映射（2026-09-05 实体抽屉身份卡）：与画布 colorBy=community
      同源同输入（visible 子图 Welsh-Powell）——抽屉社区芯片色点与节点色闭环。 */
  const communityColorMap = useMemo(
    () => buildCommunityColorMap(visible.nodes, visible.edges),
    [visible],
  );

  // 切片位次（2026-09-05）：抽屉打开时拉关联切片的存活位次（与切片抽屉
  // #K 同源同词汇）；关抽屉传 null 不发请求。位次缺失（已删/在拉）行内不显。
  const positionsQuery = useChunkPositions(
    kbId,
    selected ? selected.source_chunk_ids : null,
  );
  const positionByChunkId = positionsQuery?.data?.positions;

  /** 关联切片行排序（2026-09-05）：文档名 → 位次 #K 升序（同文档切片相邻、
      序内有序）；位次未到位/缺失排末尾并保持原相对序（稳定）。 */
  const orderedSourceChunkIds = useMemo(() => {
    if (!selected) return [] as string[];
    const positions = positionByChunkId ?? {};
    return selected.source_chunk_ids
      .map((chunkId, index) => ({ chunkId, index }))
      .sort((a, b) => {
        const docA = docIdOfChunk(a.chunkId);
        const docB = docIdOfChunk(b.chunkId);
        const nameA = docA ? (docNameById.get(docA) ?? "") : "";
        const nameB = docB ? (docNameById.get(docB) ?? "") : "";
        if (nameA !== nameB) return nameA.localeCompare(nameB);
        const posA = positions[a.chunkId] ?? Number.MAX_SAFE_INTEGER;
        const posB = positions[b.chunkId] ?? Number.MAX_SAFE_INTEGER;
        return posA - posB || a.index - b.index;
      })
      .map((entry) => entry.chunkId);
  }, [selected, positionByChunkId, docNameById]);

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="graph-tab">
      {/* 工具栏：实体搜索 + 着色切换 + 图规模统计 */}
      <div className="flex shrink-0 items-center gap-2 border-b px-4 py-2">
        <form className="relative w-40" onSubmit={handleSearch}>
          <Search className="text-muted-foreground absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
          <Input
            aria-label={tg.searchEntities}
            className="h-7 pr-6 pl-7 text-xs"
            placeholder={tg.searchEntities}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </form>
        <ToggleGroup
          aria-label={tg.colorByCommunity}
          size="sm"
          type="single"
          value={colorBy}
          onValueChange={(value) => value && setColorBy(value as GraphColorBy)}
        >
          <ToggleGroupItem
            aria-label={tg.colorByCommunity}
            className="h-7 px-2 text-xs"
            value="community"
          >
            {tg.colorByCommunity}
          </ToggleGroupItem>
          <ToggleGroupItem
            aria-label={tg.colorByType}
            className="h-7 px-2 text-xs"
            value="type"
          >
            {tg.colorByType}
          </ToggleGroupItem>
        </ToggleGroup>
        <div className="ml-auto flex items-center gap-2">
          {/* P4「跟随对话」开关（spec §7）：默认开；关闭后 chat 通道叠加冻结。
              状态与向量空间共享（page 层下发时受控）。 */}
          <label className="text-muted-foreground flex shrink-0 cursor-pointer items-center gap-1.5 text-xs">
            <Switch
              aria-label={tg.followChat}
              checked={followChat}
              className="shrink-0"
              onCheckedChange={setFollowChat}
            />
            <span className="whitespace-nowrap">{tg.followChat}</span>
          </label>
        </div>
      </div>

      {/* 局部图面包屑（实体邻居；返回按钮清模式） */}
      {neighborhood && (
        <div
          className="flex shrink-0 items-center gap-2 border-b px-4 py-1.5"
          data-testid="graph-breadcrumb"
        >
          <Button
            className="h-6 gap-1 px-1.5 text-xs"
            data-testid="graph-breadcrumb-back"
            size="sm"
            variant="ghost"
            onClick={() => {
              setNeighborhood(null);
            }}
          >
            <ChevronLeft className="size-3.5" />
            {tg.backToGlobal}
          </Button>
          <span className="text-xs font-medium">
            {tg.neighborhoodOf(neighborhood.focusId)}
          </span>
          <ToggleGroup
            aria-label={tg.hop1}
            className="ml-auto"
            size="sm"
            type="single"
            value={String(neighborhood.hops)}
            onValueChange={(value) =>
              (value === "1" || value === "2") &&
              setNeighborhood({ ...neighborhood, hops: Number(value) as 1 | 2 })
            }
          >
            <ToggleGroupItem
              aria-label={tg.hop1}
              className="h-6 px-2 text-xs"
              value="1"
            >
              {tg.hop1}
            </ToggleGroupItem>
            <ToggleGroupItem
              aria-label={tg.hop2}
              className="h-6 px-2 text-xs"
              value="2"
            >
              {tg.hop2}
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      )}

      {/* relative 供叠加徽标浮层定位（对齐向量空间徽标模式） */}
      <div className="relative min-h-0 flex-1">
        {graphQuery.isLoading ? (
          <div
            className="text-muted-foreground flex h-full items-center justify-center text-sm"
            data-testid="graph-loading"
          >
            {tg.loading}
          </div>
        ) : graphQuery.isError ? (
          <div
            className="text-muted-foreground flex h-full items-center justify-center text-sm"
            data-testid="graph-error"
          >
            {tg.loadFailed}
          </div>
        ) : !graph || graph.nodes.length === 0 ? (
          <div
            className="text-muted-foreground flex h-full items-center justify-center text-sm"
            data-testid="graph-empty"
          >
            {tg.empty}
          </div>
        ) : (
          <GraphCanvas
            colorBy={colorBy}
            communities={visibleCommunities}
            edges={visible.edges}
            focusNode={focusNode}
            nodes={visible.nodes}
            overlay={activeOverlay?.overlay.trace ?? null}
            onNodeClick={setSelected}
            onNodeDblClick={(node) => {
              setNeighborhood({ focusId: node.id, hops: 1 });
            }}
            onRenderTierChange={setRenderTier}
          />
        )}
        {/* LOD guide 层引导（实体超 2000 熔断）：右上角低调提示。 */}
        {renderTier === "guide" && !neighborhood && (
          <div
            className="bg-background/80 text-muted-foreground absolute top-2 right-2 z-10 max-w-[45%] rounded-full border px-2.5 py-1 text-xs shadow-sm backdrop-blur"
            data-testid="graph-guide-hint"
          >
            {tg.guideHint}
          </div>
        )}
        {/* 叠加徽标：地图式左上浮层——query 文本 + 种子/扩展/证据三层计数 + × 清除。 */}
        {activeOverlay && (
          <div
            className="bg-background/80 absolute top-2 left-2 z-10 flex max-w-[70%] items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs shadow-sm backdrop-blur"
            data-testid="graph-overlay-badge"
          >
            {/* 色点与命中节点同色（红）——徽标是叠加层的图例入口。 */}
            <span
              aria-hidden
              className="size-2 shrink-0 rounded-full"
              style={{ backgroundColor: "#f5222d" }}
            />
            <span
              className="min-w-0 truncate"
              title={activeOverlay.overlay.text}
            >
              {activeOverlay.overlay.text}
            </span>
            <span className="text-muted-foreground shrink-0">
              {tg.overlayLayers(
                activeOverlay.overlay.trace.seed_entities.length,
                activeOverlay.overlay.trace.expanded_nodes.length,
                activeOverlay.overlay.trace.evidence_entities.length,
              )}
            </span>
            <button
              aria-label={tg.clearOverlay}
              className="text-muted-foreground hover:text-foreground ml-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-full"
              type="button"
              onClick={() => setActiveOverlay(null)}
            >
              <X className="size-3" />
            </button>
          </div>
        )}
        {/* 图规模统计：底部居中低调浮层（不占工具栏行宽，与画布视觉中轴对齐）。 */}
        {graph && (
          <span
            className="bg-background/80 text-muted-foreground absolute bottom-2 left-1/2 z-10 -translate-x-1/2 rounded-full border px-2 py-0.5 text-xs whitespace-nowrap shadow-sm backdrop-blur"
            data-testid="graph-stats"
          >
            {tg.stats(
              graph.stats.node_count,
              graph.stats.edge_count,
              graph.stats.community_count,
            )}
          </span>
        )}
      </div>

      {/* 实体详情抽屉：详情 + 关联切片列表 → 跳文档抽屉 */}
      <Sheet
        open={selected !== null}
        onOpenChange={(open) => !open && setSelected(null)}
      >
        <SheetContent
          className="overflow-hidden"
          data-testid="graph-entity-sheet"
          side="right"
        >
          {/* 百科 Tab 容器同款 overlay 滚动条（2026-09-04）：整抽屉经 ScrollArea 滚动；
              原 SheetContent flex gap-4 改由内层 div 承担。 */}
          <ScrollArea
            className="min-h-0 flex-1"
            scrollHideDelay={2000}
            type="scroll"
          >
            {selected && (
              <div className="flex flex-col gap-4">
                <SheetHeader>
                  <SheetTitle>{selected.id}</SheetTitle>
                  {/* sr-only 元数据（项目 Sheet 配方：描述不重复标题，供读屏；
                      视觉信息由下方芯片行承载）。 */}
                  <SheetDescription className="sr-only">
                    {selected.type ? `${selected.type} · ` : ""}
                    {tg.mentions(selected.mention_count)}
                  </SheetDescription>
                  {/* 身份卡芯片行（2026-09-05 裸奔退役）：类型色点与画布节点
                      typeColor 同源，社区色点走画布同一 Welsh-Powell 映射——
                      点什么颜色的节点，抽屉见什么颜色的芯片。 */}
                  <div className="flex flex-wrap items-center gap-1.5">
                    {selected.type && (
                      <Badge className="gap-1.5 text-[10px]" variant="outline">
                        <span
                          aria-hidden
                          className="size-2 rounded-full"
                          style={{ backgroundColor: typeColor(selected.type) }}
                        />
                        {selected.type}
                      </Badge>
                    )}
                    <Badge className="text-[10px] tabular-nums" variant="secondary">
                      {tg.mentions(selected.mention_count)}
                    </Badge>
                    <Badge className="gap-1.5 text-[10px]" variant="outline">
                      <span
                        aria-hidden
                        className="size-2 rounded-full"
                        style={{
                          backgroundColor: communityColor(
                            selected.community,
                            communityColorMap,
                          ),
                        }}
                      />
                      {tg.entityCommunity(selected.community)}
                    </Badge>
                  </div>
                </SheetHeader>
                {/* 描述 = 阅读容器（2026-09-05 二迭代）：项目面板配方 bg-card +
                    border + shadow-xs（bg-muted/40 浅底在米色底上后退、容器感不足，
                    用户实测）；分组头收进卡内（border-b），与检索测试路容器同词汇。 */}
                <div className="px-4">
                  <div className="bg-card text-card-foreground overflow-hidden rounded-lg border shadow-xs">
                    <div className="text-muted-foreground flex items-center gap-1.5 border-b px-3 py-2 text-xs font-medium">
                      <AlignLeft className="size-3.5" />
                      {tg.entityDescription}
                    </div>
                    <p
                      className={cn(
                        "px-3 py-2.5 text-sm leading-relaxed whitespace-pre-wrap",
                        !selected.description && "text-muted-foreground",
                      )}
                    >
                      {selected.description || tg.entityNoDescription}
                    </p>
                  </div>
                </div>
                {/* 关联切片 = 同款容器 + 行解剖（2026-09-05）：计数徽章右对齐
                    （检索测试容器头同款）；行 = 文档名 truncate + 提及序 + chevron，
                    hover 浅底在卡片边界内。裸 chunkId 退役（仅作 key 与跳转参数）。
                    不显 chunk_index：索引时原始序号与切片抽屉的存活位次 #K 在删除
                    空洞时会打架，诚实序号 = 列表内提及序，点击后抽屉自会显示
                    准确 #K。 */}
                <div className="px-4">
                  <div className="bg-card text-card-foreground overflow-hidden rounded-lg border shadow-xs">
                    <div className="text-muted-foreground flex items-center gap-1.5 border-b px-3 py-2 text-xs font-medium">
                      <FileText className="size-3.5" />
                      {tg.relatedChunks}
                      <Badge
                        className="ml-auto text-[10px] tabular-nums"
                        variant="secondary"
                      >
                        {selected.source_chunk_ids.length}
                      </Badge>
                    </div>
                    {selected.source_chunk_ids.length === 0 ? (
                      <p className="text-muted-foreground px-3 py-2.5 text-xs">
                        {tg.entityNoChunks}
                      </p>
                    ) : (
                      <ul className="space-y-0.5 p-1.5">
                        {orderedSourceChunkIds.map((chunkId) => {
                          const docId = docIdOfChunk(chunkId);
                          const docName = docId
                            ? (docNameById.get(docId) ?? tg.unknownDoc)
                            : tg.unknownDoc;
                          const position = positionByChunkId?.[chunkId];
                          return (
                            <li key={chunkId}>
                              <button
                                className="hover:bg-muted/50 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors"
                                data-testid="graph-entity-chunk"
                                type="button"
                                onClick={() => docId && onOpenChunk(docId, chunkId)}
                              >
                                <span className="min-w-0 flex-1 truncate font-medium">
                                  {docName}
                                </span>
                                {/* 位次芯片（2026-09-05）：「提及 i」列表序退役——同文档多行
                                    靠真实位次区分；缺失（已删/在拉）诚实不显。 */}
                                {position != null && (
                                  <span className="text-muted-foreground shrink-0 tabular-nums">
                                    {tr.slicePosition(position)}
                                  </span>
                                )}
                                <ChevronRight className="text-muted-foreground size-3.5 shrink-0" />
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            )}
          </ScrollArea>
        </SheetContent>
      </Sheet>
    </div>
  );
}
