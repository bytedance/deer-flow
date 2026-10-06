/**
 * TanStack Query hooks for the knowledge API. Polling cadence lives in the
 * pure `documentsRefetchInterval` (document-stats.ts) so the wiring here
 * stays trivially testable.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import * as api from "./api";
import { documentsRefetchInterval } from "./document-stats";
import { evalRunsRefetchInterval } from "./eval-run-status";
import { reindexRefetchInterval } from "./reindex-status";
import { synthesisRefetchInterval } from "./synthesis-status";
import type {
  EvalQuestionCreateInput,
  EvalQuestionListResponse,
  EvalQuestionUpdateInput,
  EvalRunDetail,
  EvalRunListResponse,
  EvalTriggerInput,
  MetricsOverview,
  SynthesisAcceptInput,
  SynthesisStatus,
  SynthesisTriggerInput,
  TrendResponse,
} from "./types";
import { wikiEntriesRefetchInterval } from "./wiki-status";

export function knowledgeBasesKey() {
  return ["knowledge-bases"] as const;
}

export function knowledgeDocumentsKey(kbId: string) {
  return ["knowledge-bases", kbId, "documents"] as const;
}

/** 知识图谱（2026-08-19 spec §4）：端点无参数维度，键即 kb 粒度。 */
export function knowledgeGraphKey(kbId: string) {
  return ["knowledge-bases", kbId, "graph"] as const;
}

export function knowledgeChunksKey(kbId: string, docId: string, offset: number, limit: number) {
  return ["knowledge-bases", kbId, "documents", docId, "chunks", { offset, limit }] as const;
}

export function useKnowledgeBases() {
  return useQuery({ queryKey: knowledgeBasesKey(), queryFn: api.listKnowledgeBases });
}

export function supportedFormatsKey() {
  return ["knowledge-bases", "supported-formats"] as const;
}

/** Upload allowlist (Task 6): static data — never goes stale within a session. */
export function useSupportedFormats() {
  return useQuery({
    queryKey: supportedFormatsKey(),
    queryFn: api.getSupportedFormats,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useCreateKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.createKnowledgeBase,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeBasesKey() });
    },
  });
}

export function useUpdateKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kbId, patch }: { kbId: string; patch: { name?: string; description?: string } }) =>
      api.updateKnowledgeBase(kbId, patch),
    onSuccess: (_data, { kbId }) => {
      void queryClient.invalidateQueries({ queryKey: knowledgeBasesKey() });
      void queryClient.invalidateQueries({ queryKey: knowledgeDocumentsKey(kbId) });
    },
  });
}

export function useDeleteKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (kbId: string) => api.deleteKnowledgeBase(kbId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeBasesKey() });
    },
  });
}

export function useDocuments(kbId: string | null) {
  return useQuery({
    queryKey: knowledgeDocumentsKey(kbId ?? ""),
    queryFn: () => api.listDocuments(kbId!),
    enabled: kbId !== null,
    refetchInterval: (query) => documentsRefetchInterval(query.state.data),
  });
}

export function useUploadDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => api.uploadDocument(kbId, file),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeDocumentsKey(kbId) });
    },
  });
}

export function useDeleteDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => api.deleteDocument(kbId, docId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeDocumentsKey(kbId) });
    },
  });
}

export function useRetryDocument(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => api.retryDocument(kbId, docId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeDocumentsKey(kbId) });
    },
  });
}

export function useDocumentChunks(kbId: string | null, docId: string | null, offset: number, limit: number) {
  return useQuery({
    queryKey: knowledgeChunksKey(kbId ?? "", docId ?? "", offset, limit),
    queryFn: () => api.listDocumentChunks(kbId!, docId!, { offset, limit }),
    enabled: kbId !== null && docId !== null,
  });
}

export function useGenerateWiki(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (mode: api.WikiGenerateMode) => api.generateWiki(kbId, mode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeWikiEntriesKey(kbId) });
      // The 202 ack returns before the background asyncio task flips the
      // in-flight flag, so the immediate refetch can still read idle. One
      // delayed re-invalidation closes that gap — after it lands on
      // "generating", the entries query's refetchInterval takes over.
      setTimeout(() => void queryClient.invalidateQueries({ queryKey: knowledgeWikiEntriesKey(kbId) }), 1000);
    },
  });
}

