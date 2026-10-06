/**
 * Knowledge-base (RAG) types mirroring the Task-8 gateway contract
 * (spec §5.3 / §3.2). Field names stay snake_case to match the API payload
 * exactly — these types are the wire format, not a view model.
 */

export interface KnowledgeBase {
  id: string;
  owner_id: string;
  name: string;
  description: string;
  visibility: "private" | string;
  created_at: string;
}

/** Document status machine (spec §3.6): uploaded → parsing → chunking → indexing → ready / failed. */
export type KnowledgeDocumentStatus = "uploaded" | "parsing" | "chunking" | "indexing" | "ready" | "failed";

// ── P3 per-path sub-status (phase-2 batch-1, spec 2026-08-11 §5) ──────────

/** Vector leg: pending → indexing → done / failed. */
export type VectorPathState = "pending" | "indexing" | "done" | "failed" | string;
/** Graph leg adds "degraded" (partial extraction failure — same verdict source as the "graph degraded" error marker). */
export type GraphPathState = "pending" | "indexing" | "done" | "degraded" | "failed" | string;
/** Wiki leg: a library-level mirror injected at read time — identical for every document of the KB. */
export type WikiPathState = "pending" | "generating" | "ready" | "failed" | string;
/**
 * Video prep legs (spec 2026-09-08 §5): asr / segment / caption. Present only
 * on video documents — text docs write vector/graph alone. Reuses the vector
 * state vocabulary (pending → indexing → done / degraded / failed); `degraded`
 * marks a fallback (segment → fixed windows, caption → >30% shot failures).
 */
export type VideoLegState = "pending" | "indexing" | "done" | "degraded" | "failed" | string;

/** Per-path indexing sub-status persisted on the document row (wiki mirrored library-wide). */
export interface DocumentPathStatus {
  vector: VectorPathState;
  graph: GraphPathState;
  wiki: WikiPathState;
  /** Video prep legs — absent on text documents and legacy rows (spec §5). */
  asr?: VideoLegState;
  segment?: VideoLegState;
  caption?: VideoLegState;
}

export interface KnowledgeDocument {
  id: string;
  kb_id: string;
  uploader_id: string;
  name: string;
  size_bytes: number;
  storage_path: string;
  status: KnowledgeDocumentStatus;
  progress_percent: number;
  /** Null until indexing finished — the table renders "—" (spec §3.6). */
  chunk_count: number | null;
  /** Failure reason; also carries the "graph degraded" marker (spec §3.4). */
  error: string | null;
  /**
   * Per-path sub-status (P3). Null on legacy rows and before the indexing
   * stage — the status cell renders no hover breakdown then (spec §5 兼容).
   */
  path_status: DocumentPathStatus | null;
  /**
   * SHA-256 of the file content (Task 11 duplicate-upload interception).
   * Written at upload time; null on legacy rows (no backfill) — the upload
   * pre-check treats those as "hash unknown" and falls into the conflict
   * branch (replace / keep-both).
   */
  content_hash: string | null;
  created_at: string;
  /**
   * Video-only summary fields (spec 2026-09-08 §5, Task 8): the list endpoint
   * injects `duration_ms` (last shot's end_ms) and `shot_count` once shots are
   * materialized. Absent on text documents and on video rows still mid-pipeline
   * — the table renders the video badge only when at least one is present.
   */
  duration_ms?: number | null;
  shot_count?: number | null;
}

export interface KnowledgeChunk {
  chunk_id: string;
  doc_id: string;
  kb_id: string;
  chunk_index: number;
  text: string;
  heading_path: string[];
  page: number | null;
  token_count: number;
  entities: string[];
  extract_status: "pending" | "done" | "empty" | "failed" | string;
  /** Phase-3 Batch-1 P2: timestamp of last manual text edit (null = never edited). */
  last_edited_at: string | null;
  /**
   * Video shot fields (spec 2026-09-08 §5, Task 10): the chunk list endpoint
   * joins ``video_shots`` for video-shot chunks — ``media="video"``, the shot
   * ordinal, the PTS range (start/end_ms), and the keyframe ``frame_url``
   * (absent when no frame was persisted, spec §2 degradation). Text chunks
   * carry none of these — the drawer renders no video bar for them (零回归).
   */
  media?: "video" | string;
  shot_index?: number;
  start_ms?: number;
  end_ms?: number;
  frame_url?: string;
}

