/**
 * REST client for the knowledge-base management API (spec §5.3).
 * Follows the `core/memory/api.ts` pattern: the shared fetcher owns CSRF +
 * credentials + 401 redirect; this module owns paths, bodies, and error
 * detail surfacing.
 */
import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

import type {
  AnchorBlockDetail,
  ChunkPositionsResponse,
  DeletePreviewResponse,
  EvalCancelResponse,
  EvalQuestion,
  EvalQuestionCreateInput,
  EvalQuestionListResponse,
  EvalQuestionUpdateInput,
  EvalRunDeleteResponse,
  EvalRunDetail,
  EvalRunListResponse,
  EvalTriggerInput,
  EvalTriggerResponse,
  KnowledgeBase,
  KnowledgeChunk,
  KnowledgeChunkPage,
  KnowledgeDocument,
  KnowledgeGraphResponse,
  ManualCardDetail,
  ManualCardsPage,
  MetricsOverview,
  RecallTestResponse,
  ReindexAck,
  ReindexStatus,
  SynthesisStatus,
  SynthesisTriggerInput,
  SynthesisTriggerResponse,
  TrendResponse,
  VectorProjectionAlgo,
  VectorProjectionQueryResult,
  VectorProjectionResponse,
  WikiEntriesPage,
  KnowledgeChunkWithDoc,
  WikiEntryDetail,
  WikiGenerateAck,
} from "./types";

function formatErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const record = item as Record<string, unknown>;
          if (typeof record.msg === "string") return record.msg;
        }
        return null;
      })
      .filter(Boolean);
    return parts.length > 0 ? parts.join("; ") : null;
  }
  return null;
}

/**
 * 锚定核验拦截（B′，2026-10-05）：后端 422 的 detail 是**对象**（普通错误是
 * 字符串），携带机器证据。命中该形状时抛本类型，由 useAnchorConfirm 转成
 * 红块内联确认（「仍要入库/仍要接受」）；普通错误保持既有 Error + toast 路径。
 */
export class AnchorBlockError extends Error {
  readonly detail: AnchorBlockDetail;

  constructor(detail: AnchorBlockDetail) {
    super(`anchor check failed: ${detail.reason}`);
    this.name = "AnchorBlockError";
    this.detail = detail;
  }
}

/** 仅认结构化锚定 detail（对象 + reason 枚举 + miss_terms 数组）；其余 null。 */
function parseAnchorBlockDetail(detail: unknown): AnchorBlockDetail | null {
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const record = detail as Record<string, unknown>;
  const reason = record.reason;
  if (reason !== "mismatch" && reason !== "zero_hit" && reason !== "missing_chunk") return null;
  const missTerms = record.miss_terms;
  if (!Array.isArray(missTerms) || !missTerms.every((term) => typeof term === "string")) return null;
  return {
    reason,
    miss_terms: [...missTerms],
    hits: typeof record.hits === "number" ? record.hits : 0,
    best_hits: typeof record.best_hits === "number" ? record.best_hits : 0,
    suggested_chunk: typeof record.suggested_chunk === "string" ? record.suggested_chunk : null,
  };
}

function buildResponseError(response: Response, detail: unknown, fallbackMessage: string): Error {
  // 锚定核验专属形态：422 + 结构化 detail；普通字符串 detail 的 422 走旧路径。
  if (response.status === 422) {
    const anchorDetail = parseAnchorBlockDetail(detail);
    if (anchorDetail !== null) {
      return new AnchorBlockError(anchorDetail);
    }
  }
  const detailMessage = formatErrorDetail(detail);
  return new Error(detailMessage ?? `${fallbackMessage}: ${response.statusText}`);
}

async function readResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw buildResponseError(response, errorData.detail, fallbackMessage);
  }
  return response.json() as Promise<T>;
}

async function readEmptyResponse(response: Response, fallbackMessage: string): Promise<void> {
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw buildResponseError(response, errorData.detail, fallbackMessage);
  }
}

function kbUrl(kbId: string, suffix = ""): string {
  return `${getBackendBaseURL()}/api/knowledge-bases/${encodeURIComponent(kbId)}${suffix}`;
}

