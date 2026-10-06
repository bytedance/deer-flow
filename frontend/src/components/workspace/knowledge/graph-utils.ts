/**
 * 知识图谱可视化的编码纯函数（2026-08-19 spec §5/§6）——独立于 echarts 的
 * 纯数据层，jsdom 可直测，graph-tab / graph-canvas 共用：
 * - nodeSymbolSize：mention_count √开方 → 10–28（抑制长尾）
 * - typeColor / communityColor：FNV-1a 稳定哈希 / 社区邻接图贪心着色（Welsh-Powell）
 * - buildCommunityColorMap：社区 → 色号分配（相邻社区异色优先，耗尽取模回绕）
 * - matchEntityNames：实体搜索模糊匹配
 * - filterNeighborhood：局部图 N 跳 BFS 裁剪
 * - buildGraphSeries / graphTooltipFormatter：echarts option 组装与 tooltip
 */
import type { GraphRetrievalTrace, KnowledgeGraphCommunity, KnowledgeGraphEdge, KnowledgeGraphNode } from "@/core/knowledge/types";

import { buildTooltipHtml } from "./vector-canvas";

/**
 * 节点着色色板（Material Design 400/300 级，与向量空间 SOURCE_COLORS 同色系）。
 * 2026-08-21 扩 20 色（Task 7a 着色治理）：10 色在 80 社区时每色 8 个社区共享，
 * 相邻社区大概率同色。新增 10 色避开命中红 #f5222d / 路径金 #ffd700 / hover 蓝
 * #1677ff 的正色（描边语义色与填充拉开）；red 取 300 粉珊瑚与命中正红拉开明度。
 * type 走 FNV 取模；社区走 buildCommunityColorMap（相邻异色优先）。
 */
export const COMMUNITY_PALETTE: readonly string[] = [
  // ── 原 10 色（400 级，顺序不变）──
  "#42a5f5", // blue 400
  "#66bb6a", // green 400
  "#ffa726", // orange 400
  "#ab47bc", // purple 400
  "#26c6da", // cyan 400
  "#ec407a", // pink 400
  "#9ccc65", // light green 400
  "#ff7043", // deep orange 400
  "#7e57c2", // deep purple 400
  "#8d6e63", // brown 400
  // ── 新增 10 色（300/400 级补色相覆盖）──
  "#e57373", // red 300
  "#5c6bc0", // indigo 400
  "#29b6f6", // light blue 400
  "#26a69a", // teal 400
  "#d4e157", // lime 400
  "#78909c", // blue grey 400
  "#ba68c8", // purple 300
  "#4db6ac", // teal 300
  "#aed581", // light green 300
  "#ffb74d", // orange 300
];