/** Chunk row + source document name (2026-09-05 条目↔切片血缘批量端点)。 */
export interface KnowledgeChunkWithDoc extends KnowledgeChunk {
  doc_name: string | null;
}

export interface KnowledgeChunkPage {
  items: KnowledgeChunk[];
  total: number;
  offset: number;
  limit: number;
}

/** Phase-3 Batch-1 P5: delete impact preview response. */
export interface DeletePreviewResponse {
  orphaned_entities: string[];
  affected_entities: string[];
  relation_deletions: Array<{
    source: string;
    target: string;
    relation: string;
  }>;
}

export interface WikiGenerateAck {
  /** "enqueued" | "already_running" (P1 触发幂等, 2026-08-14: a run is in flight). */
  status: "enqueued" | "already_running" | string;
}

/** Reindex ack (spec 2026-09-14 §5 / P4): the 202 from `POST /{kb_id}/reindex`. */
export interface ReindexAck {
  status: "enqueued" | "already_running" | string;
}

/** Live rebuild counters while `in_progress`; the backend sends `null` when idle. */
export interface ReindexProgress {
  documents_total: number;
  documents_done: number;
  chunks_indexed: number;
  entities_indexed: number;
  wiki_entries_indexed: number;
  cards_indexed: number;
}

/**
 * Library rebuild status (spec 2026-09-14 §5 / P4). `last_run` is the *previous* run's
 * verdict, so an idle entry can still say whether the last rebuild worked.
 */
export interface ReindexStatus {
  in_progress: boolean;
  last_run: "succeeded" | "failed" | string | null;
  progress: ReindexProgress | null;
}

/** Wiki tab list item (phase-2 batch-1): summary-only, no full content. */
export interface WikiEntrySummary {
  id: string;
  title: string;
  summary: string;
  status: "ready" | "dirty" | string;
  updated_at: string;
}

/**
 * Library-level wiki generation run state (wiki 更新状态可见, 2026-08-14).
 * Same source as ``path_status.wiki === "generating"``, exposed on the
 * entries payload so the wiki tab can render 更新中 and poll until done.
 */
export type WikiGenerationState = "idle" | "generating" | string;

/** Wiki entries list payload: summaries + the library-level run flag. */
export interface WikiEntriesPage {
  entries: WikiEntrySummary[];
  generation: WikiGenerationState;
  /**
   * Terminal status of the most recent run (P1 失败可见性, 2026-08-14) —
   * the completion toast keys off it so a crashed run never surfaces as
   * 已更新. ``null`` = never ran in this process.
   */
  last_run: "succeeded" | "failed" | null;
}

/** Full wiki entry, fetched on demand for the entry drawer. */
export interface WikiEntryDetail {
  id: string;
  kb_id: string;
  title: string;
  content: string;
  /** User annotations that survive dirty re-generation (Phase-3 Batch-1 P1). */
  supplement_content: string | null;
  status: "ready" | "dirty" | string;
  source_chunk_ids: string[];
  updated_at: string;
}

// ── Phase-3 Batch-1 P6: manual knowledge cards (spec §8) ──────────────────
// Fully user-managed entries outside the AI wiki lifecycle: never
// auto-regenerated, never disqualified. ``include_in_wiki_search`` opts the
// card into the wiki retrieval path's shared top_k pool (Task 8).

/** Manual card list item: summary-only, no full content (wiki-list pattern). */
export interface ManualCardSummary {
  id: string;
  title: string;
  summary: string;
  tags: string[];
  include_in_wiki_search: boolean;
  created_at: string;
  updated_at: string;
}

export interface ManualCardsPage {
  items: ManualCardSummary[];
  total: number;
  offset: number;
  limit: number;
}

/** Full manual card, fetched on demand for the editor. */
export interface ManualCardDetail {
  id: string;
  kb_id: string;
  owner_id: string;
  title: string;
  content: string;
  tags: string[];
  include_in_wiki_search: boolean;
  created_at: string;
  updated_at: string;
}