/**
 * 局部更新/重建（2026-09-02）：重生成手选条目。与 ``useGenerateWiki`` 同一
 * 失效节奏（含 1s 延迟二次失效弥合 202→in-flight 间隙），因为后端复用同一
 * 库级 in-flight/轮询/完成信号。
 */
export function useRegenerateWikiEntries(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entryIds: string[]) => api.regenerateWikiEntries(kbId, entryIds),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeWikiEntriesKey(kbId) });
      setTimeout(() => void queryClient.invalidateQueries({ queryKey: knowledgeWikiEntriesKey(kbId) }), 1000);
    },
  });
}

export function knowledgeWikiEntriesKey(kbId: string) {
  return ["knowledge-bases", kbId, "wiki-entries"] as const;
}

export function knowledgeReindexStatusKey(kbId: string) {
  return ["knowledge-bases", kbId, "reindex-status"] as const;
}

/**
 * 重建进度（spec 2026-09-14 §5 / P4）：只在重建在飞时轮询，空闲不打扰。
 * 设置页的重建入口用它渲染进度行与禁用按钮。
 */
export function useReindexStatus(kbId: string | null) {
  return useQuery({
    queryKey: knowledgeReindexStatusKey(kbId ?? ""),
    queryFn: () => api.getReindexStatus(kbId!),
    enabled: kbId !== null,
    refetchInterval: (query) => reindexRefetchInterval(query.state.data),
  });
}

/**
 * 触发库级重建（202）。与 ``useGenerateWiki`` 同一失效节奏（含 1s 延迟二次失效）：
 * 202 ack 先于后台任务翻 in-flight 标志返回，立即 refetch 可能仍读到空闲。
 */
export function useReindexKnowledgeBase(kbId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.reindexKnowledgeBase(kbId!),
    onSuccess: () => {
      if (kbId === null) return;
      void queryClient.invalidateQueries({ queryKey: knowledgeReindexStatusKey(kbId) });
      setTimeout(() => void queryClient.invalidateQueries({ queryKey: knowledgeReindexStatusKey(kbId) }), 1000);
    },
  });
}

/** 评测数据（2026-08-24 spec §5，plan Task 5）：latest 无参数维度，键即 kb 粒度。 */
export function knowledgeEvalLatestKey(kbId: string) {
  return ["knowledge-bases", kbId, "eval-runs", "latest"] as const;
}

/** 趋势查询键（contract v4）：固定 90d 一次取全，无粒度维度——切视窗预设不 refetch。 */
export function knowledgeEvalTrendKey(kbId: string) {
  return ["knowledge-bases", kbId, "eval-runs", "trend"] as const;
}

/** 单次运行详情键（drawer 下钻，plan Task 6）：runId 定位。 */
export function knowledgeEvalRunKey(kbId: string, runId: string) {
  return ["knowledge-bases", kbId, "eval-runs", "detail", runId] as const;
}

/** 题库键（2026-08-27 spec §4.2，plan Task 4）：无分页维度，键即 kb 粒度。 */
export function knowledgeEvalQuestionsKey(kbId: string) {
  return ["knowledge-bases", kbId, "eval-questions"] as const;
}

/** 历史列表键（spec §6.1）：含顶层 in_flight，与 detail/latest/trend 键互斥。 */
export function knowledgeEvalRunsKey(kbId: string) {
  return ["knowledge-bases", kbId, "eval-runs", "history"] as const;
}

/** 合成状态键（2026-08-28 spec §6，Task 8）：与题库/运行键互斥，kb 粒度。 */
export function knowledgeSynthesisKey(kbId: string) {
  return ["knowledge-bases", kbId, "eval-synthesis"] as const;
}

/**
 * 评测数据分钟级不变：30s 内 keep-alive 来回切 tab 不重复请求（plan Task 5）。
 */
const EVAL_STALE_TIME_MS = 30_000;

