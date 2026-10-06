/**
 * Wiring tests for the knowledge TanStack Query hooks: fetch routing,
 * enabled gating, polling wiring, and cache invalidation after mutations.
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/core/knowledge/api", () => ({
  listKnowledgeBases: rs.fn(),
  createKnowledgeBase: rs.fn(),
  updateKnowledgeBase: rs.fn(),
  deleteKnowledgeBase: rs.fn(),
  listDocuments: rs.fn(),
  uploadDocument: rs.fn(),
  deleteDocument: rs.fn(),
  retryDocument: rs.fn(),
  listDocumentChunks: rs.fn(),
  generateWiki: rs.fn(),
  getLatestEvalMetrics: rs.fn(),
  getEvalTrend: rs.fn(),
  getEvalRun: rs.fn(),
  listEvalQuestions: rs.fn(),
  createEvalQuestion: rs.fn(),
  deleteEvalQuestion: rs.fn(),
  updateEvalQuestion: rs.fn(),
  listEvalRuns: rs.fn(),
  triggerEvalRun: rs.fn(),
  triggerQuestionSynthesis: rs.fn(),
  getSynthesisStatus: rs.fn(),
  acceptSynthesisCandidate: rs.fn(),
  rejectSynthesisCandidate: rs.fn(),
}));

import * as api from "@/core/knowledge/api";
import { evalRunsRefetchInterval } from "@/core/knowledge/eval-run-status";
import {
  knowledgeDocumentsKey,
  knowledgeEvalLatestKey,
  knowledgeEvalQuestionsKey,
  knowledgeEvalRunsKey,
  knowledgeEvalRunKey,
  knowledgeEvalTrendKey,
  knowledgeSynthesisKey,
  useAcceptSynthesisCandidate,
  useAddEvalQuestion,
  useCreateKnowledgeBase,
  useDeleteEvalQuestion,
  useDocuments,
  useEvalQuestions,
  useEvalRun,
  useEvalRuns,
  useEvalTrend,
  useGenerateWiki,
  useKnowledgeBases,
  useMetricsOverview,
  useRejectSynthesisCandidate,
  useRetryDocument,
  useSynthesisStatus,
  useTriggerEvalRun,
  useTriggerSynthesis,
  useUpdateEvalQuestion,
  useUploadDocument,
} from "@/core/knowledge/hooks";
import { synthesisRefetchInterval } from "@/core/knowledge/synthesis-status";
import type {
  EvalQuestion,
  EvalQuestionListResponse,
  EvalRunDetail,
  EvalRunListResponse,
  KnowledgeDocument,
  MetricsOverview,
  SynthesisCandidate,
  SynthesisStatus,
  TrendResponse,
} from "@/core/knowledge/types";

const KB = {
  id: "kb-1",
  owner_id: "user-1",
  name: "产品资料",
  description: "",
  visibility: "private",
  created_at: "2026-08-09T10:00:00Z",
};

const READY_DOC: KnowledgeDocument = {
  id: "doc-1",
  kb_id: "kb-1",
  uploader_id: "user-1",
  name: "a.pdf",
  size_bytes: 10,
  storage_path: "p",
  status: "ready",
  progress_percent: 100,
  chunk_count: 3,
  error: null,
  path_status: null,
  content_hash: null,
  created_at: "2026-08-09T10:00:00Z",
};

function createWrapper(queryClient: QueryClient) {
  return function QueryWrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function freshQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  rs.mocked(api.listKnowledgeBases).mockResolvedValue([KB]);
  rs.mocked(api.listDocuments).mockResolvedValue([READY_DOC]);
  rs.mocked(api.createKnowledgeBase).mockResolvedValue(KB);
  rs.mocked(api.uploadDocument).mockResolvedValue(READY_DOC);
  rs.mocked(api.retryDocument).mockResolvedValue({ ...READY_DOC, status: "uploaded", progress_percent: 0 });
  rs.mocked(api.generateWiki).mockResolvedValue({ status: "enqueued" });
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("useKnowledgeBases", () => {
  it("fetches and caches the list", async () => {
    const { result } = renderHook(() => useKnowledgeBases(), {
      wrapper: createWrapper(freshQueryClient()),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([KB]);
    expect(api.listKnowledgeBases).toHaveBeenCalledTimes(1);
  });
});

describe("useCreateKnowledgeBase", () => {
  it("invalidates the kb list after success", async () => {
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const list = renderHook(() => useKnowledgeBases(), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));

    const mutation = renderHook(() => useCreateKnowledgeBase(), { wrapper });
    await mutation.result.current.mutateAsync({ name: "新库", description: "" });

    expect(rs.mocked(api.createKnowledgeBase).mock.calls[0]?.[0]).toEqual({ name: "新库", description: "" });
    await waitFor(() => expect(api.listKnowledgeBases).toHaveBeenCalledTimes(2));
  });
});

describe("useDocuments", () => {
  it("is disabled without a kb id (no fetch fires)", () => {
    renderHook(() => useDocuments(null), { wrapper: createWrapper(freshQueryClient()) });
    expect(api.listDocuments).not.toHaveBeenCalled();
  });

  it("fetches when a kb is selected", async () => {
    const { result } = renderHook(() => useDocuments("kb-1"), {
      wrapper: createWrapper(freshQueryClient()),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.listDocuments).toHaveBeenCalledWith("kb-1");
    expect(result.current.data?.[0]?.status).toBe("ready");
  });
});

describe("document mutations", () => {
  it("upload invalidates the documents query (picks up the uploaded row)", async () => {
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const docs = renderHook(() => useDocuments("kb-1"), { wrapper });
    await waitFor(() => expect(docs.result.current.isSuccess).toBe(true));

    const upload = renderHook(() => useUploadDocument("kb-1"), { wrapper });
    await upload.result.current.mutateAsync(new File(["x"], "b.md"));

    await waitFor(() => expect(api.listDocuments).toHaveBeenCalledTimes(2));
  });

  it("retry invalidates the documents query", async () => {
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const docs = renderHook(() => useDocuments("kb-1"), { wrapper });
    await waitFor(() => expect(docs.result.current.isSuccess).toBe(true));

    const retry = renderHook(() => useRetryDocument("kb-1"), { wrapper });
    await retry.result.current.mutateAsync("doc-1");

    expect(api.retryDocument).toHaveBeenCalledWith("kb-1", "doc-1");
    await waitFor(() => expect(api.listDocuments).toHaveBeenCalledTimes(2));
  });

  it("retry re-fetch surfaces the re-queued state for a degraded document", async () => {
    rs.mocked(api.listDocuments)
      .mockResolvedValueOnce([
        {
          ...READY_DOC,
          path_status: {
            vector: "done",
            graph: "done",
            wiki: "ready",
            caption: "degraded",
          },
        },
      ])
      .mockResolvedValue([{ ...READY_DOC, status: "uploaded", progress_percent: 0 }]);
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const docs = renderHook(() => useDocuments("kb-1"), { wrapper });
    await waitFor(() => expect(docs.result.current.isSuccess).toBe(true));
    expect(docs.result.current.data?.[0]?.path_status).toEqual({
      vector: "done",
      graph: "done",
      wiki: "ready",
      caption: "degraded",
    });

    const retry = renderHook(() => useRetryDocument("kb-1"), { wrapper });
    await retry.result.current.mutateAsync("doc-1");
    // 降级行与 failed 同管道：受理后行回到 uploaded（进度清零）。
    await waitFor(() =>
      expect(docs.result.current.data?.[0]?.status).toBe("uploaded"),
    );
  });

  it("documents query cache uses the kb-scoped key", async () => {
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const docs = renderHook(() => useDocuments("kb-1"), { wrapper });
    await waitFor(() => expect(docs.result.current.isSuccess).toBe(true));
    expect(queryClient.getQueryData(knowledgeDocumentsKey("kb-1"))).toEqual([READY_DOC]);
  });
});

describe("useGenerateWiki", () => {
  it("posts the trigger without touching the documents cache", async () => {
    const { result } = renderHook(() => useGenerateWiki("kb-1"), {
      wrapper: createWrapper(freshQueryClient()),
    });
    await result.current.mutateAsync("incremental");
    expect(api.generateWiki).toHaveBeenCalledWith("kb-1", "incremental");
  });

  it("passes the full-rebuild mode through", async () => {
    const { result } = renderHook(() => useGenerateWiki("kb-1"), {
      wrapper: createWrapper(freshQueryClient()),
    });
    await result.current.mutateAsync("full");
    expect(api.generateWiki).toHaveBeenCalledWith("kb-1", "full");
  });
});

// ── 评测数据 hooks（2026-08-24 spec §5，plan Task 5）──────────────────────

const EVAL_OVERVIEW: MetricsOverview = {
  kb_id: "kb-1",
  layer1: null,
  layer2: null,
};

const EVAL_TREND: TrendResponse = {
  points: [],
  baseline: null,
  has_data: false,
  sparks: {
    faithfulness: [],
    answer_relevancy: [],
    context_precision: [],
    context_recall: [],
    citation_precision: [],
    citation_recall: [],
    seed_hit_rate: [],
    routing_hit_rate: [],
  },
};

describe("评测数据 hooks", () => {
  beforeEach(() => {
    rs.mocked(api.getLatestEvalMetrics).mockResolvedValue(EVAL_OVERVIEW);
    rs.mocked(api.getEvalTrend).mockResolvedValue(EVAL_TREND);
  });

  it("useMetricsOverview fetches on enable and caches under the eval-latest key", async () => {
    const queryClient = freshQueryClient();
    const { result } = renderHook(() => useMetricsOverview("kb-1", true), {
      wrapper: createWrapper(queryClient),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.getLatestEvalMetrics).toHaveBeenCalledWith("kb-1");
    expect(queryClient.getQueryData(knowledgeEvalLatestKey("kb-1"))).toEqual(EVAL_OVERVIEW);
    // staleTime 30s：刚取回的数据保持 fresh，keep-alive 来回切不重复请求
    expect(result.current.isStale).toBe(false);
  });

  it("enabled=false does not send requests (keep-alive 门控)", async () => {
    renderHook(() => useMetricsOverview("kb-1", false), {
      wrapper: createWrapper(freshQueryClient()),
    });
    renderHook(() => useEvalTrend("kb-1", false), {
      wrapper: createWrapper(freshQueryClient()),
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.getLatestEvalMetrics).not.toHaveBeenCalled();
    expect(api.getEvalTrend).not.toHaveBeenCalled();
  });

  it("trend query caches under a single key (contract v4: no granularity dimension)", async () => {
    const queryClient = freshQueryClient();
    const { result } = renderHook(() => useEvalTrend("kb-1", true), {
      wrapper: createWrapper(queryClient),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // 服务端一次给 90d run 级点：请求无粒度参数，键无粒度维度
    expect(api.getEvalTrend).toHaveBeenCalledWith("kb-1");
    expect(queryClient.getQueryData(knowledgeEvalTrendKey("kb-1"))).toEqual(EVAL_TREND);
  });

  it("null kbId keeps the queries disabled", async () => {
    renderHook(() => useMetricsOverview(null, true), {
      wrapper: createWrapper(freshQueryClient()),
    });
    renderHook(() => useEvalTrend(null, true), {
      wrapper: createWrapper(freshQueryClient()),
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.getLatestEvalMetrics).not.toHaveBeenCalled();
    expect(api.getEvalTrend).not.toHaveBeenCalled();
  });
});

describe("useEvalRun（drawer 下钻数据源，plan Task 6）", () => {
  const RUN_DETAIL: EvalRunDetail = {
    run_id: "run-1",
    kb_id: "kb-1",
    status: "completed",
    environment: "local",
    created_at: "2026-08-20T09:00:00+00:00",
    layer1_metrics: {},
    layer2_metrics: {},
    is_baseline: false,
  };

  beforeEach(() => {
    rs.mocked(api.getEvalRun).mockResolvedValue(RUN_DETAIL);
  });

  it("fetches only when both kbId and runId are set, caching under the run key", async () => {
    const queryClient = freshQueryClient();
    const { rerender } = renderHook(
      ({ runId }) => useEvalRun("kb-1", runId),
      { initialProps: { runId: null as string | null }, wrapper: createWrapper(queryClient) },
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.getEvalRun).not.toHaveBeenCalled();

    rerender({ runId: "run-1" });
    await waitFor(() => expect(api.getEvalRun).toHaveBeenCalledWith("kb-1", "run-1"));
    expect(queryClient.getQueryData(knowledgeEvalRunKey("kb-1", "run-1"))).toEqual(RUN_DETAIL);
  });
});

// ── 评测二期数据 hooks（2026-08-27 spec §4–§6，plan Task 4）──────────────

const EVAL_QUESTIONS_PAGE: EvalQuestionListResponse = {
  questions: [
    {
      id: "q_ab12cd34",
      query: "什么是退休年龄",
      category: "fact",
      expected_paths: ["vector"],
      relevant_chunk_ids: [],
      relevant_entities: [],
      reference_answer: null,
    },
  ],
  total: 1,
};

const EVAL_RUNS_IDLE: EvalRunListResponse = { in_flight: false, runs: [], total: 0 };

describe("评测二期数据 hooks（plan Task 4）", () => {
  beforeEach(() => {
    rs.mocked(api.listEvalQuestions).mockResolvedValue(EVAL_QUESTIONS_PAGE);
    rs.mocked(api.listEvalRuns).mockResolvedValue(EVAL_RUNS_IDLE);
    rs.mocked(api.triggerEvalRun).mockResolvedValue({ status: "enqueued" });
    rs.mocked(api.deleteEvalQuestion).mockResolvedValue(undefined);
  });

  it("useEvalQuestions fetches when enabled and caches under its kb-scoped key", async () => {
    const queryClient = freshQueryClient();
    const { result } = renderHook(() => useEvalQuestions("kb-1", true), {
      wrapper: createWrapper(queryClient),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.listEvalQuestions).toHaveBeenCalledWith("kb-1");
    expect(queryClient.getQueryData(knowledgeEvalQuestionsKey("kb-1"))).toEqual(EVAL_QUESTIONS_PAGE);
  });

  it("useEvalRuns fetches when enabled and caches under the history key", async () => {
    const queryClient = freshQueryClient();
    const { result } = renderHook(() => useEvalRuns("kb-1", true), {
      wrapper: createWrapper(queryClient),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.listEvalRuns).toHaveBeenCalledWith("kb-1");
    expect(queryClient.getQueryData(knowledgeEvalRunsKey("kb-1"))).toEqual(EVAL_RUNS_IDLE);
  });

  it("enabled=false keeps both new queries silent (keep-alive 门控)", async () => {
    renderHook(() => useEvalQuestions("kb-1", false), { wrapper: createWrapper(freshQueryClient()) });
    renderHook(() => useEvalRuns("kb-1", false), { wrapper: createWrapper(freshQueryClient()) });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.listEvalQuestions).not.toHaveBeenCalled();
    expect(api.listEvalRuns).not.toHaveBeenCalled();
  });

  it("delete mutation invalidates the questions cache (refetch after success)", async () => {
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const list = renderHook(() => useEvalQuestions("kb-1", true), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));

    const del = renderHook(() => useDeleteEvalQuestion("kb-1"), { wrapper });
    await del.result.current.mutateAsync("q_ab12cd34");

    expect(api.deleteEvalQuestion).toHaveBeenCalledWith("kb-1", "q_ab12cd34");
    await waitFor(() => expect(api.listEvalQuestions).toHaveBeenCalledTimes(2));
  });

  it("add mutation invalidates the questions cache", async () => {
    rs.mocked(api.createEvalQuestion).mockResolvedValue({
      id: "q_new00001",
      query: "新考题",
      category: "relation",
      expected_paths: ["graph"],
      relevant_chunk_ids: [],
      relevant_entities: [],
      reference_answer: null,
    });
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const list = renderHook(() => useEvalQuestions("kb-1", true), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));

    const add = renderHook(() => useAddEvalQuestion("kb-1"), { wrapper });
    await add.result.current.mutateAsync({
      query: "新考题",
      category: "relation",
      expected_paths: ["graph"],
    });

    expect(rs.mocked(api.createEvalQuestion).mock.calls[0]?.[0]).toEqual("kb-1");
    await waitFor(() => expect(api.listEvalQuestions).toHaveBeenCalledTimes(2));
  });

  it("update mutation routes the anchor body and invalidates the questions cache", async () => {
    rs.mocked(api.updateEvalQuestion).mockResolvedValue({
      id: "q_ab12cd34",
      query: "题目",
      category: "fact",
      expected_paths: ["vector"],
      relevant_chunk_ids: ["doc-1#0001"],
      relevant_entities: [],
      reference_answer: null,
    });
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const list = renderHook(() => useEvalQuestions("kb-1", true), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));

    const update = renderHook(() => useUpdateEvalQuestion("kb-1"), { wrapper });
    await update.result.current.mutateAsync({
      questionId: "q_ab12cd34",
      body: { relevant_chunk_ids: ["doc-1#0001"] },
    });

    expect(api.updateEvalQuestion).toHaveBeenCalledWith("kb-1", "q_ab12cd34", { relevant_chunk_ids: ["doc-1#0001"] });
    // 改锚成功 → 题库缓存失效（行级切片数/悬空徽章即时收敛）。
    await waitFor(() => expect(api.listEvalQuestions).toHaveBeenCalledTimes(2));
  });

  it("useTriggerEvalRun passes the trigger response straight through", async () => {
    const { result } = renderHook(() => useTriggerEvalRun("kb-1"), {
      wrapper: createWrapper(freshQueryClient()),
    });
    const response = await result.current.mutateAsync({});
    expect(response).toEqual({ status: "enqueued" });
    // 无参默认 = 空载荷（后端默认 L1 全量，旧契约兼容）。
    expect(api.triggerEvalRun).toHaveBeenCalledWith("kb-1", {});
  });

  it("useTriggerEvalRun forwards tier and selection payload（2026-09-01 B 方案）", async () => {
    const { result } = renderHook(() => useTriggerEvalRun("kb-1"), {
      wrapper: createWrapper(freshQueryClient()),
    });
    await result.current.mutateAsync({ layers: "l1_l2", question_ids: ["q1", "q2"] });
    expect(api.triggerEvalRun).toHaveBeenCalledWith("kb-1", { layers: "l1_l2", question_ids: ["q1", "q2"] });
  });
});

describe("evalRunsRefetchInterval（纯函数，spec §5.3）", () => {
  it("polls at 3s only while in_flight", () => {
    expect(evalRunsRefetchInterval(undefined)).toBe(false);
    expect(evalRunsRefetchInterval({ in_flight: false, runs: [], total: 0 })).toBe(false);
    expect(evalRunsRefetchInterval({ in_flight: true, runs: [], total: 0 })).toBe(3000);
  });
});

// ── 合成造题数据层（2026-08-28 spec §6，plan Task 8）──────────────────

const SYNTH_CANDIDATE: SynthesisCandidate = {
  candidate_id: "c_a1b2c3d4",
  query: "String 有什么特点？",
  category: "fact",
  expected_paths: ["vector"],
  relevant_chunk_ids: ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa#0001"],
  relevant_entities: [],
  reference_answer: "不可变。",
  doc_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  generated_at: "2026-08-28T10:00:00+00:00",
};

const SYNTH_STATUS: SynthesisStatus = {
  in_progress: false,
  candidates: [SYNTH_CANDIDATE],
  generated_at: "2026-08-28T10:00:00+00:00",
  doc_ids: ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
  dropped: 0,
};

const ACCEPTED_QUESTION: EvalQuestion = {
  id: "q_new12345",
  query: SYNTH_CANDIDATE.query,
  category: SYNTH_CANDIDATE.category,
  expected_paths: SYNTH_CANDIDATE.expected_paths,
  relevant_chunk_ids: SYNTH_CANDIDATE.relevant_chunk_ids,
  relevant_entities: [],
  reference_answer: SYNTH_CANDIDATE.reference_answer,
};

describe("合成造题数据 hooks（plan Task 8）", () => {
  beforeEach(() => {
    rs.mocked(api.getSynthesisStatus).mockResolvedValue(SYNTH_STATUS);
    rs.mocked(api.listEvalQuestions).mockResolvedValue(EVAL_QUESTIONS_PAGE);
    rs.mocked(api.triggerQuestionSynthesis).mockResolvedValue({ status: "enqueued" });
    rs.mocked(api.acceptSynthesisCandidate).mockResolvedValue(ACCEPTED_QUESTION);
    rs.mocked(api.rejectSynthesisCandidate).mockResolvedValue(undefined);
  });

  it("knowledgeSynthesisKey is kb-scoped and distinct from the questions key", () => {
    expect(knowledgeSynthesisKey("kb-1")).toContain("kb-1");
    expect(knowledgeSynthesisKey("kb-1")).not.toEqual(knowledgeEvalQuestionsKey("kb-1"));
    expect(knowledgeSynthesisKey("kb-1")).not.toEqual(knowledgeSynthesisKey("kb-2"));
  });

  it("useSynthesisStatus fetches when enabled and caches under the synthesis key", async () => {
    const queryClient = freshQueryClient();
    const { result } = renderHook(() => useSynthesisStatus("kb-1", true), {
      wrapper: createWrapper(queryClient),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.getSynthesisStatus).toHaveBeenCalledWith("kb-1");
    expect(queryClient.getQueryData(knowledgeSynthesisKey("kb-1"))).toEqual(SYNTH_STATUS);
  });

  it("enabled=false keeps the synthesis query silent (keep-alive 门控)", async () => {
    renderHook(() => useSynthesisStatus("kb-1", false), { wrapper: createWrapper(freshQueryClient()) });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.getSynthesisStatus).not.toHaveBeenCalled();
  });

  it("useTriggerSynthesis passes the trigger response straight through", async () => {
    const { result } = renderHook(() => useTriggerSynthesis("kb-1"), {
      wrapper: createWrapper(freshQueryClient()),
    });
    const response = await result.current.mutateAsync({ doc_ids: ["doc-1"], count: 5 });
    expect(response).toEqual({ status: "enqueued" });
    expect(api.triggerQuestionSynthesis).toHaveBeenCalledWith("kb-1", { doc_ids: ["doc-1"], count: 5 });
  });

  it("trigger success invalidates the synthesis cache so polling can start", async () => {
    // 旧缓存 in_progress=false 会让轮询永不启动；触发后必须重拉一次拿到真值。
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const status = renderHook(() => useSynthesisStatus("kb-1", true), { wrapper });
    await waitFor(() => expect(status.result.current.isSuccess).toBe(true));
    expect(api.getSynthesisStatus).toHaveBeenCalledTimes(1);

    const trigger = renderHook(() => useTriggerSynthesis("kb-1"), { wrapper });
    await trigger.result.current.mutateAsync({ doc_ids: ["doc-1"], count: 5 });

    await waitFor(() => expect(api.getSynthesisStatus).toHaveBeenCalledTimes(2));
  });

  it("accept mutation invalidates both synthesis and evalQuestions caches", async () => {
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const status = renderHook(() => useSynthesisStatus("kb-1", true), { wrapper });
    const questions = renderHook(() => useEvalQuestions("kb-1", true), { wrapper });
    await waitFor(() => expect(status.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(questions.result.current.isSuccess).toBe(true));

    const accept = renderHook(() => useAcceptSynthesisCandidate("kb-1"), { wrapper });
    const question = await accept.result.current.mutateAsync({ candidate_id: "c_a1b2c3d4" });

    expect(question.id).toBe("q_new12345");
    // anchor_ack 缺省保持 bodyless 旧契约（api 层默认 false，不发确认体）。
    expect(api.acceptSynthesisCandidate).toHaveBeenCalledWith("kb-1", "c_a1b2c3d4", false);
    await waitFor(() => expect(api.getSynthesisStatus).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.listEvalQuestions).toHaveBeenCalledTimes(2));
  });

  it("reject mutation invalidates both synthesis and evalQuestions caches", async () => {
    const queryClient = freshQueryClient();
    const wrapper = createWrapper(queryClient);
    const status = renderHook(() => useSynthesisStatus("kb-1", true), { wrapper });
    const questions = renderHook(() => useEvalQuestions("kb-1", true), { wrapper });
    await waitFor(() => expect(status.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(questions.result.current.isSuccess).toBe(true));

    const reject = renderHook(() => useRejectSynthesisCandidate("kb-1"), { wrapper });
    await reject.result.current.mutateAsync("c_a1b2c3d4");

    expect(api.rejectSynthesisCandidate).toHaveBeenCalledWith("kb-1", "c_a1b2c3d4");
    await waitFor(() => expect(api.getSynthesisStatus).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.listEvalQuestions).toHaveBeenCalledTimes(2));
  });
});

describe("synthesisRefetchInterval（纯函数，与 eval-run-status 同款）", () => {
  it("polls at 3s only while in_progress", () => {
    expect(synthesisRefetchInterval(undefined)).toBe(false);
    expect(synthesisRefetchInterval({ ...SYNTH_STATUS, in_progress: false })).toBe(false);
    expect(synthesisRefetchInterval({ ...SYNTH_STATUS, in_progress: true })).toBe(3000);
  });
});