/** Citation source carried by the retrieval tools' JSON output (spec §4.6). */
export interface KnowledgeCitation {
  chunk_id: string;
  doc_name: string;
  page: number | null;
  heading_path: string[];
  text: string;
  score: number;
  /**
   * Phase-2 batch-1: filled by the frontend parse layer from the tool name
   * (wiki_search → "wiki", hybrid/graph → "chunk"). Phase-3 P6 (spec §8):
   * wiki_search mixes manual cards into its entries, so a payload-level
   * ``source_type`` wins when present ("manual" for cards). Undefined on
   * legacy citations — render those as "chunk".
   */
  source_type?: "chunk" | "wiki" | "manual";
  /**
   * Backend-assigned citation numbers (rag citation_counter) — INTERNAL
   * handles, never shown to the user. A chunk recalled by multiple paths
   * (hybrid AND graph) carries every number it was assigned; the answer's
   * ``[n]`` marks resolve through these to this card, and the card's sorted
   * strip position becomes the display number actually rendered.
   */
  citation_nos?: number[];
}

// ── P1 recall test (phase-2 batch-1) ─────────────────────────────────────

export interface RecallVectorHit {
  chunk_id: string;
  doc_name: string;
  text: string;
  heading_path: string[];
  page: number | null;
  /** null when the reranker degraded to RRF order (schema deliberately nullable). */
  score: number | null;
  rank: number;
  /** 切片在文档存活切片中的位次（2026-09-05，与切片总览抽屉 #K 同源）；
      畸形/已删 chunk_id 缺键。 */
  chunk_position?: number;
}

export interface RecallGraphEntity {
  name: string;
  type: string;
  description: string;
}

export interface RecallGraphRelation {
  source: string;
  target: string;
  relation: string;
  description: string;
}

export interface RecallGraphEvidence {
  chunk_id: string;
  doc_name: string;
  text: string;
  heading_path: string[];
  page: number | null;
  score: number;
  /** 同 RecallVectorHit.chunk_position（2026-09-05）。 */
  chunk_position?: number;
}

export interface RecallWikiHit {
  entry_id: string;
  title: string;
  summary: string;
  score: number | null;
  rank: number;
  /**
   * Phase-3 P6（spec §8 混排）：wiki 路命中可能是人工卡片。前端据此分流
   * 「条目抽屉 / 卡片抽屉」——卡片 id 走 wiki 详情接口必然 404。缺省回退
   * "wiki"（旧响应形态）。
   */
  source_type?: "wiki" | "manual";
  /**
   * 词条的源切片锚定（2026-08-28 spec §5，Task 5 后端）：仅词条携带，人工卡片
   * （source_type === "manual"）无此键——百科路勾选存题时据此进锚定集。
   */
  source_chunk_ids?: string[];
}

export type RecallPathName = "vector" | "graph" | "wiki";

export interface RecallTestResponse {
  query: string;
  paths: {
    vector: { hits: RecallVectorHit[]; message: string };
    graph: {
      entities: RecallGraphEntity[];
      relations: RecallGraphRelation[];
      evidence: RecallGraphEvidence[];
      message: string;
    };
    wiki: { hits: RecallWikiHit[]; message: string };
  };
  /** Per-path score semantics — never compare scores across paths. */
  score_type: Record<RecallPathName, string>;
  elapsed_ms: Record<RecallPathName, number>;
  /** D4（spec 2026-10-04 §2.4）：库的向量空间与当前配置不一致时为 true；
      缺键=不做声明（一致或未盖章）——查询照常返回，只是质量不保证。 */
  embedding_mismatch?: boolean;
}

/**
 * POST /chunk-positions 批量位次响应（2026-09-05）：chunk_id → 文档存活
 * 切片中的位次（与 recall-test chunk_position / 切片抽屉 #K 同源）；畸形/
 * 已删 id 缺键，前端诚实缺省不显。
 */
export interface ChunkPositionsResponse {
  positions: Record<string, number>;
}

// ── 向量空间可视化（2026-08-15 spec §7：四 collection 同图投影）────────────

/** Point provenance — one per Qdrant collection (spec §3 双编码着色的大类维度). */
export type VectorSourceType = "chunk" | "entity" | "wiki" | "card";

/** Reducer choice; umap requires the optional server-side extra (spec §4). */
export type VectorProjectionAlgo = "pca" | "umap";

/**
 * One projected point. ``z`` only appears for dims=3; ``preview`` is the
 * chunk hover text joined from the business DB (never rides the Qdrant
 * payload); ``heading_path`` / ``doc_name`` accompany chunk points.
 */
export interface VectorProjectionPoint {
  id: string;
  source_type: VectorSourceType | string;
  x: number;
  y: number;
  z?: number;
  label: string;
  /** Coloring rule: doc_id for chunks, entity type for entities, source_type otherwise. */
  color_key: string;
  preview?: string;
  doc_name?: string;
  heading_path?: string[];
}