/**
 * 指标总览（GET /eval-runs/latest）。Lazy: the caller gates with ``enabled``
 * so the fetch only fires once the eval tab is first activated — keep-alive
 * panes stay mounted, so without the gate every kb page load would fetch
 * eagerly（useWikiEntries / useVectorProjection 先例）.
 */
export function useMetricsOverview(kbId: string | null, enabled = true): UseQueryResult<MetricsOverview> {
  return useQuery({
    queryKey: knowledgeEvalLatestKey(kbId ?? ""),
    queryFn: () => api.getLatestEvalMetrics(kbId!),
    enabled: enabled && kbId !== null,
    staleTime: EVAL_STALE_TIME_MS,
  });
}

/** 指标趋势（GET /eval-runs/trend）：run 级点一次取全（contract v4）。 */
export function useEvalTrend(
  kbId: string | null,
  enabled = true,
): UseQueryResult<TrendResponse> {
  return useQuery({
    queryKey: knowledgeEvalTrendKey(kbId ?? ""),
    queryFn: () => api.getEvalTrend(kbId!),
    enabled: enabled && kbId !== null,
    staleTime: EVAL_STALE_TIME_MS,
  });
}

/**
 * 单次运行详情（GET /eval-runs/{run_id}）：runId 定位，null 即禁用——
 * drawer 关闭后不残留请求（plan Task 6）。
 */
export function useEvalRun(kbId: string | null, runId: string | null): UseQueryResult<EvalRunDetail> {
  return useQuery({
    queryKey: knowledgeEvalRunKey(kbId ?? "", runId ?? ""),
    queryFn: () => api.getEvalRun(kbId!, runId!),
    enabled: kbId !== null && runId !== null,
  });
}

// ── 评测二期（2026-08-27 spec §4–§6，plan Task 4）────────────────────────

/** 题库列表（GET /eval/questions），enabled 由 eval tab 激活下发。 */
export function useEvalQuestions(kbId: string | null, enabled = true): UseQueryResult<EvalQuestionListResponse> {
  return useQuery({
    queryKey: knowledgeEvalQuestionsKey(kbId ?? ""),
    queryFn: () => api.listEvalQuestions(kbId!),
    enabled: enabled && kbId !== null,
    staleTime: EVAL_STALE_TIME_MS,
  });
}

/** 新增考题；成功失效题库缓存（表格即时见新题）。 */
export function useAddEvalQuestion(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: EvalQuestionCreateInput) => api.createEvalQuestion(kbId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeEvalQuestionsKey(kbId) });
    },
  });
}

/** 删除考题；成功失效题库缓存。 */
export function useDeleteEvalQuestion(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (questionId: string) => api.deleteEvalQuestion(kbId, questionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeEvalQuestionsKey(kbId) });
    },
  });
}

/**
 * 改锚（2026-10-06 改锚对，spec §2③）：只动 relevant_chunk_ids 的更新口。
 * 成功失效题库缓存——抽屉改完锚，bank 行的切片数与「悬空」徽章即时收敛
 * （missing_chunk_ids 是读时派生，重拉即新结论）。
 */
export function useUpdateEvalQuestion(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ questionId, body }: { questionId: string; body: EvalQuestionUpdateInput }) =>
      api.updateEvalQuestion(kbId, questionId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeEvalQuestionsKey(kbId) });
    },
  });
}

/**
 * 批量删除运行历史（2026-09-08）：invalidate eval-runs 全前缀——history/
 * latest/trend/detail 同源，删除后四面一起收敛；题库召回列取 latest 的
 * question_results，同前缀覆盖。
 */
export function useDeleteEvalRuns(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runIds: string[]) => api.deleteEvalRuns(kbId, runIds),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases", kbId, "eval-runs"] });
    },
  });
}

/**
 * 历史列表（GET /eval-runs）：轮询由顶层 in_flight 驱动（eval-run-status
 * 纯函数），drain 后停轮询——运行完成行的刷新走 drain 边 invalidate（§5.2）。
 */