/** FNV-1a 32 位哈希：短字符串稳定着色的经典选择（同 key 跨渲染恒同值）。 */
export function fnv1aHash(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    // hash *= 16777619 的 32 位溢出等价（Math.imul 保低位）。
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** 实体 type → 色板稳定取色。空 type 也走哈希（落固定桶），不特殊置灰。 */
export function typeColor(type: string): string {
  return COMMUNITY_PALETTE[fnv1aHash(type) % COMMUNITY_PALETTE.length]!;
}

/**
 * 社区邻接图贪心着色（Welsh-Powell，2026-08-21 Task 7a）：返回 communityId → 色号。
 * 1. 构建社区邻接图：边两端社区不同 → 两社区相邻（无向；幽灵端点跳过）；
 * 2. 按社区度降序排序（同度按社区 id 升序，保确定性）；
 * 3. 顺序分配「邻居未占用的色号中全局使用次数最少的」（同次数取最小编号）——
 *    相邻异色是硬约束，色号使用均匀是软优化：稀疏图上大量孤立社区（无跨社区
 *    边）若复用最小色号会全撞色号 0（2026-08-21 实测：286 节点/255 边的 JVM 库
 *    八成节点蓝色），均匀分配让颜色自然铺开；色号全被邻居占用时才取模回绕
 *   （撞色也撞在远距离社区，视觉无感）。
 */
export function buildCommunityColorMap(
  nodes: readonly KnowledgeGraphNode[],
  edges: readonly KnowledgeGraphEdge[],
): Map<number, number> {
  const communityOf = new Map<string, number>();
  for (const node of nodes) communityOf.set(node.id, node.community);

  // 孤立社区也入图（度 0），保证返回值覆盖全部社区。
  const neighbors = new Map<number, Set<number>>();
  for (const node of nodes) {
    if (!neighbors.has(node.community)) neighbors.set(node.community, new Set());
  }
  for (const edge of edges) {
    const a = communityOf.get(edge.source);
    const b = communityOf.get(edge.target);
    if (a === undefined || b === undefined || a === b) continue;
    neighbors.get(a)!.add(b);
    neighbors.get(b)!.add(a);
  }

  // Welsh-Powell：度降序，同度按社区 id 升序（同输入恒同输出）。
  const ordered = [...neighbors.keys()].sort((a, b) => {
    const degreeDiff = neighbors.get(b)!.size - neighbors.get(a)!.size;
    return degreeDiff !== 0 ? degreeDiff : a - b;
  });

  const colorMap = new Map<number, number>();
  const usage = new Array<number>(COMMUNITY_PALETTE.length).fill(0);
  for (const community of ordered) {
    const used = new Set<number>();
    for (const neighbor of neighbors.get(community)!) {
      const assigned = colorMap.get(neighbor);
      if (assigned !== undefined) used.add(assigned);
    }
    // 可用色号中取全局使用次数最少的（同次数取最小编号）→ 全图颜色均匀铺开。
    let colorIndex = -1;
    let bestUsage = Infinity;
    for (let i = 0; i < COMMUNITY_PALETTE.length; i += 1) {
      if (used.has(i)) continue;
      if (usage[i]! < bestUsage) {
        bestUsage = usage[i]!;
        colorIndex = i;
      }
    }
    // 邻居占满全色板 → 社区 id 取模回绕（确定性；撞色只发生在远距离社区）。
    if (colorIndex === -1) colorIndex = community % COMMUNITY_PALETTE.length;
    colorMap.set(community, colorIndex);
    usage[colorIndex]! += 1;
  }
  return colorMap;
}

/**
 * 社区 id → 色板取色。传 colorMap（buildCommunityColorMap 产物）时走 Welsh-Powell
 * 分配结果（相邻社区异色）；缺省回退取模（无 colorMap 的兼容路径）。
 */
export function communityColor(community: number, colorMap?: ReadonlyMap<number, number>): string {
  const colorIndex = colorMap?.get(community) ?? community % COMMUNITY_PALETTE.length;
  return COMMUNITY_PALETTE[colorIndex]!;
}

/** 着色模式（spec §6）：默认按社区（结构洞察优先），可切按类型。 */
export type GraphColorBy = "type" | "community";

/** 实体搜索：实体名大小写不敏感子串匹配，返回命中节点 id（保持数据序）。 */
export function matchEntityNames(nodes: readonly KnowledgeGraphNode[], query: string): string[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  return nodes.filter((node) => node.id.toLowerCase().includes(needle)).map((node) => node.id);
}

/**
 * 局部图裁剪（spec §6）：焦点节点 + N 跳邻居（BFS，有向边按无向扩展——对齐
 * graph_search 的邻域语义）。返回裁剪后的节点/边（引用原对象，不复制）。
 */
export function filterNeighborhood(
  nodes: readonly KnowledgeGraphNode[],
  edges: readonly KnowledgeGraphEdge[],
  focusId: string,
  hops: number,
): { nodes: KnowledgeGraphNode[]; edges: KnowledgeGraphEdge[] } {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  if (!byId.has(focusId)) return { nodes: [], edges: [] };
  const kept = new Set<string>([focusId]);
  let frontier = [focusId];
  for (let hop = 0; hop < hops && frontier.length > 0; hop += 1) {
    const next: string[] = [];
    for (const edge of edges) {
      for (const endpoint of [edge.source, edge.target] as const) {
        const other = endpoint === edge.source ? edge.target : edge.source;
        if (frontier.includes(endpoint) && !kept.has(other)) {
          kept.add(other);
          next.push(other);
        }
      }
    }
    frontier = next;
  }
  return {
    nodes: nodes.filter((node) => kept.has(node.id)),
    edges: edges.filter((edge) => kept.has(edge.source) && kept.has(edge.target)),
  };
}

/** 节点尺寸：√count 映射 10–28——mention 长尾被开方压平，巨头不霸屏。 */
export function nodeSymbolSize(mentionCount: number): number {
  if (mentionCount <= 0) return 10;
  return Math.min(28, 10 + 6 * Math.sqrt(mentionCount));
}

// ── 缩放分级标签（2026-08-19 标签密集治理）─────────────────────────────────
// 对齐 Neo4j Bloom / Gephi 惯例：缩略态减标签，避免文字铺满画布遮挡节点，
// 同时释放空白像素给 roam 平移手势（事件路由：命中标签=拖节点，命中空白=平移）。

/** 低于此缩放级别全部隐藏标签（缩略导航态；hover emphasis 仍显示单个）。 */
export const LABEL_ZOOM_HIDE_BELOW = 0.6;
/** 达到此缩放级别全部显示标签（配 labelLayout.hideOverlap 防重叠）。 */
export const LABEL_ZOOM_FULL_ABOVE = 0.9;
/** 中档「重要节点」的 mention 阈值：>= 2 才显示标签。 */
export const IMPORTANT_MENTION_MIN = 2;

export type LabelTier = "hidden" | "important" | "full";

/** 缩放级别 → 标签档位。边界归属：0.6 入中档，0.9 入全显档。 */
export function labelTierForZoom(zoom: number): LabelTier {
  if (zoom < LABEL_ZOOM_HIDE_BELOW) return "hidden";
  if (zoom < LABEL_ZOOM_FULL_ABOVE) return "important";
  return "full";
}

/**
 * tier + 节点 → 标签文本（供 echarts label.formatter 调用）。
 *
 * 用 formatter 而非 setOption data 实现分级（2026-08-19 实测踩坑）：series.data
 * 是整体替换语义，部分字段的 data 会清掉原 datum 的 itemStyle/symbolSize →
 * 全图节点回落默认色板蓝色。formatter 只决定文本，不触碰 data。
 * 返回空串 = 不显示该标签（空标签不参与 labelLayout 计算）。
 */
export function labelTextForTier(
  node: KnowledgeGraphNode | undefined,
  tier: LabelTier,
  fallbackName: string,
): string {
  if (tier === "hidden") return "";
  if (tier === "important" && (node?.mention_count ?? 0) < IMPORTANT_MENTION_MIN) return "";
  return fallbackName;
}

/** hover 高亮描边色（交互蓝）：与命中红 #f5222d / 路径金 #ffd700 同语言异色，
    双主题可读；悬停=临时聚焦，叠加层=持久标记，语义不混。 */
export const GRAPH_HOVER_BORDER_COLOR = "#1677ff";

// ── P4 检索路径叠加（2026-08-19 spec §7，2026-08-20 两层合并重设计）─────────
// 叠加层是诊断镜头，不破坏底图编码：填充色一律保留（类型/社区语义），层语义由
// 描边 + 发光 + 尺寸承载。视觉只分两层（种子与证据数据上高度重叠、hop 层数对
// 调试指导意义低，故合并；徽标仍保留三层数字分解）：
//   命中（种子∪证据）= 红发光描边，种子额外放大（尺寸通道保留源头信号）；
//   路径（hop-1∪hop-2 扩展）= 金细边无发光，与命中路径边同色——金色织出
//   检索路径网络，红色标出路径上的命中要点；非命中节点/边原样（不灰化）。

/** 命中节点描边/发光色（红=命中要点；双主题通用）。 */
export const GRAPH_HIT_BORDER_COLOR = "#f5222d";
/** 路径节点描边色（荧光金，hop-1/hop-2 合并；无发光，视觉权重弱于命中）。 */
export const GRAPH_EXPANSION_BORDER_COLOR = "#ffd700";
/** 种子节点放大倍率（在 mention 基底尺寸上乘算）。 */
export const GRAPH_SEED_SIZE_BOOST = 1.35;
/** 命中/路径描边宽度与发光强度。 */
export const GRAPH_HIT_BORDER_WIDTH = 3;
export const GRAPH_EXPANSION_BORDER_WIDTH = 2;
export const GRAPH_NODE_GLOW_BLUR = 12;
/** 命中路径边：荧光金 + 发光（与路径节点描边同色，路径层一体化）。 */
export const GRAPH_PATH_COLOR = GRAPH_EXPANSION_BORDER_COLOR;
export const GRAPH_PATH_WIDTH = 2;
export const GRAPH_PATH_GLOW_BLUR = 8;

/** series data 里的节点 datum：携带原始 node 供点击钻取回取。 */
export interface GraphDatum {
  name: string;
  symbolSize: number;
  itemStyle: {
    /** 填充恒为自身色（社区/类型）——叠加层绝不覆盖。SuperNode 为空心透明。 */
    color: string;
    /** P4 叠加角色描边（种子红 / 证据金 / hop 橙黄）；SuperNode 主导值色描边。 */
    borderColor?: string;
    borderWidth?: number;
    /** 发光（种子/证据；hop 层不发光）。 */
    shadowColor?: string;
    shadowBlur?: number;
  };
  /** 实体节点载荷（点击钻取链路数据源）。 */
  node: KnowledgeGraphNode;
}

interface GraphLink {
  source: string;
  target: string;
  relation: string;
  description: string;
  lineStyle: {
    curveness: number;
    /** P4 命中路径边：荧光金 + 发光。 */
    color?: string;
    width?: number;
    shadowColor?: string;
    shadowBlur?: number;
  };
}

/** trace → 三层查询表（Set/Map O(1) 判定；null overlay → null 短路）。 */
function overlayLookup(overlay: GraphRetrievalTrace | null | undefined) {
  if (!overlay) return null;
  const seeds = new Set(overlay.seed_entities);
  const hops = new Map(overlay.expanded_nodes.map((node) => [node.name, node.hop]));
  const evidence = new Set(overlay.evidence_entities);
  // 路径边判定用并集：种子 ∪ 扩展 ∪ 证据（等价于 graph_search 的 seen 子图）。
  const all = new Set<string>([...seeds, ...hops.keys(), ...evidence]);
  return { seeds, hops, evidence, all };
}

/**
 * 组装 series data。填充一律保留自身色；命中（种子∪证据）红发光描边，种子
 * 额外放大；路径（hop 扩展）金细边；命中优先于路径。trace 中已不在图里的
 * 实体名自然跳过（陈旧 trace 容错）；未命中节点原样返回（不灰化不描边）。
 */
export function buildGraphData(
  nodes: readonly KnowledgeGraphNode[],
  colorBy: GraphColorBy = "community",
  overlay?: GraphRetrievalTrace | null,
  /** Welsh-Powell 色号分配（buildCommunityColorMap 产物）；缺省时社区色退化为取模。 */
  colorMap?: ReadonlyMap<number, number>,
): GraphDatum[] {
  const lookup = overlayLookup(overlay);
  return nodes.map((node) => {
    const ownColor = colorBy === "community" ? communityColor(node.community, colorMap) : typeColor(node.type);
    const baseSize = nodeSymbolSize(node.mention_count);
    const datum: GraphDatum = { name: node.id, symbolSize: baseSize, itemStyle: { color: ownColor }, node };
    if (!lookup) return datum;
    const isSeed = lookup.seeds.has(node.id);
    const isHit = isSeed || lookup.evidence.has(node.id);
    if (isHit) {
      datum.itemStyle = {
        ...datum.itemStyle,
        borderColor: GRAPH_HIT_BORDER_COLOR,
        borderWidth: GRAPH_HIT_BORDER_WIDTH,
        shadowColor: GRAPH_HIT_BORDER_COLOR,
        shadowBlur: GRAPH_NODE_GLOW_BLUR,
      };
      if (isSeed) {
        datum.symbolSize = Math.round(baseSize * GRAPH_SEED_SIZE_BOOST);
      }
    } else if (lookup.hops.has(node.id)) {
      datum.itemStyle = {
        ...datum.itemStyle,
        borderColor: GRAPH_EXPANSION_BORDER_COLOR,
        borderWidth: GRAPH_EXPANSION_BORDER_WIDTH,
      };
    }
    return datum;
  });
}

/**
 * 组装 series links。命中路径边（两端均在 trace 并集——等价于 graph_search
 * 的 seen 关系子图）荧光金发光；其余边原样（不淡化）。
 */
export function buildGraphLinks(edges: readonly KnowledgeGraphEdge[], overlay?: GraphRetrievalTrace | null): GraphLink[] {
  const lookup = overlayLookup(overlay);
  return edges.map((edge) => {
    const onPath = lookup != null && lookup.all.has(edge.source) && lookup.all.has(edge.target);
    return {
      source: edge.source,
      target: edge.target,
      relation: edge.relation,
      description: edge.description,
      // 双向/多重关系轻微弯曲防重叠（spec §10：并行边不合并，曲率错开）。
      lineStyle: onPath
        ? {
            curveness: 0.1,
            color: GRAPH_PATH_COLOR,
            width: GRAPH_PATH_WIDTH,
            shadowColor: GRAPH_PATH_COLOR,
            shadowBlur: GRAPH_PATH_GLOW_BLUR,
          }
        : { curveness: 0.1 },
    };
  });
}

export interface GraphSeriesConfig {
  type: "graph";
  layout: "force";
  roam: boolean;
  draggable: boolean;
  /** 缩放上下限：防缩放到失控找不到图（不设限时滚轮可无限缩）。 */
  scaleLimit: { min: number; max: number };
  edgeSymbol: [string, string];
  edgeSymbolSize: [number, number];
  force: {
    repulsion: number;
    edgeLength: [number, number];
    gravity: number;
    layoutAnimation: boolean;
  };
  /** hover 高亮（2026-08-20 加法高亮版）：只配当前元素自身的 emphasis 样式。
      不配 focus/blur——echarts states.js 实证：focus:adjacency 下邻接集合仅
      「不被压暗」而非主动高亮（原版邻居高亮=压暗全图的减法错觉，压暗即闪烁
      根因）。邻域提亮由 canvas 层 mouseover 手动 dispatchAction highlight
      实现（当前节点+1 跳邻居同走本样式）；不配 lineStyle，边一律不动。 */
  emphasis: {
    itemStyle: { borderColor: string; borderWidth: number; shadowColor: string; shadowBlur: number };
    /** 关掉 echarts 默认 hover 放大（位置绝对静止）。 */
    scale: boolean;
    focus?: string;
    label?: { show: boolean };
    lineStyle?: { width: number };
  };
  /** hover 状态即时切换（false = 无过渡渐变，快速划过不闪）。 */
  stateAnimation: boolean;
  label: { show: boolean; position: string; fontSize: number };
  /** echarts 5.1+ 内建防重叠：重叠标签自动隐藏（密集区只留稀疏可读标签）。 */
  labelLayout: { hideOverlap: boolean };
  data: GraphDatum[];
  links: GraphLink[];
}

/** graph 系列基础配置（force 参数/交互/emphasis 全系列共用，data/links 各层自填）。 */
function baseSeriesConfig(): Omit<GraphSeriesConfig, "data" | "links"> {
  return {
    type: "graph",
    layout: "force",
    roam: true,
    draggable: true,
    edgeSymbol: ["none", "arrow"],
    edgeSymbolSize: [0, 6],
    force: {
      repulsion: 120,
      edgeLength: [40, 120],
      gravity: 0.1,
      layoutAnimation: true,
    },
    // hover 高亮：交互蓝描边+轻发光（与命中红/路径金同语言异色）。
    // 仅作用于进 emphasis 的元素（当前 hover 节点 + canvas 手动 highlight 的邻居）。
    emphasis: {
      itemStyle: {
        borderColor: GRAPH_HOVER_BORDER_COLOR,
        borderWidth: 3,
        shadowColor: GRAPH_HOVER_BORDER_COLOR,
        shadowBlur: 8,
      },
      scale: false,
    },
    stateAnimation: false,
    label: { show: true, position: "right", fontSize: 11 },
    labelLayout: { hideOverlap: true },
    scaleLimit: { min: 0.3, max: 3 },
  };
}

/**
 * 组装 graph 系列（spec §6：默认按社区着色）。force 参数为 100~500 节点档
 * 调参钉死值：repulsion 120 + edgeLength 40–120 让社区自然成簇，
 * gravity 0.1 防图甩出视口。
 */
export function buildGraphSeries(
  nodes: readonly KnowledgeGraphNode[],
  edges: readonly KnowledgeGraphEdge[],
  colorBy: GraphColorBy = "community",
  overlay?: GraphRetrievalTrace | null,
): [GraphSeriesConfig] {
  return [
    {
      ...baseSeriesConfig(),
      // 社区模式走 Welsh-Powell 色号分配（相邻社区异色）；type 模式 FNV 不需要。
      data: buildGraphData(
        nodes,
        colorBy,
        overlay,
        colorBy === "community" ? buildCommunityColorMap(nodes, edges) : undefined,
      ),
      links: buildGraphLinks(edges, overlay),
    },
  ];
}

/**
 * 邻接表（hover 邻域提亮的数据源）：实体名 → 1 跳邻居名数组。
 * 有向边按无向邻接处理（对齐 filterNeighborhood 的邻域语义）；无边的节点
 * 不产条目。canvas 层在数据重建时刷新 ref，mouseover 时查表 dispatch
 * highlight（echarts 内置 focus:adjacency 只能「不压暗邻居」，加法高亮必须手动）。
 */
export function buildAdjacencyMap(edges: readonly KnowledgeGraphEdge[]): Map<string, string[]> {
  const sets = new Map<string, Set<string>>();
  const ensure = (id: string): Set<string> => {
    let set = sets.get(id);
    if (!set) {
      set = new Set();
      sets.set(id, set);
    }
    return set;
  };
  for (const edge of edges) {
    ensure(edge.source).add(edge.target);
    ensure(edge.target).add(edge.source);
  }
  return new Map([...sets].map(([id, set]) => [id, [...set]]));
}

export interface GraphTooltipParams {
  dataType: "node" | "edge";
  data: Record<string, unknown>;
}

/** tooltip formatter：节点 = 实体名 + 描述截断；边 = s → t 关系 + 描述。 */
export function graphTooltipFormatter(params: GraphTooltipParams): string {
  if (params.dataType === "edge") {
    const data = params.data as { source: string; target: string; relation: string; description?: string };
    // buildTooltipHtml 内部跳过空 preview——空串直传即可。
    return buildTooltipHtml(`${data.source} → ${data.target} · ${data.relation}`, data.description);
  }
  const data = params.data as { name: string; node?: KnowledgeGraphNode };
  return buildTooltipHtml(data.name, data.node?.description);
}

// ── LOD 分层渲染（2026-08-21 Task 7b，对齐 Google Maps 心智模型：缩放 = 地图层级）──
// 数据层（renderTier）与视觉层（labelTier）解耦。2026-08-21 实测裁决：cluster 层
//（SuperNode 聚合）移除——Louvain 稀疏图产出大量微社区（1200 节点→720 社区，减幅
// 仅 ~3x），SuperNode 阵无概览价值；最缩略档直接落 hub。

/** 激活门控：总数 ≤ 500 时 LOD 完全不激活（小库全量渲染零行为变化）。 */
export const LOD_MIN_NODES = 500;
/** zoom < 0.6 → hub（每社区 Top 3 枢纽）。 */
export const LOD_ZOOM_HUB_BELOW = 0.6;
/** zoom ≤ 0.9 → all-important（mention≥2）；> 0.9 → all-full / guide。 */
export const LOD_ZOOM_FULL_ABOVE = 0.9;
/** all-full 硬上限：超出时引导双击进社区局部图（不硬渲全量，防万级节点卡死）。 */
export const LOD_FULL_HARD_LIMIT = 2000;
/** hub 层每社区入选的枢纽数（Top N）。 */
export const LOD_HUB_TOP_PER_COMMUNITY = 3;
/** hub 层节点预算：微社区图上「每社区 Top3」会超出中间层意义（2026-08-21 压测：
    1200 节点 Louvain 产出 720 微社区 → Top3×720=2160）。按社区规模降序累计截断。 */
export const LOD_HUB_NODE_BUDGET = 200;

export type RenderTier = "full" | "hub" | "all-important" | "all-full" | "guide";

/**
 * 缩放 + 节点总数 → 渲染档位。门控优先：totalNodes ≤ LOD_MIN_NODES 恒 full（小库
 * 任何 zoom 走现有全量模式，聚合对小库是丢信息而非优化）。边界归属：0.6 入
 * all-important，> 0.9 才入 all-full；all-full 超 2000 熔断为 guide。
 */
export function renderTierForZoom(zoom: number, totalNodes: number): RenderTier {
  if (totalNodes <= LOD_MIN_NODES) return "full";
  if (zoom < LOD_ZOOM_HUB_BELOW) return "hub";
  if (zoom <= LOD_ZOOM_FULL_ABOVE) return "all-important";
  return totalNodes <= LOD_FULL_HARD_LIMIT ? "all-full" : "guide";
}

/**
 * 搜索定位的目标 zoom（2026-09-08 抽出为常量）：> LOD_ZOOM_FULL_ABOVE，所以
 * 定位档恒为 all-full（≤2000）/ guide（熔断）。tab 层判「命中实体在定位档能否
 * 被渲染」与 canvas 层「升档到哪一档」必须同源，否则两边算出不同答案。
 */
export const GRAPH_FOCUS_ZOOM = 1.6;

/**
 * 首次进入的初始 zoom（2026-08-21 实测修正）：LOD 激活的大库从最缩略档进入
 *（0.3 → hub 层 200 枢纽 + 零标签）——原 zoom=1 会先全量力导向布局 1200 节点
 * 再降载，首次进入卡一下。门控小库恒 zoom=1（full + 全标签，行为不变）。
 */
export function initialZoomForGraph(nodeCount: number): number {
  return nodeCount > LOD_MIN_NODES ? 0.3 : 1;
}

/**
 * tier 的渲染子集（实体 id 集合）；full / all-full 返回 null = 全量不裁剪。
 *
 * 单一源（2026-09-08）：既供 buildTieredSeries 裁数据，也供「命中可达性」判定
 * ——搜索定位必须先知道命中实体在目标档位是否真被渲染，否则画布上没有它可居中。
 */
export function tierNodeIds(
  nodes: readonly KnowledgeGraphNode[],
  communities: readonly KnowledgeGraphCommunity[],
  tier: RenderTier,
): ReadonlySet<string> | null {
  if (tier === "full" || tier === "all-full") return null;

  // hub：每社区 Top N 枢纽（节点预算内按社区规模降序截断——微社区图防爆）；
  // all-important / guide：mention≥2 重要节点。
  const keep = new Set<string>();
  if (tier === "hub") {
    const bySize = [...communities].sort((a, b) => b.memberCount - a.memberCount || a.id - b.id);
    for (const community of bySize) {
      for (const member of community.topMembers.slice(0, LOD_HUB_TOP_PER_COMMUNITY)) {
        if (keep.size >= LOD_HUB_NODE_BUDGET) break;
        keep.add(member.id);
      }
      if (keep.size >= LOD_HUB_NODE_BUDGET) break;
    }
  } else {
    for (const node of nodes) {
      if (node.mention_count >= IMPORTANT_MENTION_MIN) keep.add(node.id);
    }
  }
  return keep;
}

/**
 * 命中可达性：给定 zoom 的渲染档位下该实体是否会被渲染出来（2026-09-08 搜索
 * 定位修复）。缩略档只渲染子集——命中实体不在子集内时，居中/高亮都无从落地，
 * 调用方（graph-tab）据此改走「局部图裁剪」兜底，保证任何库规模都能看见命中。
 */
export function isNodeRenderedAtZoom(
  nodes: readonly KnowledgeGraphNode[],
  communities: readonly KnowledgeGraphCommunity[],
  zoom: number,
  nodeId: string,
): boolean {
  const keep = tierNodeIds(nodes, communities, renderTierForZoom(zoom, nodes.length));
  return keep === null || keep.has(nodeId);
}

/**
 * 分层渲染 series 组装：按 tier 返回对应数据子集。
 * - full / all-full：全量实体（= buildGraphSeries）；
 * - hub：每社区 Top 3 枢纽实体 + 枢纽间原始边；
 * - all-important / guide：mention≥2 重要节点 + 之间边（guide 层内容由 tab 层加引导提示）。
 */
export function buildTieredSeries(
  nodes: readonly KnowledgeGraphNode[],
  edges: readonly KnowledgeGraphEdge[],
  communities: readonly KnowledgeGraphCommunity[],
  tier: RenderTier,
  colorBy: GraphColorBy = "community",
  overlay?: GraphRetrievalTrace | null,
): [GraphSeriesConfig] {
  const keep = tierNodeIds(nodes, communities, tier);
  if (!keep) return buildGraphSeries(nodes, edges, colorBy, overlay);
  const subNodes = nodes.filter((node) => keep.has(node.id));
  const subEdges = edges.filter((edge) => keep.has(edge.source) && keep.has(edge.target));
  return buildGraphSeries(subNodes, subEdges, colorBy, overlay);
}