/** GET /vector-projection — fingerprint-cached projection of the four collections. */
export interface VectorProjectionResponse {
  kb_id: string;
  algo: VectorProjectionAlgo | string;
  dims: 2 | 3;
  model_version: string;
  /** Content digest driving the server-side cache (spec §6). */
  fingerprint: string;
  cached: boolean;
  computed_ms: number;
  total_points: number;
  shown_points: number;
  /** true when chunks were subsampled (only chunks ever are, spec §5). */
  sampled: boolean;
  points: VectorProjectionPoint[];
}

/** POST /vector-projection/query — query text transformed into the cached PCA space. */
export interface VectorProjectionQueryResult {
  x: number;
  y: number;
  z?: number;
  model_version: string;
  /** Matches the projection it was transformed with — staleness check for overlays. */
  fingerprint: string;
}

// ── P6 检索联动叠加（2026-08-15 spec §9 双通道共享）──────────────────────

/**
 * 一个叠加命中点。pointId 即投影点 id：chunk 切片 = chunk_id，wiki = entry_id，
 * card = card_id（citations 解析层把后两者的 id 也填在 chunk_id 字段，天然对齐）。
 */
export interface VectorOverlayHit {
  pointId: string;
  /** null = 该路降级无分（reranker 退化的 RRF 序），色深取中间档。 */
  score: number | null;
}

/**
 * page 层共享的检索叠加请求：recall「在向量空间查看」（显式跳转）与 chat 每轮
 * 自动跟随共用同一形态。text 经 POST /vector-projection/query 投影为落点；
 * hits 驱动命中高亮 / 连线 / score 色深。
 */
export interface VectorRetrievalOverlay {
  source: "recall" | "chat";
  text: string;
  hits: VectorOverlayHit[];
}

// ── 知识图谱可视化（2026-08-19 spec §4 P1）─────────────────────────────

/** GET /graph 的节点：实体名即 id；mention_count = len(source_chunk_ids)。 */
export interface KnowledgeGraphNode {
  id: string;
  type: string;
  description: string;
  mention_count: number;
  /** Louvain 社区 id（0 = 最大社区，规模降序，固定种子保证稳定）。 */
  community: number;
  /** 提及该实体的切片 id（`{doc_id}#%04d`）——实体钻取链路的跳转数据。 */
  source_chunk_ids: string[];
}

/** GET /graph 的边：关系有向（source → target）。 */
export interface KnowledgeGraphEdge {
  source: string;
  target: string;
  relation: string;
  description: string;
}

/** GET /graph 响应的社区汇总项（2026-08-21 Task 7b LOD：SuperNode 聚合数据源）。 */
export interface KnowledgeGraphCommunity {
  id: number;
  memberCount: number;
  totalMentions: number;
  /** 社区内 mention 降序 Top 3（同数按名字典序）。 */
  topMembers: Array<{ id: string; mention_count: number }>;
  /** 主导类型：社区内 mention 总和最高的 type（同数按名字典序）。 */
  dominantType: string;
}

export interface KnowledgeGraphResponse {
  kb_id: string;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  stats: { node_count: number; edge_count: number; community_count: number };
  /** Task 7b：社区级汇总（LOD 分层渲染的 cluster/hub 层数据源）。 */
  communities: KnowledgeGraphCommunity[];
}

// ── P4 graph_search 路径高亮（2026-08-19 spec §7）───────────────────────────

/** graph_search 工具响应透传的检索轨迹（后端 snake_case 原样镜像，零映射成本）。 */
export interface GraphRetrievalTrace {
  /** 种子实体：查询向量命中的 hop-0 实体名。 */
  seed_entities: string[];
  /** 扩展节点：hop ≥ 1 的邻域扩展（hop 信息驱动橙/黄分层染色）。 */
  expanded_nodes: { name: string; hop: number }[];
  /** 证据实体：被选中切片的实体/边来源端点。 */
  evidence_entities: string[];
}

/**
 * page 层共享的图谱叠加请求（对齐 VectorRetrievalOverlay 先例）：chat 每轮
 * 完成含 graph_search 轨迹的对话后上报；图谱 tab 的「跟随对话」开关决定何时
 * 应用（冻结语义在 GraphTab 内）。
 */