export function useEvalRuns(kbId: string | null, enabled = true): UseQueryResult<EvalRunListResponse> {
  return useQuery({
    queryKey: knowledgeEvalRunsKey(kbId ?? ""),
    queryFn: () => api.listEvalRuns(kbId!),
    enabled: enabled && kbId !== null,
    refetchInterval: (query) => evalRunsRefetchInterval(query.state.data),
  });
}

/**
 * 触发一次按需评测（2026-09-01 B 方案分档）：缺省 L1 快速档全量；
 * ``{ layers: "l1_l2" }`` 完整档，``question_ids`` 选题。202 响应原样透传
 * （enqueued / already_running 由调用方消费成不同 toast）；行数据的刷新
 * 不在这里 invalidate——统一走 drain 边，避免 POST 与首次轮询双重请求。
 */
export function useTriggerEvalRun(kbId: string) {
  return useMutation({
    mutationFn: (input: EvalTriggerInput = {}) => api.triggerEvalRun(kbId, input),
  });
}

/**
 * 终止在飞按需评测（spec 2026-09-06 §11）。与触发同款不在此 invalidate——
 * 轮询见 in_flight false 时走 drain 边一次性失效三个评测 query，cancelled 行
 * 随历史/总览一并刷新。
 */
export function useCancelEvalRun(kbId: string) {
  return useMutation({
    mutationFn: () => api.cancelEvalRun(kbId),
  });
}

// ── 合成造题（2026-08-28 spec §6，plan Task 8）────────────────────────

/**
 * 合成状态：轮询由 in_progress 驱动（synthesis-status 纯函数），drain 后
 * 停轮询；无暂存文件时后端回空列表，新 KB 不是错误。
 */
export function useSynthesisStatus(kbId: string | null, enabled = true): UseQueryResult<SynthesisStatus> {
  return useQuery({
    queryKey: knowledgeSynthesisKey(kbId ?? ""),
    queryFn: () => api.getSynthesisStatus(kbId!),
    enabled: enabled && kbId !== null,
    refetchInterval: (query) => synthesisRefetchInterval(query.state.data),
  });
}

/** 触发合成：202 响应原样透传；成功后失效合成缓存——旧缓存的
 * in_progress=false 会让轮询永不启动（触发后审核面板不现），重拉一次
 * 拿到 in_progress 真值后轮询接管（2026-09-02 多篇联合出题时实测发现）。 */
export function useTriggerSynthesis(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SynthesisTriggerInput) => api.triggerQuestionSynthesis(kbId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeSynthesisKey(kbId) });
    },
  });
}

/** 采纳候选：入库后同时失效暂存与题库缓存（新题即时可见）。入参携可选
 *  anchor_ack（B′，2026-10-05）：真值时透传给 accept 请求体覆盖词条级拦截。 */
export function useAcceptSynthesisCandidate(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SynthesisAcceptInput) => api.acceptSynthesisCandidate(kbId, input.candidate_id, input.anchor_ack ?? false),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeSynthesisKey(kbId) });
      void queryClient.invalidateQueries({ queryKey: knowledgeEvalQuestionsKey(kbId) });
    },
  });
}

/** 忽略候选：只动暂存；题库失效一并做（口径统一，代价是一次空刷）。 */
export function useRejectSynthesisCandidate(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (candidateId: string) => api.rejectSynthesisCandidate(kbId, candidateId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeSynthesisKey(kbId) });
      void queryClient.invalidateQueries({ queryKey: knowledgeEvalQuestionsKey(kbId) });
    },
  });
}

/**
 * Wiki tab listing (phase-2 batch-1). Lazy: the caller gates with
 * ``enabled`` so the list only loads once the tab is first activated —
 * keep-alive panes stay mounted, so without the gate every tab would fetch
 * eagerly.
 */
export function useWikiEntries(kbId: string | null, enabled = true) {
  return useQuery({
    queryKey: knowledgeWikiEntriesKey(kbId ?? ""),
    queryFn: () => api.listWikiEntries(kbId!),
    enabled: enabled && kbId !== null,
    // Poll only while a generation run is in flight (wiki 更新状态可见,
    // 2026-08-14) — same 3s cadence as the documents query; idle never polls.
    refetchInterval: (query) => wikiEntriesRefetchInterval(query.state.data),
  });
}