export function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  return fetch(`${getBackendBaseURL()}/api/knowledge-bases`).then((r) =>
    readResponse<KnowledgeBase[]>(r, "Failed to fetch knowledge bases"),
  );
}

/** Upload allowlist (Task 6, spec §6) — static data, cached indefinitely. */
export function getSupportedFormats(): Promise<{ suffixes: string[] }> {
  return fetch(`${getBackendBaseURL()}/api/knowledge-bases/supported-formats`).then((r) =>
    readResponse<{ suffixes: string[] }>(r, "Failed to fetch supported formats"),
  );
}

export function createKnowledgeBase(input: { name: string; description?: string }): Promise<KnowledgeBase> {
  return fetch(`${getBackendBaseURL()}/api/knowledge-bases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: input.name, description: input.description ?? "" }),
  }).then((r) => readResponse<KnowledgeBase>(r, "Failed to create knowledge base"));
}

export function getKnowledgeBase(kbId: string): Promise<KnowledgeBase> {
  return fetch(kbUrl(kbId)).then((r) => readResponse<KnowledgeBase>(r, "Failed to fetch knowledge base"));
}

export function updateKnowledgeBase(
  kbId: string,
  patch: { name?: string; description?: string },
): Promise<KnowledgeBase> {
  return fetch(kbUrl(kbId), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  }).then((r) => readResponse<KnowledgeBase>(r, "Failed to update knowledge base"));
}

export async function deleteKnowledgeBase(kbId: string): Promise<void> {
  const response = await fetch(kbUrl(kbId), { method: "DELETE" });
  return readEmptyResponse(response, "Failed to delete knowledge base");
}

/** GET /graph — 知识图谱可视化（2026-08-19 spec §4）：全量实体/关系 + 社区标注。 */
export function getKnowledgeGraph(kbId: string): Promise<KnowledgeGraphResponse> {
  return fetch(kbUrl(kbId, "/graph")).then((r) => readResponse<KnowledgeGraphResponse>(r, "Failed to fetch knowledge graph"));
}

export function listDocuments(kbId: string): Promise<KnowledgeDocument[]> {
  return fetch(kbUrl(kbId, "/documents")).then((r) =>
    readResponse<KnowledgeDocument[]>(r, "Failed to fetch documents"),
  );
}

export function uploadDocument(kbId: string, file: File): Promise<KnowledgeDocument> {
  const body = new FormData();
  body.append("file", file, file.name);
  // No explicit Content-Type: fetch must compose the multipart boundary.
  return fetch(kbUrl(kbId, "/documents"), { method: "POST", body }).then((r) =>
    readResponse<KnowledgeDocument>(r, "Failed to upload document"),
  );
}

export async function deleteDocument(kbId: string, docId: string): Promise<void> {
  const response = await fetch(kbUrl(kbId, `/documents/${encodeURIComponent(docId)}`), {
    method: "DELETE",
  });
  return readEmptyResponse(response, "Failed to delete document");
}

export function retryDocument(kbId: string, docId: string): Promise<KnowledgeDocument> {
  return fetch(kbUrl(kbId, `/documents/${encodeURIComponent(docId)}/retry`), {
    method: "POST",
  }).then((r) => readResponse<KnowledgeDocument>(r, "Failed to retry document"));
}

export function listDocumentChunks(
  kbId: string,
  docId: string,
  page: { offset: number; limit: number },
): Promise<KnowledgeChunkPage> {
  const params = new URLSearchParams({
    offset: String(page.offset),
    limit: String(page.limit),
  });
  return fetch(kbUrl(kbId, `/documents/${encodeURIComponent(docId)}/chunks?${params}`)).then((r) =>
    readResponse<KnowledgeChunkPage>(r, "Failed to fetch chunks"),
  );
}

/**
 * Entry↔chunk lineage (2026-09-05): batch-fetch chunks by id in the requested
 * order, each carrying its source document name. Unknown ids drop server-side
 * (deleted chunks); the caller reports the count delta.
 */
export async function listChunksByIds(kbId: string, ids: string[]): Promise<KnowledgeChunkWithDoc[]> {
  const params = new URLSearchParams(ids.map((id) => ["ids", id]));
  const body = await fetch(kbUrl(kbId, `/chunks?${params}`)).then((r) =>
    readResponse<{ items: KnowledgeChunkWithDoc[] }>(r, "Failed to fetch chunks"),
  );
  return body.items;
}

/**
 * URL of a parser-extracted document asset (chunk markdown references
 * `images/…`; the gateway serves them from the document directory).
 * Pure URL builder for <img src> — never goes through the CSRF fetcher.
 */
export function documentFileUrl(kbId: string, docId: string, ref: string): string {
  const encodedRef = ref.split("/").map(encodeURIComponent).join("/");
  return kbUrl(kbId, `/documents/${encodeURIComponent(docId)}/files/${encodedRef}`);
}

/**
 * URL of the persisted source file (2026-09-10 round-trip export): the gateway
 * serves the upload bytes with ``Content-Disposition: attachment`` under the
 * stored name. Pure URL builder — cookie-authed GET, never through the CSRF
 * fetcher (same family as ``documentFileUrl``).
 */
export function documentSourceUrl(kbId: string, docId: string): string {
  return kbUrl(kbId, `/documents/${encodeURIComponent(docId)}/source`);
}

/**
 * Trigger a browser download of the document's source file (2026-09-10): a
 * programmatic anchor over {@link documentSourceUrl}; the saved filename comes
 * from the response's Content-Disposition, so the anchor needs no own name.
 */
export function downloadDocumentSource(kbId: string, docId: string): void {
  const anchor = document.createElement("a");
  anchor.href = documentSourceUrl(kbId, docId);
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

/**
 * URL of a video shot's persisted keyframe (spec 2026-09-08 §4/§5, Task 10):
 * the chunk drawer's thumbnail <img src>. Mirrors ``documentFileUrl`` — a pure
 * URL builder over the same gateway prefix, never through the CSRF fetcher.
 * The chunk payload's ``frame_url`` is the base-relative form; this rebuilds it
 * with ``getBackendBaseURL()`` so it resolves identically across deployments.
 */
export function shotFrameUrl(kbId: string, docId: string, shotIndex: number): string {
  return kbUrl(kbId, `/documents/${encodeURIComponent(docId)}/shots/${shotIndex}/frame`);
}

/**
 * Absolute URL of a document's source video for the chunk drawer's inline
 * ``<video>`` player (spec 2026-09-08 §5, Task 10b). The endpoint negotiates
 * HTTP Range, so seeking streams only the needed bytes rather than the whole
 * file. Plain ``<video src>`` — not fetched through the CSRF wrapper.
 */
export function videoStreamUrl(kbId: string, docId: string): string {
  return kbUrl(kbId, `/documents/${encodeURIComponent(docId)}/video/stream`);
}

export type WikiGenerateMode = "incremental" | "full";

export function generateWiki(kbId: string, mode: WikiGenerateMode = "incremental"): Promise<WikiGenerateAck> {
  return fetch(kbUrl(kbId, `/wiki/generate?mode=${mode}`), { method: "POST" }).then((r) =>
    readResponse<WikiGenerateAck>(r, "Failed to trigger wiki generation"),
  );
}

/**
 * 重建索引（spec 2026-09-14 §5 / P4）：把库里现有切片重新嵌入一次，**不重解析**。
 * 换嵌入 provider / 维度之后的唯一出口——没有它，「拒绝启用非 1024 维」就是死胡同。
 */
export function reindexKnowledgeBase(kbId: string): Promise<ReindexAck> {
  return fetch(kbUrl(kbId, "/reindex"), { method: "POST" }).then((r) =>
    readResponse<ReindexAck>(r, "Failed to trigger knowledge-base reindex"),
  );
}

/** 重建进度（设置页轮询）：`in_progress` 为假时 `progress` 为 null，`last_run` 是上一轮结论。 */
export function getReindexStatus(kbId: string): Promise<ReindexStatus> {
  return fetch(kbUrl(kbId, "/reindex/status")).then((r) =>
    readResponse<ReindexStatus>(r, "Failed to fetch reindex status"),
  );
}

/**
 * 局部更新/重建（2026-09-02）：重生成手选的百科条目（按各自实体的当前切片
 * 重跑 LLM）。单条更新与单条重建在后端是同一操作，故共用此端点；返回与
 * ``generateWiki`` 相同的 202 ack（enqueued / already_running，与库级生成互斥）。
 */
export function regenerateWikiEntries(kbId: string, entryIds: string[]): Promise<WikiGenerateAck> {
  return fetch(kbUrl(kbId, "/wiki/regenerate"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entry_ids: entryIds }),
  }).then((r) => readResponse<WikiGenerateAck>(r, "Failed to regenerate wiki entries"));
}

export function listWikiEntries(kbId: string): Promise<WikiEntriesPage> {
  return fetch(kbUrl(kbId, "/wiki/entries")).then((r) =>
    readResponse<WikiEntriesPage>(r, "Failed to fetch wiki entries"),
  );
}

export function getWikiEntry(kbId: string, entryId: string): Promise<WikiEntryDetail> {
  return fetch(kbUrl(kbId, `/wiki/entries/${encodeURIComponent(entryId)}`)).then((r) =>
    readResponse<WikiEntryDetail>(r, "Failed to fetch wiki entry"),
  );
}

export async function deleteWikiEntry(kbId: string, entryId: string): Promise<void> {
  const response = await fetch(kbUrl(kbId, `/wiki/entries/${encodeURIComponent(entryId)}`), {
    method: "DELETE",
  });
  return readEmptyResponse(response, "Failed to delete wiki entry");
}

/** Phase-3 Batch-1 P1: update wiki entry content and supplement layer. */
export async function updateWikiEntry(
  kbId: string,
  entryId: string,
  body: { content: string; supplement_content: string | null },
): Promise<WikiEntryDetail> {
  const response = await fetch(kbUrl(kbId, `/wiki/entries/${encodeURIComponent(entryId)}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<WikiEntryDetail>(response, "Failed to update wiki entry");
}

/** Task 5 收尾: delete one chunk (full cascade server-side: graph/wiki/vector/row). */
export async function deleteChunk(kbId: string, chunkId: string): Promise<void> {
  const response = await fetch(kbUrl(kbId, `/chunks/${encodeURIComponent(chunkId)}`), {
    method: "DELETE",
  });
  return readEmptyResponse(response, "Failed to delete chunk");
}

/** Phase-3 Batch-1 P2: update chunk text with re-embedding. */
export async function updateChunk(
  kbId: string,
  chunkId: string,
  body: { text: string },
): Promise<KnowledgeChunk> {
  const response = await fetch(kbUrl(kbId, `/chunks/${encodeURIComponent(chunkId)}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<KnowledgeChunk>(response, "Failed to update chunk");
}

/** Phase-3 Batch-1 P5: preview chunk deletion impact (dry-run). */
export async function previewChunkDeletion(
  kbId: string,
  body: { chunk_ids: string[] },
): Promise<DeletePreviewResponse> {
  const response = await fetch(kbUrl(kbId, "/chunks/delete-preview"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<DeletePreviewResponse>(response, "Failed to preview chunk deletion");
}

/** Phase-3 Batch-1 P3: re-extract entities for a single chunk. */
export async function reExtractChunk(kbId: string, chunkId: string): Promise<unknown> {
  const response = await fetch(kbUrl(kbId, `/chunks/${encodeURIComponent(chunkId)}/re-extract`), {
    method: "POST",
  });
  return readResponse<unknown>(response, "Failed to re-extract chunk");
}

export function recallTest(kbId: string, body: { query: string; top_k: number }): Promise<RecallTestResponse> {
  return fetch(kbUrl(kbId, "/recall-test"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => readResponse<RecallTestResponse>(r, "Failed to run recall test"));
}

/** 批量切片位次（2026-09-05）：图谱实体抽屉行内「切片 #K」数据源。 */
export function fetchChunkPositions(kbId: string, chunkIds: readonly string[]): Promise<ChunkPositionsResponse> {
  return fetch(kbUrl(kbId, "/chunk-positions"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chunk_ids: chunkIds }),
  }).then((r) => readResponse<ChunkPositionsResponse>(r, "Failed to fetch chunk positions"));
}

// ── Phase-3 Batch-1 P6: manual knowledge cards (spec §8) ──────────────────

export function listManualCards(
  kbId: string,
  page: { offset: number; limit: number } = { offset: 0, limit: 50 },
): Promise<ManualCardsPage> {
  const params = new URLSearchParams({ offset: String(page.offset), limit: String(page.limit) });
  return fetch(kbUrl(kbId, `/manual-knowledge?${params}`)).then((r) =>
    readResponse<ManualCardsPage>(r, "Failed to fetch manual cards"),
  );
}

export function getManualCard(kbId: string, cardId: string): Promise<ManualCardDetail> {
  return fetch(kbUrl(kbId, `/manual-knowledge/${encodeURIComponent(cardId)}`)).then((r) =>
    readResponse<ManualCardDetail>(r, "Failed to fetch manual card"),
  );
}

export async function createManualCard(
  kbId: string,
  body: { title: string; content: string; tags?: string[]; include_in_wiki_search?: boolean },
): Promise<ManualCardDetail> {
  const response = await fetch(kbUrl(kbId, "/manual-knowledge"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<ManualCardDetail>(response, "Failed to create manual card");
}

export async function updateManualCard(
  kbId: string,
  cardId: string,
  body: { title?: string; content?: string; tags?: string[]; include_in_wiki_search?: boolean },
): Promise<ManualCardDetail> {
  const response = await fetch(kbUrl(kbId, `/manual-knowledge/${encodeURIComponent(cardId)}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<ManualCardDetail>(response, "Failed to update manual card");
}

export async function deleteManualCard(kbId: string, cardId: string): Promise<void> {
  const response = await fetch(kbUrl(kbId, `/manual-knowledge/${encodeURIComponent(cardId)}`), {
    method: "DELETE",
  });
  return readEmptyResponse(response, "Failed to delete manual card");
}

// ── 向量空间可视化（2026-08-15 spec §7）────────────────────────────────────

/**
 * GET /vector-projection query params. Absent keys fall through to the server
 * defaults (collections=all four, algo=pca, dims=2, sample_size=5000); the
 * server clamps sample_size to [100, 10000].
 */
export interface VectorProjectionParams {
  collections?: readonly string[];
  algo?: VectorProjectionAlgo;
  dims?: 2 | 3;
  sampleSize?: number;
  /** Bypass the fingerprint comparison and recompute (spec §6 escape hatch). */
  refresh?: boolean;
}

/** 视图参数 → query string（GET 投影与 POST query 投影共用——缓存键对齐）。 */
function projectionSearchParams(params: VectorProjectionParams): string {
  const search = new URLSearchParams();
  if (params.collections && params.collections.length > 0) {
    search.set("collections", params.collections.join(","));
  }
  if (params.algo) {
    search.set("algo", params.algo);
  }
  if (params.dims) {
    search.set("dims", String(params.dims));
  }
  if (params.sampleSize !== undefined) {
    search.set("sample_size", String(params.sampleSize));
  }
  if (params.refresh) {
    search.set("refresh", "true");
  }
  return search.toString();
}

export function getVectorProjection(
  kbId: string,
  params: VectorProjectionParams = {},
): Promise<VectorProjectionResponse> {
  const qs = projectionSearchParams(params);
  return fetch(kbUrl(kbId, qs ? `/vector-projection?${qs}` : "/vector-projection")).then((r) =>
    readResponse<VectorProjectionResponse>(r, "Failed to fetch vector projection"),
  );
}

/** GET /eval-runs/latest：两层各取最近一次 completed 非 ci 运行（spec §4.2）。 */
export function getLatestEvalMetrics(kbId: string): Promise<MetricsOverview> {
  return fetch(kbUrl(kbId, "/eval-runs/latest")).then((r) =>
    readResponse<MetricsOverview>(r, "Failed to fetch eval metrics overview"),
  );
}

/**
 * GET /eval-runs/trend：run 级点（contract v4，spec 2026-09-07 §2）——固定
 * 近 90 天窗口一次取全，无服务端聚合粒度；日/周/月是客户端视窗预设。
 */
export function getEvalTrend(kbId: string): Promise<TrendResponse> {
  return fetch(kbUrl(kbId, "/eval-runs/trend")).then((r) =>
    readResponse<TrendResponse>(r, "Failed to fetch eval trend"),
  );
}

/** GET /eval-runs/{run_id}：单行完整 JSON，drawer 下钻数据源（spec §4.2）。 */
export function getEvalRun(kbId: string, runId: string): Promise<EvalRunDetail> {
  return fetch(kbUrl(kbId, `/eval-runs/${encodeURIComponent(runId)}`)).then((r) =>
    readResponse<EvalRunDetail>(r, "Failed to fetch eval run detail"),
  );
}

/**
 * POST /vector-projection/query: transform raw question text through the
 * cached PCA model (409 when no projection is cached / the cached one is
 * umap). Never triggers a projection compute server-side.
 *
 * ``params`` 必须与当前投影视图一致：服务端缓存键含 collections/algo/dims/
 * sample_size，缺省回落默认值 → peek 落空 409（联动静默不渲染的修复）。
 */
export async function projectVectorQuery(
  kbId: string,
  text: string,
  params: VectorProjectionParams = {},
): Promise<VectorProjectionQueryResult> {
  const qs = projectionSearchParams(params);
  const response = await fetch(
    kbUrl(kbId, qs ? `/vector-projection/query?${qs}` : "/vector-projection/query"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    },
  );
  return readResponse<VectorProjectionQueryResult>(response, "Failed to project query");
}

// ── Eval question bank & run history (spec 2026-08-27 §4–§6) ─────────────

/** GET /eval/questions：读全量题库；文件不存在由后端回空表（spec §4.2）。 */
export function listEvalQuestions(kbId: string): Promise<EvalQuestionListResponse> {
  return fetch(kbUrl(kbId, "/eval/questions")).then((r) =>
    readResponse<EvalQuestionListResponse>(r, "Failed to fetch eval questions"),
  );
}

/** POST /eval/questions：新增一题，id 由服务端生成（201；schema 违例 422）。 */
export function createEvalQuestion(kbId: string, input: EvalQuestionCreateInput): Promise<EvalQuestion> {
  return fetch(kbUrl(kbId, "/eval/questions"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then((r) => readResponse<EvalQuestion>(r, "Failed to create eval question"));
}

/** DELETE /eval/questions/{id}：删一题（204；id 不存在 404）。 */
export async function deleteEvalQuestion(kbId: string, questionId: string): Promise<void> {
  const response = await fetch(kbUrl(kbId, `/eval/questions/${encodeURIComponent(questionId)}`), {
    method: "DELETE",
  });
  await readEmptyResponse(response, "Failed to delete eval question");
}

/**
 * PATCH /eval/questions/{id}：改锚（2026-10-06 改锚对，spec §2③）——只动
 * relevant_chunk_ids（实体服务端跟锚收缩），清空 = 解除锚定。B′ 锚定核验
 * 同 create/accept：422 结构化 detail 转 AnchorBlockError；anchor_ack 仅
 * 红块确认路径携带（原「保存」永为缺省/假值）。
 */
export function updateEvalQuestion(
  kbId: string,
  questionId: string,
  body: EvalQuestionUpdateInput,
): Promise<EvalQuestion> {
  return fetch(kbUrl(kbId, `/eval/questions/${encodeURIComponent(questionId)}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => readResponse<EvalQuestion>(r, "Failed to update eval question"));
}

/** DELETE /eval-runs：批量删除运行历史（2026-09-08）；复选框选中集/行菜单/
 *  右键「删除所选」共用；空集 422。返回实际删除行数。 */
export function deleteEvalRuns(kbId: string, runIds: string[]): Promise<EvalRunDeleteResponse> {
  return fetch(kbUrl(kbId, "/eval-runs"), {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_ids: runIds }),
  }).then((r) => readResponse<EvalRunDeleteResponse>(r, "Failed to delete eval runs"));
}

/**
 * GET /eval-runs：历史列表 + 顶层 in_flight（spec §6.1）。默认排除 ci 行；
 * limit 超上限由后端 clamp，前端不重复限制。
 */
export function listEvalRuns(kbId: string, params: { limit?: number; include_ci?: boolean } = {}): Promise<EvalRunListResponse> {
  const search = new URLSearchParams();
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.include_ci) search.set("include_ci", "true");
  const qs = search.toString();
  return fetch(kbUrl(kbId, qs ? `/eval-runs?${qs}` : "/eval-runs")).then((r) =>
    readResponse<EvalRunListResponse>(r, "Failed to fetch eval runs"),
  );
}

/** POST /eval-runs：触发一次按需评测（202 幂等，spec §5.1 + 2026-09-01 B 方案）。
 *  空载荷 = L1 全量（后端默认，旧契约兼容）；``l1_l2`` / ``question_ids`` 见 EvalTriggerInput。 */
export function triggerEvalRun(kbId: string, input: EvalTriggerInput = {}): Promise<EvalTriggerResponse> {
  return fetch(kbUrl(kbId, "/eval-runs"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then((r) => readResponse<EvalTriggerResponse>(r, "Failed to trigger eval run"));
}

/** POST /eval-runs/cancel：终止在飞按需评测（spec 2026-09-06 §11）。
 *  202 = 已发取消（runner 自落 cancelled 行并释放 already_running 锁）；409 = 无在飞 run。 */
export function cancelEvalRun(kbId: string): Promise<EvalCancelResponse> {
  return fetch(kbUrl(kbId, "/eval-runs/cancel"), { method: "POST" }).then((r) =>
    readResponse<EvalCancelResponse>(r, "Failed to cancel eval run"),
  );
}

// ── Question synthesis（2026-08-28 spec §6，Task 6–8）───────────────────

/** POST /eval/questions/synthesize：自底向上合成候选题（202 幂等；文档未就绪 409）。 */
export function triggerQuestionSynthesis(kbId: string, input: SynthesisTriggerInput): Promise<SynthesisTriggerResponse> {
  return fetch(kbUrl(kbId, "/eval/questions/synthesize"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then((r) => readResponse<SynthesisTriggerResponse>(r, "Failed to trigger question synthesis"));
}

/** GET /eval/questions/synthesize：合成状态（in_progress + 暂存候选 + 元数据）。 */
export function getSynthesisStatus(kbId: string): Promise<SynthesisStatus> {
  return fetch(kbUrl(kbId, "/eval/questions/synthesize")).then((r) =>
    readResponse<SynthesisStatus>(r, "Failed to fetch synthesis status"),
  );
}

/** POST .../synthesize/{candidate_id}/accept：采纳候选入题库（201；未知候选 404）。
 *  ``ack``（B′，2026-10-05）：真值时发 ``{"anchor_ack": true}`` 覆盖词条级锚定
 *  拦截；缺省保持无请求体（旧契约兼容，bodyless 调用不受影响）。 */
export function acceptSynthesisCandidate(kbId: string, candidateId: string, ack = false): Promise<EvalQuestion> {
  return fetch(kbUrl(kbId, `/eval/questions/synthesize/${encodeURIComponent(candidateId)}/accept`), {
    method: "POST",
    ...(ack ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ anchor_ack: true }) } : {}),
  }).then((r) => readResponse<EvalQuestion>(r, "Failed to accept synthesis candidate"));
}

/** DELETE .../synthesize/{candidate_id}：忽略候选（204；未知候选 404）。 */
export async function rejectSynthesisCandidate(kbId: string, candidateId: string): Promise<void> {
  const response = await fetch(kbUrl(kbId, `/eval/questions/synthesize/${encodeURIComponent(candidateId)}`), {
    method: "DELETE",
  });
  await readEmptyResponse(response, "Failed to reject synthesis candidate");
}