export interface GraphRetrievalOverlay {
  source: "chat";
  /** 该轮的可见用户提问文本（徽标展示用）。 */
  text: string;
  trace: GraphRetrievalTrace;
}

// ── Evaluation metrics (spec 2026-08-24 §3.2, plan Task 2) ────────────────

/** Layer 1 per-category metrics（wire format 平铺结构：{summary, fact?, relation?, concept?, global?}）。*/
export type Layer1CategoryKey = "fact" | "relation" | "concept" | "global";

export interface Layer1CategoryMetrics {
  hit_rate: number;
  recall_at_k: number;
  mrr: number;
  path_accuracy: number;
  question_count: number;
}

/** 逐题 L1 slim 指标（layer1_metrics.questions，2026-09-07 题库分诊列）：
    保存时自 runner report 投影的五键；旧运行行无此数组（键缺省）。 */
export interface EvalQuestionMetric {
  id: string;
  /** 参考切片被命中比例（0–1）；无锚定题为 null。 */
  recall: number | null;
  hit: number | null;
  path_correct: boolean;
  actual_path: string | null;
}

/** Layer 1 summary + dynamic category keys from the dataset schema. */
export interface Layer1Metrics {
  summary: Layer1CategoryMetrics;
  fact?: Layer1CategoryMetrics;
  relation?: Layer1CategoryMetrics;
  concept?: Layer1CategoryMetrics;
  global?: Layer1CategoryMetrics;
  /** 逐题 slim 数组（可选：slim 投影落地前的旧运行行无此键）。 */
  questions?: EvalQuestionMetric[];
  /** 该 run 的检索 top_k（列头 @k 具体值数据源，2026-09-07）；旧运行行无此键。 */
  top_k?: number;
}

/** RAGAS standard metrics (RagasReport.aggregate.ragas). */
export interface RagasMetrics {
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
}

/** Architecture-specific metrics (RagasReport.arch_specific). */
export interface ArchSpecificMetrics {
  citation_precision: number | null;
  citation_recall: number | null;
  seed_hit_rate: number | null;
}

/** Baseline comparison diff (wire payload includes per-category gate results). */
export interface BaselineDiff {
  recall_at_k_delta: number | null;
  regression_detected: boolean;
  threshold_percent: number;
  regressed_categories?: string[];
}

/** 逐题最近一次被测结果（latest payload question_results，2026-09-07）：
    跨 run 倒序合并——scoped run 只含子集，列语义是「该题最近一次被测」
    而非「最近一次 run」，跑别的题不会抹掉已出数的题。 */
export interface EvalQuestionResult extends EvalQuestionMetric {
  run_id: string;
  created_at: string;
}

/** MetricsOverview payload for GET /eval-runs/latest (spec §3.2). */
export interface MetricsOverview {
  kb_id: string;
  layer1: {
    run_id: string;
    created_at: string;
    metrics: Layer1Metrics;
    baseline_diff?: BaselineDiff;
  } | null;
  layer2: {
    run_id: string;
    created_at: string;
    ragas_available: boolean;
    ragas_skip_reason?: string;
    ragas: RagasMetrics;
    arch_specific: ArchSpecificMetrics;
    /** 路由命中率（layer2 顶层 path_accuracy 换展示面键名；总览瓦片数据源）。 */
    routing_hit_rate: number | null;
    langfuse_trace_url?: string;
    has_graph_questions: boolean;
  } | null;
  /** 逐题最近结果（跨 run 合并）；旧网关无此键时列全 —。 */
  question_results?: EvalQuestionResult[];
}

// ── Evaluation trend (spec 2026-08-24 §4.1, plan Task 3) ─────────────────

/**
 * 趋势图单个数据点（contract v4，spec 2026-09-07 §2）：一个点 = 一次真实
 * 运行，不做周期分桶——同日多次运行各自出点，时间连续性由 time 轴承载。
 */