/** Full entry text for the drawer; null-gated until the drawer opens. */
export function useWikiEntry(kbId: string | null, entryId: string | null) {
  return useQuery({
    queryKey: [...knowledgeWikiEntriesKey(kbId ?? ""), entryId ?? ""] as const,
    queryFn: () => api.getWikiEntry(kbId!, entryId!),
    enabled: kbId !== null && entryId !== null,
  });
}

/**
 * Manual single-entry delete (Task 13). Regeneration semantics: an eligible
 * entity's entry comes back on the next generation run (a reset); only
 * disqualified/vanished entities' entries stay deleted.
 */
export function useDeleteWikiEntry(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entryId: string) => api.deleteWikiEntry(kbId, entryId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeWikiEntriesKey(kbId) });
    },
  });
}

/** Phase-3 Batch-1 P1: update wiki entry (main content + supplement layer). */
export function useUpdateWikiEntry(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ entryId, body }: { entryId: string; body: { content: string; supplement_content: string | null } }) =>
      api.updateWikiEntry(kbId, entryId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeWikiEntriesKey(kbId) });
    },
  });
}

/** Phase-3 Batch-1 P2: update chunk text with re-embedding. */
export function useUpdateChunk(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ chunkId, body }: { chunkId: string; body: { text: string } }) => api.updateChunk(kbId, chunkId, body),
    onSuccess: () => {
      // Invalidate all chunk queries for this KB (any doc might contain this chunk)
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases", kbId, "documents"] });
    },
  });
}

/** Phase-3 Batch-1 P5: preview chunk deletion impact (dry-run). */
export function usePreviewChunkDeletion(kbId: string) {
  return useMutation({
    mutationFn: (body: { chunk_ids: string[] }) => api.previewChunkDeletion(kbId, body),
  });
}

/** Task 5 收尾: delete a single chunk (cascade runs server-side). */
export function useDeleteChunk(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (chunkId: string) => api.deleteChunk(kbId, chunkId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases", kbId, "documents"] });
    },
  });
}

/** Phase-3 Batch-1 P3: re-extract entities for a single chunk. */
export function useReExtractChunk(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (chunkId: string) => api.reExtractChunk(kbId, chunkId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge-bases", kbId, "documents"] });
    },
  });
}

/**
 * P1 recall test (phase-2 batch-1): a mutation, not a query — each run hits
 * the live retrieval chain (embedding + rerank + entity-extraction LLM), so
 * results must never be cached/refetched implicitly.
 */
export function useRecallTest(kbId: string) {
  return useMutation({
    mutationFn: (body: { query: string; top_k: number }) => api.recallTest(kbId, body),
  });
}

// ── Phase-3 Batch-1 P6: manual knowledge cards (spec §8) ──────────────────

export function knowledgeManualCardsKey(kbId: string) {
  return ["knowledge-bases", kbId, "manual-cards"] as const;
}

/** Manual card list. Lazy: gated by ``enabled`` (the wiki tab's collapsible
 * card section only fetches once expanded). */
export function useManualCards(kbId: string | null, enabled = true) {
  return useQuery({
    queryKey: knowledgeManualCardsKey(kbId ?? ""),
    queryFn: () => api.listManualCards(kbId!),
    enabled: enabled && kbId !== null,
  });
}

/** Full card for the editor dialog; null-gated until an edit opens. */
export function useManualCard(kbId: string | null, cardId: string | null) {
  return useQuery({
    queryKey: [...knowledgeManualCardsKey(kbId ?? ""), cardId ?? ""] as const,
    queryFn: () => api.getManualCard(kbId!, cardId!),
    enabled: kbId !== null && cardId !== null,
  });
}

export function useCreateManualCard(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; content: string; tags?: string[]; include_in_wiki_search?: boolean }) =>
      api.createManualCard(kbId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeManualCardsKey(kbId) });
    },
  });
}

