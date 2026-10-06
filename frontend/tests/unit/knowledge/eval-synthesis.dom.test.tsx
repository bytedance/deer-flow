/**
 * 合成造题前端契约测试（2026-08-28 spec §6，plan Task 11）：
 * - 触发 dialog：文档多选清单 + 数量选择；未勾选禁用；提交体 {doc_ids, count}；
 *   enqueued → success toast 并关闭，already_running → info toast 不关闭；
 *   2026-09-02 起支持多篇联合出题（路线二）：清单多选、提交携带全部勾选 id。
 * - 审核面板：暂存空且非运行中不渲染；候选卡片字段全量；采纳/忽略/全部忽略
 *   分别驱动 accept/reject mutation；in_progress 显示「生成中…」。
 * - B′ 锚定拦截（2026-10-05）：采纳被锚定核验 422 拦下时候选卡出红块（无错误
 *   toast），原「采纳」重提恒不带确认，仅红块内「仍要接受」携 anchor_ack=true
 *   入库；missing_chunk 红块无确认钮（不可绕过）。
 *
 * 轮询门控（refetchInterval）已在 hooks.dom.test（Task 8）钉死，此处不重复。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { toast } from "sonner";

const hooksMock = rs.hoisted(() => ({
  useSynthesisStatus: rs.fn(),
  useTriggerSynthesis: rs.fn(),
  useAcceptSynthesisCandidate: rs.fn(),
  useRejectSynthesisCandidate: rs.fn(),
  useDocuments: rs.fn(),
}));

rs.mock("@/core/knowledge/hooks", () => hooksMock);

rs.mock("sonner", () => ({
  toast: { error: rs.fn(), success: rs.fn(), info: rs.fn(), warning: rs.fn() },
}));

import { EvalSynthesisDialog } from "@/components/workspace/knowledge/eval-synthesis-dialog";
import { EvalSynthesisReview } from "@/components/workspace/knowledge/eval-synthesis-review";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { AnchorBlockError } from "@/core/knowledge/api";
import type {
  AnchorBlockDetail,
  KnowledgeDocument,
  SynthesisCandidate,
  SynthesisStatus,
} from "@/core/knowledge/types";

const DOC = "a".repeat(32);

const READY_DOC: KnowledgeDocument = {
  id: DOC,
  kb_id: "kb-1",
  uploader_id: "user-1",
  name: "Java 并发.md",
  size_bytes: 100,
  storage_path: "p",
  status: "ready",
  progress_percent: 100,
  chunk_count: 12,
  error: null,
  path_status: null,
  content_hash: null,
  created_at: "2026-08-28T09:00:00Z",
};

const INDEXING_DOC: KnowledgeDocument = { ...READY_DOC, id: "b".repeat(32), name: "索引中.pdf", status: "indexing", chunk_count: 0 };
const READY_DOC_2: KnowledgeDocument = { ...READY_DOC, id: "c".repeat(32), name: "集合框架.md" };

const CAND_1: SynthesisCandidate = {
  candidate_id: "c_aaaa1111",
  query: "String 有什么特点？",
  category: "fact",
  expected_paths: ["vector"],
  relevant_chunk_ids: [`${DOC}#0001`],
  relevant_entities: [],
  reference_answer: "String 是不可变类型。",
  doc_id: DOC,
  generated_at: "2026-08-28T10:00:00+00:00",
};

const CAND_2: SynthesisCandidate = {
  candidate_id: "c_bbbb2222",
  query: "两个可变字符串类有什么关系？",
  category: "relation",
  expected_paths: ["vector", "graph"],
  relevant_chunk_ids: [`${DOC}#0002`, `${DOC}#0003`],
  relevant_entities: [],
  reference_answer: null,
  doc_id: DOC,
  generated_at: "2026-08-28T10:00:00+00:00",
};

const STATUS_WITH_CANDIDATES: SynthesisStatus = {
  in_progress: false,
  candidates: [CAND_1, CAND_2],
  generated_at: "2026-08-28T10:00:00+00:00",
  doc_ids: [DOC],
  dropped: 2,
};

const STATUS_EMPTY: SynthesisStatus = { in_progress: false, candidates: [], generated_at: null, doc_ids: [], dropped: 0 };

function renderWithI18n(ui: ReactElement) {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      {ui}
    </I18nContext.Provider>,
  );
}

beforeEach(() => {
  hooksMock.useSynthesisStatus.mockReset();
  hooksMock.useTriggerSynthesis.mockReset();
  hooksMock.useAcceptSynthesisCandidate.mockReset();
  hooksMock.useRejectSynthesisCandidate.mockReset();
  hooksMock.useDocuments.mockReset();
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("EvalSynthesisDialog（触发）", () => {
  function renderDialog(onOpenChange = rs.fn()) {
    const mutateAsync = rs.fn().mockResolvedValue({ status: "enqueued" });
    hooksMock.useDocuments.mockReturnValue({ data: [READY_DOC, INDEXING_DOC, READY_DOC_2], isLoading: false });
    hooksMock.useTriggerSynthesis.mockReturnValue({ mutateAsync, isPending: false });
    renderWithI18n(<EvalSynthesisDialog kbId="kb-1" onOpenChange={onOpenChange} open />);
    return { mutateAsync, onOpenChange };
  }

  it("未勾选时提交禁用；清单只列已索引文档", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "生成" }).hasAttribute("disabled")).toBe(true);

    // 已索引文档进清单；索引中文档不进（后端无切片必 409——前端预过滤减错）
    expect(screen.getByText("Java 并发.md")).toBeTruthy();
    expect(screen.getByText("集合框架.md")).toBeTruthy();
    expect(screen.queryByText("索引中.pdf")).toBeNull();
  });

  it("多选勾选后提交携带全部 {doc_ids, count}；enqueued → success toast 并关闭", async () => {
    const { mutateAsync, onOpenChange } = renderDialog();

    // 勾选两篇：清单行即复选目标，逐行点击。
    fireEvent.click(screen.getByText("Java 并发.md"));
    fireEvent.click(screen.getByText("集合框架.md"));
    expect(screen.getByRole("button", { name: "生成" }).hasAttribute("disabled")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "生成" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith({ doc_ids: [DOC, "c".repeat(32)], count: 5 }));
    await waitFor(() => {
      expect(rs.mocked(toast.success).mock.calls.length).toBeGreaterThan(0);
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("再点已勾选项可取消勾选；全部取消后提交重新禁用", () => {
    renderDialog();
    fireEvent.click(screen.getByText("Java 并发.md"));
    expect(screen.getByRole("button", { name: "生成" }).hasAttribute("disabled")).toBe(false);
    fireEvent.click(screen.getByText("Java 并发.md"));
    expect(screen.getByRole("button", { name: "生成" }).hasAttribute("disabled")).toBe(true);
  });

  it("already_running → info toast 且不关闭 dialog", async () => {
    const { mutateAsync, onOpenChange } = renderDialog();
    mutateAsync.mockResolvedValue({ status: "already_running" });

    fireEvent.click(screen.getByText("Java 并发.md"));
    fireEvent.click(screen.getByRole("button", { name: "生成" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    await waitFor(() => {
      expect(rs.mocked(toast.info).mock.calls.length).toBeGreaterThan(0);
    });
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});

describe("EvalSynthesisReview（审核面板）", () => {
  function renderReview(status: SynthesisStatus) {
    const acceptAsync = rs.fn().mockResolvedValue({ id: "q_new12345", query: CAND_1.query });
    const rejectAsync = rs.fn().mockResolvedValue(undefined);
    hooksMock.useSynthesisStatus.mockReturnValue({ data: status, isLoading: false });
    hooksMock.useAcceptSynthesisCandidate.mockReturnValue({ mutateAsync: acceptAsync, isPending: false });
    hooksMock.useRejectSynthesisCandidate.mockReturnValue({ mutateAsync: rejectAsync, isPending: false });
    // 来源文档标题（ⓘ tooltip 用）：与参考文档列同 queryKey。
    hooksMock.useDocuments.mockReturnValue({ data: [READY_DOC, READY_DOC_2], isLoading: false });
    renderWithI18n(<EvalSynthesisReview enabled kbId="kb-1" />);
    return { acceptAsync, rejectAsync };
  }

  it("常驻：暂存空显单行头空态（无 toggle/候选区，不白占分高）", () => {
    renderReview(STATUS_EMPTY);
    expect(screen.getByText(zhCN.knowledge.eval.synthesize.reviewTitle)).toBeTruthy();
    expect(screen.getByText(zhCN.knowledge.eval.synthesize.empty)).toBeTruthy();
    expect(screen.queryByTestId("eval-synthesis-review-toggle")).toBeNull();
    expect(screen.queryByText(CAND_1.query)).toBeNull();
  });

  it("候选卡片字段全量 + 元信息 salvage（计数徽章/丢弃芯片/ⓘ tooltip，裸行退役）", async () => {
    renderReview(STATUS_WITH_CANDIDATES);
    expect(screen.getByText(zhCN.knowledge.eval.synthesize.reviewTitle)).toBeTruthy();
    expect(screen.getByText(CAND_1.query)).toBeTruthy();
    expect(screen.getByText(CAND_2.query)).toBeTruthy();
    // category 显示名走 i18n；多路 Badge 全量
    expect(screen.getByText("事实")).toBeTruthy();
    expect(screen.getByText("关系")).toBeTruthy();
    expect(screen.getAllByText("vector").length).toBe(2);
    expect(screen.getByText("graph")).toBeTruthy();
    // 参考切片计数与题库参考切片列同语言（2026-10-06 列口径改造：纯数字 =
    // 切片数，无量词混排；CAND_2 两切片同文档仍显 2——采纳前后同一单位）。
    expect(screen.getByText("1")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
    expect(screen.queryByText(/篇/)).toBeNull();
    expect(screen.getByText("String 是不可变类型。")).toBeTruthy();
    // 计数徽章带单位（替换原裸数字）；丢弃 >0 显琥珀芯片，原因沉 tooltip。
    expect(screen.getByText("2 条待审")).toBeTruthy();
    expect(screen.getByText("丢弃 2 条")).toBeTruthy();
    // 计数徽章 = 琥珀「圆点+文字」胶囊（wiki 待更新同款配方），比灰胶囊显眼。
    const badge = screen.getByText("2 条待审").closest("span")!;
    expect(badge.className).toContain("amber");
    expect(badge.querySelector("span[aria-hidden]")).toBeTruthy();
    // 候选卡边框加深一档（卡容器内边际清晰）。
    expect(screen.getByText(CAND_1.query).closest("div")!.className).toContain("border-foreground/20");
    // 裸 doc_id 与裸 ISO 不再渲染；来源标题+相对时间收进 ⓘ tooltip 的 aria-label。
    expect(screen.queryByText(DOC)).toBeNull();
    expect(screen.queryByText("2026-08-28T10:00:00+00:00")).toBeNull();
    const metaTip = screen.getByRole("button", { name: /来自/ }).getAttribute("aria-label")!;
    expect(metaTip).toContain("Java 并发.md");
    expect(metaTip).toContain("生成于");
    // 批量动作收进标题行右键菜单（wiki-panel 头部右键先例）：右键头部得
    // 全部采纳 → 全部忽略（头部不再留动作钮）。
    expect(screen.queryByRole("button", { name: "全部采纳" })).toBeNull();
    fireEvent.contextMenu(screen.getByTestId("eval-synthesis-review-toggle"));
    expect((await screen.findAllByRole("menuitem")).map((item) => item.textContent)).toEqual(["全部采纳", "全部忽略"]);
  });

  it("多篇来源 → ⓘ tooltip 顿号连接（≤2 篇全列）", () => {
    const second = "c".repeat(32);
    renderReview({ ...STATUS_WITH_CANDIDATES, doc_ids: [DOC, second] });
    const metaTip = screen.getByRole("button", { name: /来自/ }).getAttribute("aria-label")!;
    expect(metaTip).toContain("Java 并发.md、集合框架.md");
  });

  it("收起：只留单行头、候选区卸载；计数徽章留头部；再点展开", () => {
    renderReview(STATUS_WITH_CANDIDATES);
    const toggle = screen.getByTestId("eval-synthesis-review-toggle");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(CAND_1.query)).toBeNull();
    // 收起态头部仍承载「有待审」信号（徽章）；批量动作在右键菜单。
    expect(screen.getByText("2 条待审")).toBeTruthy();
    fireEvent.click(toggle);
    expect(screen.getByText(CAND_1.query)).toBeTruthy();
  });

  it("采纳 → accept mutation 携带 candidate_id 并发成功 toast", async () => {
    const { acceptAsync } = renderReview(STATUS_WITH_CANDIDATES);
    const acceptButtons = screen.getAllByRole("button", { name: "采纳" });
    fireEvent.click(acceptButtons[0]!);
    await waitFor(() => expect(acceptAsync).toHaveBeenCalledWith({ candidate_id: "c_aaaa1111", anchor_ack: false }));
    await waitFor(() => {
      expect(rs.mocked(toast.success).mock.calls.some(([m]) => m === "考题已添加")).toBe(true);
    });
  });

  it("忽略 → reject mutation 携带 candidate_id", async () => {
    const { rejectAsync } = renderReview(STATUS_WITH_CANDIDATES);
    const rejectButtons = screen.getAllByRole("button", { name: "忽略" });
    fireEvent.click(rejectButtons[1]!);
    await waitFor(() => expect(rejectAsync).toHaveBeenCalledWith("c_bbbb2222"));
  });

  it("全部忽略（标题行右键菜单）→ 逐条 reject 每个候选", async () => {
    const { rejectAsync } = renderReview(STATUS_WITH_CANDIDATES);
    fireEvent.contextMenu(screen.getByTestId("eval-synthesis-review-toggle"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "全部忽略" }));
    await waitFor(() => expect(rejectAsync).toHaveBeenCalledTimes(2));
    expect(rejectAsync).toHaveBeenNthCalledWith(1, "c_aaaa1111");
    expect(rejectAsync).toHaveBeenNthCalledWith(2, "c_bbbb2222");
  });

  it("全部采纳（标题行右键菜单）→ 逐条 accept 且只发一条成功 toast（不刷屏）", async () => {
    const { acceptAsync } = renderReview(STATUS_WITH_CANDIDATES);
    fireEvent.contextMenu(screen.getByTestId("eval-synthesis-review-toggle"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "全部采纳" }));
    await waitFor(() => expect(acceptAsync).toHaveBeenCalledTimes(2));
    expect(acceptAsync).toHaveBeenNthCalledWith(1, { candidate_id: "c_aaaa1111", anchor_ack: false });
    expect(acceptAsync).toHaveBeenNthCalledWith(2, { candidate_id: "c_bbbb2222", anchor_ack: false });
    await waitFor(() => {
      expect(rs.mocked(toast.success).mock.calls.length).toBe(1);
    });
  });

  it("候选卡右键菜单提供采纳/忽略（行级，携该候选 id）", async () => {
    const { acceptAsync, rejectAsync } = renderReview(STATUS_WITH_CANDIDATES);
    fireEvent.contextMenu(screen.getByText(CAND_2.query));
    fireEvent.click(await screen.findByRole("menuitem", { name: "忽略" }));
    await waitFor(() => expect(rejectAsync).toHaveBeenCalledWith("c_bbbb2222"));
    fireEvent.contextMenu(screen.getByText(CAND_1.query));
    fireEvent.click(await screen.findByRole("menuitem", { name: "采纳" }));
    await waitFor(() => expect(acceptAsync).toHaveBeenCalledWith({ candidate_id: "c_aaaa1111", anchor_ack: false }));
  });

  it("in_progress → 生成中文案", () => {
    renderReview({ ...STATUS_WITH_CANDIDATES, in_progress: true, candidates: [] });
    expect(screen.getByText("生成中…")).toBeTruthy();
  });

  // ── B′ 锚定拦截（2026-10-05）────────────────────────────────────────
  const BLOCK_DETAIL: AnchorBlockDetail = {
    reason: "mismatch",
    miss_terms: ["装箱"],
    hits: 1,
    best_hits: 3,
    suggested_chunk: "abc#0001",
  };

  function renderReviewWithAccept(acceptAsync: ReturnType<typeof rs.fn>) {
    hooksMock.useSynthesisStatus.mockReturnValue({ data: STATUS_WITH_CANDIDATES, isLoading: false });
    hooksMock.useAcceptSynthesisCandidate.mockReturnValue({ mutateAsync: acceptAsync, isPending: false });
    hooksMock.useRejectSynthesisCandidate.mockReturnValue({ mutateAsync: rs.fn().mockResolvedValue(undefined), isPending: false });
    hooksMock.useDocuments.mockReturnValue({ data: [READY_DOC, READY_DOC_2], isLoading: false });
    renderWithI18n(<EvalSynthesisReview enabled kbId="kb-1" />);
  }

  it("B′：首击被拦落红块（无错误 toast），原「采纳」重提恒无确认，「仍要接受」携 anchor_ack=true 入库", async () => {
    const acceptAsync = rs
      .fn()
      .mockRejectedValueOnce(new AnchorBlockError(BLOCK_DETAIL))
      .mockRejectedValueOnce(new AnchorBlockError(BLOCK_DETAIL))
      .mockResolvedValue({ id: "q_new12345", query: CAND_1.query });
    renderReviewWithAccept(acceptAsync);

    fireEvent.click(screen.getAllByRole("button", { name: "采纳" })[0]!);
    const block = await screen.findByRole("alert");
    expect(block.textContent).toContain("装箱");
    expect(screen.getByRole("button", { name: "仍要接受" })).toBeTruthy();
    expect(rs.mocked(toast.error)).not.toHaveBeenCalled();

    // 原按钮保留原文案，再点仍是无确认重提（盲双击不绕过）。
    fireEvent.click(screen.getAllByRole("button", { name: "采纳" })[0]!);
    await waitFor(() => expect(acceptAsync).toHaveBeenCalledTimes(2));
    expect((acceptAsync.mock.calls[1]?.[0] as { anchor_ack?: boolean }).anchor_ack).toBeFalsy();
    expect(screen.getAllByRole("button", { name: "采纳" })).toHaveLength(2);

    // 红块内「仍要接受」→ anchor_ack=true → 正常采纳收尾（成功 toast + 红块退场）。
    fireEvent.click(screen.getByRole("button", { name: "仍要接受" }));
    await waitFor(() => expect(acceptAsync).toHaveBeenCalledTimes(3));
    expect((acceptAsync.mock.calls[2]?.[0] as { anchor_ack?: boolean }).anchor_ack).toBe(true);
    await waitFor(() => {
      expect(rs.mocked(toast.success).mock.calls.some(([m]) => m === "考题已添加")).toBe(true);
    });
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("B′ missing_chunk：红块渲染但无确认钮（不可绕过）", async () => {
    const acceptAsync = rs
      .fn()
      .mockRejectedValue(
        new AnchorBlockError({ reason: "missing_chunk", miss_terms: [], hits: 0, best_hits: 0, suggested_chunk: null }),
      );
    renderReviewWithAccept(acceptAsync);

    fireEvent.click(screen.getAllByRole("button", { name: "采纳" })[0]!);
    const block = await screen.findByRole("alert");
    expect(block.textContent).toContain(zhCN.knowledge.eval.anchorBlock.missing);
    expect(screen.queryByRole("button", { name: "仍要接受" })).toBeNull();
    expect(rs.mocked(toast.error)).not.toHaveBeenCalled();
  });
});