export interface TrendPoint {
  /** 运行真实时间戳（ISO8601 含 +00:00 偏移，coerce_iso 归一化）。 */
  ts: string;
  /** Layer 1（该层该周期无数据则 null）。 */
  recall_at_k: number | null;
  hit_rate: number | null;
  mrr: number | null;
  /** Layer 1 路径命中率（picker 候选；确定性，取 summary.path_accuracy）。 */
  path_accuracy: number | null;
  /** Layer 2 RAGAS（同粒度，独立取数）。 */
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  /** Layer 2 引用与图谱（arch_specific；稀疏——仅完整档产出，picker 候选）。 */
  citation_precision: number | null;
  citation_recall: number | null;
  seed_hit_rate: number | null;
  /** 路由命中率（layer2 顶层 path_accuracy；真实对话链路选路口径，与 L1
   *  同名键不同源；稀疏——仅完整档产出，picker 候选）。 */
  routing_hit_rate: number | null;
  /** 下钻来源行：点与 run 一一对应（两层同源一行，contract v4 单键）。 */
  run_id: string;
  /** 该点运行的门禁判定（透传其 baseline_diff）；无 diff 为 null。 */
  regression: { detected: boolean; categories: string[] } | null;
  /** 该点运行是否被 --mark-baseline 标记。 */
  is_baseline_update: boolean;
}

/**
 * sparkline 的 8 个 Layer 2 指标键（RAGAS 4 + 引用 3 + 路由命中率，含退役的
 * context_recall）。与后端 trend.py::SPARK_KEYS 一一对应（spec §6.2 冻结）。
 */
export type SparkMetricKey =
  | "faithfulness"
  | "answer_relevancy"
  | "context_precision"
  | "context_recall"
  | "citation_precision"
  | "citation_recall"
  | "seed_hit_rate"
  | "routing_hit_rate";

/** 趋势图 API 响应（GET /eval-runs/trend，contract v4）。 */
export interface TrendResponse {
  points: TrendPoint[];
  /** 当前 baseline；无 baseline 行时为 null（前端不画阈值线）。 */
  baseline: {
    recall_at_k: number;
    /** DEFAULT_FAIL_THRESHOLD * 100，与 CI 门禁同源。 */
    threshold_percent: number;
  } | null;
  /** 固定近 90 天窗口内是否有数据（任一层有即为 true）。 */
  has_data: boolean;
  /**
   * 8 个 Layer 2 瓦片的 sparkline 数据源：每键一条 run 级近 10 非空值升序数组。
   * 与趋势固定窗口解耦（spec §6.2）；某键全 null（如 ragas 未装）→ 空数组。
   */
  sparks: Record<SparkMetricKey, number[]>;
}

/**
 * 趋势图 i18n 文案包（canvas 组件纯渲染不调 useI18n——文案经 props 注入，
 * spec §3.6）。eval-tab 从 tk.eval.* 组装。
 */
export interface TrendChartLabels {
  /** 6 条指标线的显示名（图例 + tooltip）。 */
  recallAtK: string;
  hitRate: string;
  mrr: string;
  faithfulness: string;
  answerRelevancy: string;
  contextPrecision: string;
  /** 5 条 picker 稀疏指标线显示名（复用总览卡/表格同名，词汇闭环；仅 tooltip，不进图例）。 */
  pathAccuracy: string;
  citationPrecision: string;
  citationRecall: string;
  seedHitRate: string;
  routingHitRate: string;
  /** 阈值线名（markLine series 名）。 */
  thresholdLine: string;
  /** 阈值线标签（markLine formatter，含阈值百分数）。 */
  thresholdLabel: (thresholdPercent: number) => string;
  /** 基线更新竖线标签。 */
  baselineUpdate: string;
  /** tooltip 底部点击提示。 */
  clickForDetail: string;
  /** tooltip 中回退 category 列表前缀。 */
  regressionPrefix: string;
  /** tooltip 哑行：所选 picker 指标在该档未跑（null）。 */
  notRunInTier: string;
}

/** 单次运行详情（GET /eval-runs/{run_id}，drawer 数据源）。 */
export interface EvalRunDetail {
  run_id: string;
  kb_id: string;
  status: "completed" | "error" | "skipped" | "cancelled";
  environment: "local" | "ci" | "nightly";
  created_at: string;
  layer1_metrics: Layer1Metrics | Record<string, never>;
  layer2_metrics: {
    ragas_available: boolean;
    ragas_skip_reason?: string;
    ragas: RagasMetrics;
    arch_specific: ArchSpecificMetrics;
    langfuse_trace_url?: string;
    has_graph_questions: boolean;
    /** Layer 2 的 path_accuracy（真实对话链路选路准确率，与 Layer 1 同名指标口径不同）。 */
    path_accuracy?: number | null;
  } | Record<string, never>;
  baseline_diff?: BaselineDiff;
  is_baseline: boolean;
}