export function useUpdateManualCard(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      cardId,
      body,
    }: {
      cardId: string;
      body: { title?: string; content?: string; tags?: string[]; include_in_wiki_search?: boolean };
    }) => api.updateManualCard(kbId, cardId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeManualCardsKey(kbId) });
    },
  });
}

export function useDeleteManualCard(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (cardId: string) => api.deleteManualCard(kbId, cardId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: knowledgeManualCardsKey(kbId) });
    },
  });
}

// ── 向量空间可视化（2026-08-15 spec §7）────────────────────────────────────

export function knowledgeVectorProjectionKey(kbId: string, params: api.VectorProjectionParams = {}) {
  return ["knowledge-bases", kbId, "vector-projection", params] as const;
}

/**
 * Projection query. Lazy like the wiki list: gated by ``enabled`` so the
 * fetch only fires once the vectors tab is first activated — keep-alive
 * panes stay mounted, so without the gate it would fetch eagerly. The
 * server-side fingerprint cache makes repeat activations cheap.
 */
export function useVectorProjection(kbId: string | null, params: api.VectorProjectionParams = {}, enabled = true) {
  return useQuery({
    queryKey: knowledgeVectorProjectionKey(kbId ?? "", params),
    queryFn: () => api.getVectorProjection(kbId!, params),
    enabled: enabled && kbId !== null,
  });
}

/**
 * 知识图谱（2026-08-19 spec §4 P2）：tab 激活才拉取（lazy 门控，对齐
 * useVectorProjection 先例）。无参数维度——端点不做缓存，每次现算，
 * React Query 的 staleTime 默认即可。
 */
export function useKnowledgeGraph(kbId: string | null, enabled = true) {
  return useQuery({
    queryKey: knowledgeGraphKey(kbId ?? ""),
    queryFn: () => api.getKnowledgeGraph(kbId!),
    enabled: enabled && kbId !== null,
  });
}

/** 批量切片位次（2026-09-05）：排序后拼串入键——同一集合不同顺序命中同一缓存。 */
export function chunkPositionsKey(kbId: string, chunkIds: readonly string[]) {
  return ["knowledge-bases", kbId, "chunk-positions", [...chunkIds].sort().join("|")] as const;
}

/**
 * 批量切片位次查询（2026-09-05）：图谱实体抽屉打开时传选中实体的关联
 * 切片 id 列表（null/空列表 = 不发请求）。位次是稳定事实（切片不删不变），
 * 给长 staleTime 免抽屉反复开合重拉。
 */
export function useChunkPositions(kbId: string | null, chunkIds: readonly string[] | null) {
  const ids = chunkIds ?? [];
  return useQuery({
    queryKey: chunkPositionsKey(kbId ?? "", ids),
    queryFn: () => api.fetchChunkPositions(kbId!, ids),
    enabled: kbId !== null && ids.length > 0,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Query-text overlay projection: a mutation, not a query (same discipline as
 * the recall test) — each call hits the live embedding model, results are
 * never cached/refetched implicitly.
 *
 * ``params`` 必须镜像当前投影视图（collections/algo/dims）：服务端缓存键含
 * 这些维度，缺省回落默认值 → peek 落空 409（P6 联动静默不渲染的修复）。
 */
export function useProjectVectorQuery(kbId: string, params: api.VectorProjectionParams = {}) {
  return useMutation({
    mutationFn: (text: string) => api.projectVectorQuery(kbId, text, params),
  });
}

/**
 * 重新计算（Task 7）：直打 `refresh=true` 强制重算，成功后把新数据写回
 * 主 queryKey 缓存——单一缓存键，不产生 refresh 副本，画布随缓存更新自动
 * 刷新。refresh 永不进 `useVectorProjection` 的常规参数（否则每次轮询都
 * 重算）。
 */
export function useRecomputeVectorProjection(kbId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: api.VectorProjectionParams) =>
      api.getVectorProjection(kbId, { ...params, refresh: true }),
    onSuccess: (data, params) => {
      void queryClient.setQueryData(knowledgeVectorProjectionKey(kbId, params), data);
    },
  });
}