// ── Eval question bank & run history (spec 2026-08-27 §4–§6, plan Task 4) ──

/** Golden 考题（GET / POST /eval/questions 的行对象）。 */
export interface EvalQuestion {
  /** 服务端生成（q_<hex8>），客户端不可携带。 */
  id: string;
  query: string;
  category: "fact" | "relation" | "concept" | "global";
  /** 预期路径集合（2026-08-28 spec §3，Task 4 切换）：1–3 路，任一路承担即对。 */
  expected_paths: RecallPathName[];
  /** 空数组 = 无锚定题（Layer 1 仅参与路径判定，spec §1 事实 2）。 */
  relevant_chunk_ids: string[];
  relevant_entities: string[];
  reference_answer: string | null;
  /**
   * 悬空锚（2026-10-06 改锚对，spec §2②）：`relevant_chunk_ids` 里在该库
   * `chunks` 表已不存在的切片 id（重切片序号移位 / 切片被删）。响应派生
   * 字段——读时计算、不落盘、**不进 golden.jsonl**；旧网关无此键（缺省
   * = 不做声明），行级「悬空」徽章只在非空时渲染。
   */
  missing_chunk_ids?: string[];
  /**
   * 落空（2026-10-06 改锚对 Task 5，spec §2④）：锚在、参考答案词面已对不上
   * （切片内容被换 / 贴错锚），读时派生、不落盘。null/缺省 = 无警示；悬空
   * 优先——有缺片时为 null（一题至多显一类警示）。
   */
  anchor_mismatch?: AnchorMismatchInfo | null;
}

/** POST /eval/questions 请求体：锚定字段缺省即空数组。 */
export interface EvalQuestionCreateInput {
  query: string;
  category: "fact" | "relation" | "concept" | "global";
  /** 至少一路（后端 min_length=1），最多三路。 */
  expected_paths: RecallPathName[];
  relevant_chunk_ids?: string[];
  relevant_entities?: string[];
  reference_answer?: string | null;
  /** B′ 锚定确认（2026-10-05）：机器核验拦截后的「仍要入库」覆盖开关，缺省 false。 */
  anchor_ack?: boolean;
}

/**
 * PATCH /eval/questions/{id} 请求体（2026-10-06 改锚对，spec §2③）：**只动锚**
 * （relevant_chunk_ids；实体由服务端跟锚收缩，题面/分类/路径/参考答案不动）。
 * 清空数组 = 解除锚定（合法）。anchor_ack 同 B′ 口径：原「保存」永不携带
 * （请求体不带该键），仅红块内「仍要保存」置 true；missing_chunk 不可覆盖。
 */
export interface EvalQuestionUpdateInput {
  relevant_chunk_ids: string[];
  anchor_ack?: boolean;
}

/**
 * 锚定核验拦截的结构化 422 detail（B′，2026-10-05）：detail 是对象（普通
 * 错误的 detail 是字符串），携带机器证据——缺失术语、建议锚与命中计数。
 * missing_chunk（锚定切片已不存在）不可被 anchor_ack 覆盖。
 */
export interface AnchorBlockDetail {
  reason: "mismatch" | "zero_hit" | "missing_chunk";
  miss_terms: string[];
  /** 命中计数（参考答案在锚定切片上的命中数）。 */
  hits: number;
  /** 文档内最佳切片的命中数（对照基准）。 */
  best_hits: number;
  suggested_chunk: string | null;
}

/**
 * 落空派生明细（2026-10-06 Task 5，spec §2④）：红块同款机器依据 + 疑片集
 * （`chunk_ids` = 抽屉行级「存疑」落点；reason 只会是 zero_hit/mismatch）。
 */
export interface AnchorMismatchInfo extends AnchorBlockDetail {
  chunk_ids: string[];
}

/** GET /eval/questions 响应：全量题库（50–100 题规模，无分页）。 */
export interface EvalQuestionListResponse {
  questions: EvalQuestion[];
  total: number;
}

// ── Question synthesis（2026-08-28 spec §6，Task 6–8）─────────────────────

/** 候选题（暂存行）：完整题目载荷 + 暂存元数据；采纳后换服务端 q_ id 入题库。 */
export interface SynthesisCandidate {
  candidate_id: string;
  query: string;
  category: "fact" | "relation" | "concept" | "global";
  expected_paths: RecallPathName[];
  relevant_chunk_ids: string[];
  relevant_entities: string[];
  reference_answer: string | null;
  doc_id: string;
  generated_at: string;
}

/** GET /eval/questions/synthesize：in_progress + 暂存候选 + 合成元数据。 */
export interface SynthesisStatus {
  in_progress: boolean;
  candidates: SynthesisCandidate[];
  generated_at: string | null;
  /** 本轮合成的来源文档（多篇联合出题，2026-09-02）。 */
  doc_ids: string[];
  dropped: number;
}

/** POST /eval/questions/synthesize 触发体：一到多篇文档（联合出题）+ 候选题数（1–10）。 */
export interface SynthesisTriggerInput {
  doc_ids: string[];
  count: number;
}

/** 202 应答：与评测触发同形（enqueued / already_running）。 */
export interface SynthesisTriggerResponse {
  status: "enqueued" | "already_running";
}

/** 采纳候选的 mutation 入参（B′，2026-10-05）：anchor_ack 真值时请求体带
 *  {"anchor_ack": true}；缺省保持无请求体（旧契约兼容）。 */
export interface SynthesisAcceptInput {
  candidate_id: string;
  anchor_ack?: boolean;
}

/** 历史列表行（轻量摘要，指标本体留在 drawer 详情里）。 */
export interface EvalRunSummary {
  run_id: string;
  created_at: string | null;
  completed_at: string | null;
  environment: "local" | "ci" | "nightly";
  /** cancelled = 用户终止（spec 2026-09-06 §11）；读集只认 completed，历史行是唯一曝光面。 */
  status: "completed" | "error" | "skipped" | "cancelled";
  is_baseline: boolean;
  has_layer1: boolean;
  has_layer2: boolean;
  regression_detected: boolean;
  langfuse_trace_url: string | null;
}

/** 进度事件（spec 2026-09-06 §9）：后端只出结构化事件，单行日志的文案由 i18n 渲染。 */
export interface EvalProgressTail {
  kind: "phase" | "item" | "fail";
  phase: "layer1" | "questions" | "ragas";
  done: number;
  total: number;
  failed: number;
}

/** 运行中评测的活进度快照（spec 2026-09-06 run-progress §3 七键 + §9 扩三键，后端恒透出十键）。
 *  phase 三段均定长：questions 按题推进，ragas 段按 (样本×指标) job + 逐题 citation judge。 */
export interface EvalRunProgress {
  run_id: string;
  phase: "layer1" | "questions" | "ragas";
  done: number;
  total: number;
  failed: number;
  started_at: string;
  updated_at: string;
  /** 本阶段起点（毫秒级 ISO）；ETA 速率外推的分母。旧形状条目由后端回退为 started_at。 */
  phase_started_at?: string | null;
  /** 已完成阶段的实测耗时（秒）——加权进度条自适应跨度的数据源。 */
  phase_durations?: Partial<Record<"layer1" | "questions" | "ragas", number>>;
  /** 最新一条进度事件（单行实时日志的源）。 */
  tail?: EvalProgressTail | null;
}

/** GET /eval-runs 响应（spec §6.1）：顶层 in_flight 驱动轮询与工具栏状态。 */
export interface EvalRunListResponse {
  in_flight: boolean;
  /** 活进度快照（spec 2026-09-06 run-progress）：非 in_flight 时为 null。 */
  progress?: EvalRunProgress | null;
  runs: EvalRunSummary[];
  /** include_ci 过滤后的全量行数（不是本页行数）。 */
  total: number;
}

/** POST /eval-runs 请求载荷（2026-09-01 B 方案）：``layers`` 缺省 ``l1``（快速档），
 * ``l1_l2`` 为完整档（单行双层指标）；``question_ids`` 选题运行，缺省全量。 */
export interface EvalTriggerInput {
  layers?: "l1" | "l1_l2";
  question_ids?: string[];
}

/** POST /eval-runs 202 响应（wiki generate 幂等同款）。 */
export interface EvalTriggerResponse {
  status: "enqueued" | "already_running";
}

/** POST /eval-runs/cancel 202 响应（spec 2026-09-06 §11；409 = 无在飞 run）。 */
export interface EvalCancelResponse {
  status: "cancelled";
}

/** DELETE /eval-runs 响应（2026-09-08 历史删除）：实际删除行数
 * （他库/不存在的 id 不计入）。 */
export interface EvalRunDeleteResponse {
  deleted: number;
}
