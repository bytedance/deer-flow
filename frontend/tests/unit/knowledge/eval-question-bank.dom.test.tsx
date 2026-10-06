/**
 * 题库视图契约测试（2026-08-27 spec §4，plan Task 6；2026-10-06 改锚对列口径）：
 * - 表格三态（loading / 失败 / 数据）与参考切片列口径（纯数字 = 切片数、
 *   无量词混排；纯词「悬空」徽章仅 missing_chunk_ids 非空的行显）；
 * - 召回率@k 列三态点+百分比（最近一次 run 逐题 slim 指标 join）与未测 —；
 * - 行点击开详情 drawer；操作列 ↗/🗑 stopPropagation；
 * - 删除二次确认：取消不调 mutation，确认调并发成功 toast；
 * - 添加 dialog：必填校验、提交体不含锚定键（后端补空数组，spec §4.4）；
 * - 问题列悬浮走项目 Tooltip（断言无原生 title 属性）。
 *
 * hooks 经 mock 注入（对齐 eval-tab.dom.test 先例）；drawer mock 记录 props；
 * 添加 dialog 与详情 drawer 在独立 describe 内渲染真实组件直测。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState, type ComponentProps, type ReactElement } from "react";
import { toast } from "sonner";

import { EvalAddQuestionDialog } from "@/components/workspace/knowledge/eval-add-question-dialog";
import { EvalQuestionBank } from "@/components/workspace/knowledge/eval-question-bank";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { AnchorBlockError } from "@/core/knowledge/api";
import type { AnchorBlockDetail, EvalQuestion, EvalQuestionListResponse } from "@/core/knowledge/types";

const hooksMock = rs.hoisted(() => ({
  useEvalQuestions: rs.fn(),
  useAddEvalQuestion: rs.fn(),
  useDeleteEvalQuestion: rs.fn(),
  useSynthesisStatus: rs.fn(),
  useTriggerSynthesis: rs.fn(),
  useAcceptSynthesisCandidate: rs.fn(),
  useRejectSynthesisCandidate: rs.fn(),
  useDocuments: rs.fn(),
  useMetricsOverview: rs.fn(),
  useTriggerEvalRun: rs.fn(),
}));

rs.mock("@/core/knowledge/hooks", () => hooksMock);

rs.mock("sonner", () => ({
  toast: { error: rs.fn(), success: rs.fn(), info: rs.fn(), warning: rs.fn() },
}));

const drawerMock = rs.hoisted(() => ({
  props: undefined as Record<string, unknown> | undefined,
}));

rs.mock("@/components/workspace/knowledge/eval-question-drawer", () => ({
  EvalQuestionDrawer: (props: Record<string, unknown>) => {
    drawerMock.props = props;
    return props.open ? <div data-testid="eval-question-drawer-mock" /> : null;
  },
}));

const CHUNK_A = "a".repeat(32) + "#0001";
const CHUNK_B = "b".repeat(32) + "#0002";

const Q_UNANCHORED: EvalQuestion = {
  id: "q_11111111",
  query: "未锚定的考题",
  category: "global",
  expected_paths: ["wiki"],
  relevant_chunk_ids: [],
  relevant_entities: [],
  reference_answer: null,
};

const Q_ANCHORED: EvalQuestion = {
  id: "q_22222222",
  query: "锚定了三个切片的考题",
  category: "fact",
  expected_paths: ["vector"],
  relevant_chunk_ids: [CHUNK_A, CHUNK_B, "c".repeat(32) + "#0003"],
  relevant_entities: ["退休", "养老金"],
  reference_answer: "参考答案全文。",
};

const Q_MULTI: EvalQuestion = {
  id: "q_33333333",
  query: "多路预期的考题",
  category: "relation",
  expected_paths: ["vector", "graph"],
  relevant_chunk_ids: [CHUNK_A],
  relevant_entities: [],
  reference_answer: null,
};

/** 未测题（2026-09-07 排序用例）：question_results 无记录 → 召回列 —，排序恒沉底。 */
const Q_UNTESTED: EvalQuestion = {
  id: "q_44444444",
  query: "未测过的考题",
  category: "concept",
  expected_paths: ["vector"],
  relevant_chunk_ids: [],
  relevant_entities: [],
  reference_answer: null,
};

/** 悬空锚题（2026-10-06 spec §2②）：missing_chunk_ids 非空 → 行级「悬空」徽章。
    同文档两切片：格子显切片数 2（旧「N 篇」口径 = 1）——单位换轴的钉子。 */
const Q_DANGLING: EvalQuestion = {
  id: "q_55555555",
  query: "带悬空锚的考题",
  category: "concept",
  expected_paths: ["vector"],
  relevant_chunk_ids: [CHUNK_A, "a".repeat(32) + "#0002"],
  relevant_entities: [],
  reference_answer: null,
  missing_chunk_ids: ["a".repeat(32) + "#0002"],
};

/** 落空题（2026-10-06 spec §2④）：锚在、内容被换 → 读时派生 anchor_mismatch
    → 行级纯词「存疑」徽章 + Tooltip 机器依据（红块同款文案）。 */
const Q_SUSPECT: EvalQuestion = {
  id: "q_66666666",
  query: "内容被换的考题",
  category: "fact",
  expected_paths: ["vector"],
  relevant_chunk_ids: [CHUNK_A],
  relevant_entities: [],
  reference_answer: "装箱是把基本数据类型转换为包装类型。",
  anchor_mismatch: {
    reason: "zero_hit",
    miss_terms: ["装箱", "包装"],
    hits: 0,
    best_hits: 3,
    suggested_chunk: CHUNK_B,
    chunk_ids: [CHUNK_A],
  },
};

function questionsState(questions: EvalQuestion[]): { data: EvalQuestionListResponse } {
  return { data: { questions, total: questions.length } };
}

function renderWithI18n(ui: ReactElement) {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      {ui}
    </I18nContext.Provider>,
  );
}

/** 受控包装（2026-09-02 批量运行栏退役）：选题集上提 eval-tab，
    测试用有状态包装模拟上游；initialSelected 直接预置选中集。 */
type BankHarnessProps = Omit<ComponentProps<typeof EvalQuestionBank>, "selectedIds" | "onSelectedIdsChange" | "onTrigger"> & {
  initialSelected?: string[];
  onTrigger?: ComponentProps<typeof EvalQuestionBank>["onTrigger"];
};
function BankHarness({ initialSelected, onTrigger, ...rest }: BankHarnessProps) {
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set(initialSelected ?? []));
  return (
    <EvalQuestionBank
      {...rest}
      selectedIds={selectedIds}
      onSelectedIdsChange={setSelectedIds}
      onTrigger={onTrigger ?? (() => undefined)}
    />
  );
}

beforeEach(() => {
  drawerMock.props = undefined;
  hooksMock.useEvalQuestions.mockReset();
  hooksMock.useDeleteEvalQuestion.mockReset();
  hooksMock.useDeleteEvalQuestion.mockReturnValue({ mutateAsync: rs.fn().mockResolvedValue(undefined), isPending: false });
  // 合成状态默认空暂存（审核区块不渲染，既有用例不受影响）。
  hooksMock.useSynthesisStatus.mockReturnValue({
    data: { in_progress: false, candidates: [], generated_at: null, doc_ids: [], dropped: 0 },
    isLoading: false,
  });
  hooksMock.useDocuments.mockReturnValue({ data: [], isLoading: false });
  // 召回率@k 列缺省未测（data null → 全行 —）；三态用例自行覆盖。
  hooksMock.useMetricsOverview.mockReset();
  hooksMock.useMetricsOverview.mockReturnValue({ data: null });
  hooksMock.useTriggerSynthesis.mockReturnValue({ mutateAsync: rs.fn(), isPending: false });
  // 审核容器候选非空用例（2026-09-07 底部停靠）会走到 accept/reject 的 isPending，
  // 缺省兜底避免 undefined 解构。
  hooksMock.useAcceptSynthesisCandidate.mockReturnValue({ mutateAsync: rs.fn(), isPending: false });
  hooksMock.useRejectSynthesisCandidate.mockReturnValue({ mutateAsync: rs.fn(), isPending: false });
  hooksMock.useTriggerEvalRun.mockReset();
  hooksMock.useTriggerEvalRun.mockReturnValue({ mutate: rs.fn(), isPending: false });
});

afterEach(() => {
  cleanup();
});

describe("EvalQuestionBank 表格", () => {
  it("loading 渲染加载提示", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: true, error: null, data: undefined });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    expect(screen.getByText("加载中…")).toBeTruthy();
  });

  it("错误渲染加载失败提示", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: new Error("boom"), data: undefined });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    expect(screen.getByText("评测数据加载失败")).toBeTruthy();
  });

  it("空题库渲染引导文案（双入口：召回面板存题 + 文档合成）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([]) });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    expect(screen.getByText("题库为空——在召回测试面板勾选正确切片可一键存为考题")).toBeTruthy();
    // 双入口第二句（2026-08-28 §7）：合成造题引导。
    expect(screen.getByText("或从文档合成候选题，审核后采纳入题库")).toBeTruthy();
  });

  it("受控 synthesisOpen 渲染合成 dialog（入口已并入 eval-tab 常驻工具栏）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([]) });
    renderWithI18n(<BankHarness enabled kbId="kb-1" synthesisOpen />);
    expect(screen.getByText(zhCN.knowledge.eval.synthesize.dialogTitle)).toBeTruthy();
  });

  it("不自渲染造题入口按钮（工具行与底部虚线按钮均移除）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_ANCHORED]) });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    expect(screen.queryByRole("button", { name: /生成考题/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /添加考题/ })).toBeNull();
  });

  it("行渲染与参考切片列（2026-10-06 列口径：纯数字=切片数；纯词「悬空」徽章仅悬空题显）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({
      isLoading: false,
      error: null,
      ...questionsState([Q_UNANCHORED, Q_ANCHORED, Q_DANGLING]),
    });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    expect(screen.getByText("未锚定的考题")).toBeTruthy();
    expect(screen.getByText("锚定了三个切片的考题")).toBeTruthy();
    // 参考切片格（2026-10-06 列口径改造：数字与中文量词不在数值格混排）：
    // 纯数字 = relevant_chunk_ids.length，无「篇/切片」量词词尾。
    const anchoredRow = screen.getByText("锚定了三个切片的考题").closest("tr")!;
    const anchoredCell = within(anchoredRow as HTMLElement).getByText("3").closest("td")!;
    expect(anchoredCell.textContent).toBe("3");
    // 数值列右对齐（同文档 tab 数值列 text-right tabular-nums 同轴语言）。
    expect(anchoredCell.className).toContain("text-right");
    expect(anchoredCell.className).toContain("tabular-nums");
    // 健康行（missing_chunk_ids 缺省）无「悬空」徽章。
    expect(within(anchoredRow as HTMLElement).queryByText("悬空")).toBeNull();
    // 悬空题：同文档两切片 → 格子显 2（旧「N 篇」口径 = 1，单位换轴钉子），
    // 加纯词「悬空」徽章（无数字无图标）。
    const danglingRow = screen.getByText("带悬空锚的考题").closest("tr")!;
    const danglingCell = within(danglingRow as HTMLElement).getByText("2").closest("td")!;
    expect(danglingCell.textContent).toContain("2");
    expect(danglingCell.textContent).not.toContain("篇");
    expect(within(danglingRow as HTMLElement).getByText("悬空")).toBeTruthy();
    // 无锚定题：数字与徽章都不上行（与召回列 — 互相呼应）。
    const unanchoredRow = screen.getByText("未锚定的考题").closest("tr")!;
    expect(within(unanchoredRow as HTMLElement).queryByText(/篇/)).toBeNull();
    expect(within(unanchoredRow as HTMLElement).queryByText("悬空")).toBeNull();
    expect(within(unanchoredRow as HTMLElement).queryByText("未锚定")).toBeNull();
    // 分类显示名走 i18n（wire 键不外露）
    expect(screen.getByText("事实")).toBeTruthy();
    expect(screen.getByText("全局")).toBeTruthy();
  });

  it("落空题行级纯词「存疑」徽章 + Tooltip 机器依据（spec §2④，B1=甲）", async () => {
    hooksMock.useEvalQuestions.mockReturnValue({
      isLoading: false,
      error: null,
      ...questionsState([Q_ANCHORED, Q_SUSPECT]),
    });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    // 有疑才显：健康行零徽章。
    const healthyRow = screen.getByText("锚定了三个切片的考题").closest("tr")!;
    expect(within(healthyRow as HTMLElement).queryByText("存疑")).toBeNull();
    const suspectRow = screen.getByText("内容被换的考题").closest("tr")!;
    expect(within(suspectRow as HTMLElement).getByText("存疑")).toBeTruthy();
    // 悬浮＝项目 Tooltip 机器依据（红块同款文案：缺失术语 + 建议锚 + 命中表），
    // 无原生 title。
    const badge = within(suspectRow as HTMLElement).getByText("存疑");
    expect(badge.closest("[title]")).toBeNull();
    fireEvent.focus(badge.parentElement!);
    const tooltips = await screen.findAllByRole("tooltip");
    const evidence = tooltips.map((node) => node.textContent ?? "").join("\n");
    expect(evidence).toContain("缺失术语");
    expect(evidence).toContain("建议锚");
    expect(evidence).toContain("命中");
  });

  it("表头为 问题/分类/参考切片/召回率@k（预期路径与锚定列退役）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_MULTI]) });
    const { container } = renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    const heads = [...container.querySelectorAll("th")].map((th) => th.textContent);
    expect(heads).toEqual(["", "问题", "分类", "参考切片", "召回率@k", ""]);
    // 预期路径 Badge 不再行级出现（配置契约收抽屉）。
    expect(screen.queryByText("vector")).toBeNull();
    expect(screen.queryByText("graph")).toBeNull();
  });

  it("问题列悬浮走项目 Tooltip（无原生 title 属性，2026-10-06 悬浮统一）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_ANCHORED]) });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    const queryCell = screen.getByText(Q_ANCHORED.query).closest("td")!;
    expect(queryCell.getAttribute("title")).toBeNull();
    expect(queryCell.querySelector("[title]")).toBeNull();
    // 项目 Tooltip 组件（Radix 主题样式）承接悬浮——触发器即 span 本身
    // （TooltipTrigger asChild 合并 data-slot）。
    expect(queryCell.querySelector("[data-slot='tooltip-trigger']")).toBeTruthy();
  });

  it("召回率@k 列三态点+百分比（最近一次 run 逐题 slim 指标 join）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_UNANCHORED, Q_ANCHORED, Q_MULTI]) });
    hooksMock.useMetricsOverview.mockReturnValue({
      data: {
        kb_id: "kb-1",
        layer1: {
          run_id: "run-1",
          created_at: "2026-09-07T00:00:00+00:00",
          metrics: {
            summary: { hit_rate: 1, recall_at_k: 1, mrr: 1, path_accuracy: 1, question_count: 3 },
            top_k: 5,
          },
        },
        layer2: null,
        // 跨 run 合并的逐题最近结果（scoped run 不覆盖其它题）。
        question_results: [
          { id: Q_ANCHORED.id, recall: 1, hit: 1, path_correct: true, actual_path: "vector", run_id: "run-1", created_at: "2026-09-07T00:00:00+00:00" },
          { id: Q_MULTI.id, recall: 0.5, hit: 1, path_correct: true, actual_path: "graph", run_id: "run-1", created_at: "2026-09-07T00:00:00+00:00" },
          { id: Q_UNANCHORED.id, recall: 0, hit: 0, path_correct: false, actual_path: null, run_id: "run-1", created_at: "2026-09-07T00:00:00+00:00" },
        ],
      },
    });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    // 列头 @k 显具体值（top_k 透传自 run meta）。
    expect(screen.getByText("召回率@5")).toBeTruthy();
    const anchoredRow = screen.getByText("锚定了三个切片的考题").closest("tr")!;
    expect(within(anchoredRow as HTMLElement).getByText("100.0%")).toBeTruthy();
    expect(anchoredRow.innerHTML).toContain("bg-emerald-500");
    const multiRow = screen.getByText("多路预期的考题").closest("tr")!;
    expect(within(multiRow as HTMLElement).getByText("50.0%")).toBeTruthy();
    expect(multiRow.innerHTML).toContain("bg-lime-500");
    const unanchoredRow = screen.getByText("未锚定的考题").closest("tr")!;
    expect(within(unanchoredRow as HTMLElement).getByText("0.0%")).toBeTruthy();
    expect(unanchoredRow.innerHTML).toContain("bg-destructive");
  });

  it("召回列未测显 —（latest 无数据 / 旧运行行无 questions 键同待遇）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_UNANCHORED, Q_ANCHORED, Q_MULTI]) });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    expect(screen.getAllByText("—")).toHaveLength(3);
  });

  it("表头最右悬浮排序钮：默认隐形、激活常驻；召回率@k 排序未测沉底", async () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_ANCHORED, Q_MULTI, Q_UNANCHORED, Q_UNTESTED]) });
    hooksMock.useMetricsOverview.mockReturnValue({
      data: {
        kb_id: "kb-1",
        layer1: {
          run_id: "run-1",
          created_at: "2026-09-07T00:00:00+00:00",
          metrics: {
            summary: { hit_rate: 1, recall_at_k: 1, mrr: 1, path_accuracy: 1, question_count: 3 },
            top_k: 5,
          },
        },
        layer2: null,
        question_results: [
          { id: Q_ANCHORED.id, recall: 1, hit: 1, path_correct: true, actual_path: "vector", run_id: "run-1", created_at: "2026-09-07T00:00:00+00:00" },
          { id: Q_MULTI.id, recall: 0.5, hit: 1, path_correct: true, actual_path: "graph", run_id: "run-1", created_at: "2026-09-07T00:00:00+00:00" },
          { id: Q_UNANCHORED.id, recall: 0, hit: 0, path_correct: false, actual_path: null, run_id: "run-1", created_at: "2026-09-07T00:00:00+00:00" },
        ],
      },
    });
    const { container } = renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    const orderOf = () => [...container.querySelectorAll("tbody tr")].map((tr) => tr.querySelectorAll("td")[1]!.textContent);

    // 默认：入库原序不默默重排；钮隐形（悬停现形，同文档 tab 列显隐钮）。
    expect(orderOf()).toEqual(["锚定了三个切片的考题", "多路预期的考题", "未锚定的考题", "未测过的考题"]);
    const sortBtn = screen.getByRole("button", { name: "排序方式" });
    expect(sortBtn.className).toContain("opacity-0");
    expect(sortBtn.className).toContain("group-hover/colhead:opacity-100");

    // 菜单与文档 tab 完全同构：五键 + 升/降序恒常展示（默认态选方向只记档，
    // 切真实排序键时生效）。refDocs 选项 label 明义排序轴（2026-10-06：
    // 比较器按篇落 = 跨文档广度，与格子显示的切片数不同轴）。
    // jsdom 中 Radix DropdownMenu 须用 keyDown ArrowDown 展开（同三点菜单先例）。
    fireEvent.keyDown(sortBtn, { key: "ArrowDown" });
    expect(await screen.findByRole("menuitem", { name: "默认顺序" })).toBeTruthy();
    expect(await screen.findByRole("menuitem", { name: "文档数" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "升序" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "降序" })).toBeTruthy();

    // 选召回率@5（菜单项标签随 top_k 动态）：升序 = 最差在前（分诊视角），
    // 未测题（recall null）恒沉底不随方向翻转。
    fireEvent.click(screen.getByRole("menuitem", { name: "召回率@5" }));
    await waitFor(() => expect(orderOf()).toEqual(["未锚定的考题", "多路预期的考题", "锚定了三个切片的考题", "未测过的考题"]));
    // 激活后钮常驻（opacity-0 态类名整体移除）。
    expect(sortBtn.className).not.toContain("opacity-0");

    // 降序：有值题翻转，未测题仍沉底；方向段此时已出现。
    fireEvent.keyDown(sortBtn, { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "降序" }));
    await waitFor(() => expect(orderOf()).toEqual(["锚定了三个切片的考题", "多路预期的考题", "未锚定的考题", "未测过的考题"]));
  });

  it("行点击打开详情 drawer 并携带该题", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_ANCHORED]) });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    fireEvent.click(screen.getByText("锚定了三个切片的考题"));
    expect(screen.getByTestId("eval-question-drawer-mock")).toBeTruthy();
    expect(drawerMock.props?.question).toEqual(Q_ANCHORED);
    expect(drawerMock.props?.open).toBe(true);
  });

  it("表格样式对齐文档列表（表头 text-xs 降高 + 行高收窄；行内复现按钮移除）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_ANCHORED]) });
    const { container } = renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    // 表头：默认 h-10 是松夸根源，降成文档列表同款 text-xs；2026-09-02 起单元格
    // 钉死 h-9（36px）与文档表头对齐——自然高（复选框 + 内边距 ≈ 36.44）会撑破 tr 钉高。
    // th[0] 是选题复选框列（2026-09-01 B 方案），断言打在首个文本列上。
    const head = container.querySelectorAll("th")[1]!;
    expect(head.className).toContain("text-xs");
    expect(head.className).toContain("h-9");
    // 表头字色钉 muted（与文档表头对齐，2026-09-02）：ui/table 默认 text-foreground
    // 会压过 tr 的继承，不钉到单元格层「表头浅灰、内容深色」的层级语言不生效。
    expect(head.className).toContain("text-muted-foreground");
    // 行：单元格与文档列表同节奏；行间无分割线（2026-09-02）——ui/table 默认
    // border-b 与文档表「无框表、结构线只留表头发丝线」决策不一致（文档行早已
    // 去掉），border-0 收掉题目间那条线，两表数据行同为 px-2 py-2 无框行。
    const firstRow = container.querySelector("tbody tr")!;
    expect(firstRow.className).toContain("border-0");
    const firstCell = container.querySelector("tbody td")!;
    expect(firstCell.className).toContain("py-2");
    // 通栏对齐（文档列表同款）：表格左右拉满；首列是复选框瞬态控件，
    // px-2 与文档表头位置一致（跨 tab 一致性优先于找齐工具栏边距，2026-09-02），
    // 末列 pr-4 找齐工具栏右缘。
    const heads = container.querySelectorAll("th");
    expect(heads[0]!.className).toContain("px-2");
    expect(heads[0]!.className).not.toContain("pl-4");
    expect(heads[heads.length - 1]!.className).toContain("pr-4");
    // 吸顶表头（2026-09-02）：表头单元格 sticky，发丝线用 inset 阴影随粘性移动（
    // border-collapse 下 tr 边框会随滚动丢失）；表格外壳不可是独立滚动容器（
    // overflow-x-auto 会接管纵向滚动、破坏 sticky，横滚交给内容区）。
    expect(heads[0]!.className).toContain("sticky");
    expect(heads[0]!.className).toContain("top-0");
    expect(heads[0]!.className).toContain("bg-background");
    expect(heads[0]!.className).toContain("shadow-[inset_0_-1px_0_var(--border)]");
    expect(container.querySelector("thead")!.className).toContain("[&_tr]:border-0");
    expect(container.querySelector("[data-slot='table-container']")!.className).not.toContain("overflow-x-auto");
    // 表头行高与文档表头对齐：h-9 钉高 36px（2026-09-02）。
    expect(container.querySelector("thead tr")!.className).toContain("h-9");
    const cells = container.querySelectorAll("tbody tr:first-child td");
    expect(cells[0]!.className).toContain("px-2");
    expect(cells[0]!.className).not.toContain("pl-4");
    expect(cells[cells.length - 1]!.className).toContain("pr-4");
    // 行复选框悬浮显形（同文档表，2026-09-02）：默认隐形，悬停/勾选/任一选中才显形。
    const rowCheckbox = cells[0]!.querySelector("[data-slot='checkbox']")!;
    expect(rowCheckbox.className).toContain("opacity-0");
    expect(rowCheckbox.className).toContain("group-hover:opacity-100");
    expect(rowCheckbox.className).toContain("data-[state=checked]:opacity-100");
    expect(container.querySelector("tbody tr")!.className).toContain("group");
    // 行内 ↗ 复现按钮移除（占栏宽），复现入口留在详情 drawer。
    expect(screen.queryByRole("button", { name: "在召回测试面板复现" })).toBeNull();
    // 末列改悬浮三点（2026-09-02）：size-8 删除按钮（32px，撑出 48px 行高）换成
    // 文档 tab 同款 size-6（24px）三点菜单，行高落到 40px 与文档表对齐；删除进
    // 三点菜单（行级「删除考题」）。静止态隐形，hover/选中/菜单开才显形。
    const more = screen.getByRole("button", { name: "更多操作" });
    expect(more.className).toContain("size-6");
    const moreWrap = screen.getByTestId("bank-row-more");
    expect(moreWrap.className).toContain("opacity-0");
    expect(moreWrap.className).toContain("group-hover:opacity-100");
  });

  it("审核容器常驻底部停靠：空态单行头；表格区 ScrollArea 承隐式滚动", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_ANCHORED]) });
    // 缺省 mock 即空暂存：review 常驻单行头（空态提示、无 toggle/候选区）。
    const { container } = renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    expect(screen.getByTestId("eval-synthesis-review")).toBeTruthy();
    expect(screen.getByText("暂无待审核的候选题")).toBeTruthy();
    expect(screen.queryByTestId("eval-synthesis-review-toggle")).toBeNull();
    const root = container.firstElementChild!;
    expect(root.children).toHaveLength(2);
    // 表格区 = ScrollArea（隐式 overlay 滚动条，2026-09-08 对齐）+ 2:1 分高类。
    expect(root.children[0]!.getAttribute("data-slot")).toBe("scroll-area");
    expect(root.children[0]!.className).toContain("flex-[2]");
  });

  it("审核暂存非空 → 容器停靠在表格区之后（底部，非表头上方）且展开", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_ANCHORED]) });
    hooksMock.useSynthesisStatus.mockReturnValue({
      data: {
        in_progress: false,
        candidates: [
          {
            candidate_id: "c_11111111",
            query: "候选题一问",
            category: "fact",
            expected_paths: ["vector"],
            relevant_chunk_ids: [],
            relevant_entities: [],
            reference_answer: null,
            doc_id: "a".repeat(32),
            generated_at: "2026-09-07T00:00:00+00:00",
          },
        ],
        generated_at: "2026-09-07T00:00:00+00:00",
        doc_ids: ["a".repeat(32)],
        dropped: 0,
      },
      isLoading: false,
    });
    const { container } = renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    // 根两子：表格区 ScrollArea + 审核容器（dialog 关闭态不渲染）——审核在表格之后。
    const root = container.firstElementChild!;
    expect(root.children).toHaveLength(2);
    expect(root.children[1]!.getAttribute("data-testid")).toBe("eval-synthesis-review");
    // 有候选：toggle 出现（可收起）且候选卡渲染。
    expect(screen.getByTestId("eval-synthesis-review-toggle")).toBeTruthy();
    expect(screen.getByText("候选题一问")).toBeTruthy();
  });

  it("🗑 三点菜单删除打开确认框：取消不调 mutation", async () => {
    const mutateAsync = rs.fn().mockResolvedValue(undefined);
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_ANCHORED]) });
    hooksMock.useDeleteEvalQuestion.mockReturnValue({ mutateAsync, isPending: false });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    // 删除收进末列三点菜单（2026-09-02）：jsdom 中 Radix DropdownMenu 须用
    // keyDown ArrowDown 展开（不响应 click），再点菜单里的「删除考题」。
    fireEvent.keyDown(screen.getByRole("button", { name: "更多操作" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除考题" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain(Q_ANCHORED.query);
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(mutateAsync).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  it("删除确认：确认调 delete mutation 并发成功 toast", async () => {
    const mutateAsync = rs.fn().mockResolvedValue(undefined);
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_ANCHORED]) });
    hooksMock.useDeleteEvalQuestion.mockReturnValue({ mutateAsync, isPending: false });
    renderWithI18n(<BankHarness enabled kbId="kb-1" />);
    fireEvent.keyDown(screen.getByRole("button", { name: "更多操作" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除考题" }));

    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith(Q_ANCHORED.id));
    await waitFor(() => {
      expect(rs.mocked(toast.success).mock.calls.some(([m]) => m === "考题已删除")).toBe(true);
    });
  });

  it("末列三点菜单提供快速/完整评测（行级，携该题 id）", async () => {
    const onTrigger = rs.fn();
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([Q_ANCHORED]) });
    renderWithI18n(<BankHarness enabled kbId="kb-1" onTrigger={onTrigger} />);
    fireEvent.keyDown(screen.getByRole("button", { name: "更多操作" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "完整评测" }));
    const payload = onTrigger.mock.calls[0]?.[0] as { layers?: string; question_ids?: string[] };
    expect(payload.layers).toBe("l1_l2");
    expect(payload.question_ids).toEqual([Q_ANCHORED.id]);
  });

  it("受控 addOpen 渲染添加 dialog（入口已并入 eval-tab 常驻工具栏）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([]) });
    renderWithI18n(<BankHarness addOpen enabled kbId="kb-1" />);
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});

describe("EvalQuestionBank 搜索过滤（2026-08-30，搜索框在 eval-tab 常驻工具栏）", () => {
  it("searchQuery 按题目文本不区分大小写包含过滤", () => {
    hooksMock.useEvalQuestions.mockReturnValue({
      isLoading: false,
      error: null,
      ...questionsState([Q_UNANCHORED, Q_ANCHORED, Q_MULTI]),
    });
    renderWithI18n(<BankHarness enabled kbId="kb-1" searchQuery="多路" />);
    expect(screen.getByText("多路预期的考题")).toBeTruthy();
    expect(screen.queryByText("未锚定的考题")).toBeNull();
    expect(screen.queryByText("锚定了三个切片的考题")).toBeNull();
  });

  it("无匹配时渲染无匹配态（区别于空库引导）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({
      isLoading: false,
      error: null,
      ...questionsState([Q_ANCHORED]),
    });
    renderWithI18n(<BankHarness enabled kbId="kb-1" searchQuery="不存在的词" />);
    expect(screen.getByText("无匹配的题目，换个关键词试试")).toBeTruthy();
    expect(screen.queryByText("锚定了三个切片的考题")).toBeNull();
  });

  it("空库时即使带过滤词仍渲染空库引导（不进入无匹配态）", () => {
    hooksMock.useEvalQuestions.mockReturnValue({ isLoading: false, error: null, ...questionsState([]) });
    renderWithI18n(<BankHarness enabled kbId="kb-1" searchQuery="任意词" />);
    expect(screen.getByText("题库为空——在召回测试面板勾选正确切片可一键存为考题")).toBeTruthy();
  });
});

describe("EvalAddQuestionDialog", () => {
  function renderDialog() {
    const mutateAsync = rs.fn().mockResolvedValue({
      ...Q_ANCHORED,
      id: "q_new00001",
      query: "新考题",
    });
    hooksMock.useAddEvalQuestion.mockReturnValue({ mutateAsync, isPending: false });
    renderWithI18n(<EvalAddQuestionDialog kbId="kb-1" onOpenChange={() => undefined} open />);
    return mutateAsync;
  }

  it("空 query 时提交禁用；填后可提交（默认仅勾 vector，分类默认首项）", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "添加" }).hasAttribute("disabled")).toBe(true);

    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "新考题" } });
    expect(screen.getByRole("button", { name: "添加" }).hasAttribute("disabled")).toBe(false);
    // 分类仍是 Select 默认首项；预期路径改 Checkbox 组，默认仅勾 vector。
    expect(screen.getByRole("combobox", { name: "分类" }).textContent).toBe("事实");
    expect(screen.getByRole("checkbox", { name: "vector" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("checkbox", { name: "graph" }).getAttribute("aria-checked")).toBe("false");
    expect(screen.getByRole("checkbox", { name: "wiki" }).getAttribute("aria-checked")).toBe("false");
  });

  it("两块输入框都骑在 ScrollArea overlay 上（RAG 隐式滚动条配方，非原生滑块）", () => {
    renderDialog();
    for (const label of ["问题", "参考答案（可选）"]) {
      const field = screen.getByLabelText(label);
      // 结构钉（几何靠真浏览器量）：无边框 textarea 包在 data-slot="scroll-area" 里，
      // 高度随内容涨、超过 max-h 由 ScrollArea 接管（type=scroll、停 2s 淡出）。
      expect(field.closest('[data-slot="scroll-area"]')).not.toBeNull();
      expect(field.className).toContain("border-0");
      expect(field.className).toContain("resize-none");
    }
  });

  it("全不勾路径时提交禁用（至少一路）", () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "新考题" } });
    expect(screen.getByRole("button", { name: "添加" }).hasAttribute("disabled")).toBe(false);
    fireEvent.click(screen.getByRole("checkbox", { name: "vector" }));
    expect(screen.getByRole("button", { name: "添加" }).hasAttribute("disabled")).toBe(true);
  });

  it("勾两项提交体为双路集合，且不含旧单数键与锚定键", async () => {
    const mutateAsync = renderDialog();
    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "新考题" } });
    fireEvent.keyDown(screen.getByRole("combobox", { name: "分类" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("option", { name: "关系" }));
    // 默认已勾 vector；再勾 graph → 双路
    fireEvent.click(screen.getByRole("checkbox", { name: "graph" }));

    fireEvent.click(screen.getByRole("button", { name: "添加" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const body = mutateAsync.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(body).toMatchObject({ query: "新考题", category: "relation", expected_paths: ["vector", "graph"] });
    expect(body).not.toHaveProperty("expected_path");
    expect(body).not.toHaveProperty("relevant_chunk_ids");
    expect(body).not.toHaveProperty("relevant_entities");
  });

  it("不改选择时按默认值（单路集合）提交并发成功 toast", async () => {
    const mutateAsync = renderDialog();
    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "新考题" } });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const body = mutateAsync.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(body).toMatchObject({ category: "fact", expected_paths: ["vector"] });
    await waitFor(() => {
      expect(rs.mocked(toast.success).mock.calls.some(([m]) => m === "考题已添加")).toBe(true);
    });
  });

  // ── B′ 锚定拦截（2026-10-05；本 dialog 无锚定输入，测试模拟 422）────
  it("B′：首击被拦落红块（无错误 toast），原「添加」重提恒无确认，「仍要入库」携 anchor_ack=true 入库", async () => {
    const detail: AnchorBlockDetail = {
      reason: "mismatch",
      miss_terms: ["装箱"],
      hits: 1,
      best_hits: 3,
      suggested_chunk: "abc#0001",
    };
    const mutateAsync = rs
      .fn()
      .mockRejectedValueOnce(new AnchorBlockError(detail))
      .mockRejectedValueOnce(new AnchorBlockError(detail))
      .mockResolvedValue({ ...Q_ANCHORED, id: "q_new00002", query: "新考题" });
    hooksMock.useAddEvalQuestion.mockReturnValue({ mutateAsync, isPending: false });
    const onOpenChange = rs.fn();
    renderWithI18n(<EvalAddQuestionDialog kbId="kb-1" onOpenChange={onOpenChange} open />);
    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "新考题" } });

    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    const block = await screen.findByRole("alert");
    expect(block.textContent).toContain("装箱");
    expect(screen.getByRole("button", { name: "仍要入库" })).toBeTruthy();
    expect(rs.mocked(toast.error)).not.toHaveBeenCalled();

    // 原按钮保留原文案，再点仍是无确认重提（盲双击不绕过）。
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(2));
    expect((mutateAsync.mock.calls[1]?.[0] as Record<string, unknown>).anchor_ack).toBeFalsy();

    // 「仍要入库」→ anchor_ack=true → 正常保存收尾（成功 toast + 关闭）。
    fireEvent.click(screen.getByRole("button", { name: "仍要入库" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(3));
    expect((mutateAsync.mock.calls[2]?.[0] as Record<string, unknown>).anchor_ack).toBe(true);
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("B′ missing_chunk：红块渲染但无确认钮（不可绕过）", async () => {
    const mutateAsync = rs
      .fn()
      .mockRejectedValue(
        new AnchorBlockError({ reason: "missing_chunk", miss_terms: [], hits: 0, best_hits: 0, suggested_chunk: null }),
      );
    hooksMock.useAddEvalQuestion.mockReturnValue({ mutateAsync, isPending: false });
    renderWithI18n(<EvalAddQuestionDialog kbId="kb-1" onOpenChange={() => undefined} open />);
    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "新考题" } });

    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    const block = await screen.findByRole("alert");
    expect(block.textContent).toContain(zhCN.knowledge.eval.anchorBlock.missing);
    expect(screen.queryByRole("button", { name: "仍要入库" })).toBeNull();
    expect(rs.mocked(toast.error)).not.toHaveBeenCalled();
  });
});

// ── 题库勾选 + 批量运行（2026-09-01 B 方案 Task 5）────────────────
// 选题与档位两个正交维度：复选框列选题（行点击开 drawer 的既有行为保留），
// 批量栏双档触发携 question_ids；触发成功清空选择。

describe("EvalQuestionBank 选题与右键菜单（2026-09-02 批量运行栏退役）", () => {
  // 触发已上收 eval-tab（2026-09-06 验收缺口修复）：bank 只委托 onTrigger，不再自持
  // mutation；选择清空也由上层 handleTrigger 负责，本层断言仅到"委托携正确 payload"。
  let onTrigger: ReturnType<typeof rs.fn>;

  beforeEach(() => {
    onTrigger = rs.fn();
    hooksMock.useEvalQuestions.mockReturnValue(questionsState([Q_UNANCHORED, Q_ANCHORED, Q_MULTI]));
  });
  afterEach(() => cleanup());

  it("批量运行栏退役：勾选后不再出现插入式条（抖动源），行复选框勾选不触发抽屉", () => {
    renderWithI18n(<BankHarness kbId="kb-1" />);
    const box = screen.getByRole("checkbox", { name: `选择「${Q_ANCHORED.query}」` });
    expect(box.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(box);
    expect(box.getAttribute("aria-checked")).toBe("true");
    // 旧批量运行栏的任何痕迹都不应出现。
    expect(screen.queryByTestId("eval-bulk-run-bar")).toBeNull();
    expect(screen.queryByText(/已选 \d+ 题/)).toBeNull();
    // 勾选不开详情 drawer（行点击才开）
    expect(screen.queryByTestId("eval-question-drawer-mock")).toBeNull();
  });

  it("表头全选切换全部可见题", () => {
    renderWithI18n(<BankHarness kbId="kb-1" />);
    const selectAll = screen.getByRole("checkbox", { name: "全选" });
    fireEvent.click(selectAll);
    for (const question of [Q_UNANCHORED, Q_ANCHORED, Q_MULTI]) {
      expect(screen.getByRole("checkbox", { name: `选择「${question.query}」` }).getAttribute("aria-checked")).toBe("true");
    }
    fireEvent.click(selectAll);
    expect(screen.getByRole("checkbox", { name: `选择「${Q_ANCHORED.query}」` }).getAttribute("aria-checked")).toBe("false");
  });

  it("右键未选中行只选中该行，单选菜单提供快速评测（只跑该题）", () => {
    renderWithI18n(<BankHarness kbId="kb-1" onTrigger={onTrigger} />);
    fireEvent.contextMenu(screen.getByText(Q_ANCHORED.query));
    // 右键即选中（文件管理器惯例）。菜单打开时背景 aria-hidden，
    // getByRole 查不到——用 getByLabelText（不受可访问性树过滤）。
    expect(screen.getByLabelText(`选择「${Q_ANCHORED.query}」`).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("menuitem", { name: "快速评测" }));
    const payload = onTrigger.mock.calls[0]?.[0] as { layers?: string; question_ids?: string[] };
    expect(payload.layers).toBe("l1");
    expect(payload.question_ids).toEqual([Q_ANCHORED.id]);
  });

  it("单选右键菜单提供完整评测（l1_l2 只跑该题）", () => {
    renderWithI18n(<BankHarness kbId="kb-1" onTrigger={onTrigger} />);
    fireEvent.contextMenu(screen.getByText(Q_ANCHORED.query));
    fireEvent.click(screen.getByRole("menuitem", { name: "完整评测" }));
    const payload = onTrigger.mock.calls[0]?.[0] as { layers?: string; question_ids?: string[] };
    expect(payload.layers).toBe("l1_l2");
    expect(payload.question_ids).toEqual([Q_ANCHORED.id]);
  });

  it("多选右键菜单结构：已选标签 → 快速评测 → 完整评测 → 取消选择 → 分隔线 → 删除所选", () => {
    renderWithI18n(<BankHarness initialSelected={[Q_ANCHORED.id, Q_MULTI.id]} kbId="kb-1" onTrigger={onTrigger} />);
    fireEvent.contextMenu(screen.getByText(Q_ANCHORED.query));
    expect(screen.getByText("已选 2 项")).toBeTruthy();
    const names = screen.getAllByRole("menuitem").map((item) => item.textContent);
    expect(names).toEqual(["快速评测", "完整评测", "取消选择", "删除所选"]);
    expect(screen.getAllByRole("separator")).toHaveLength(1);
    // 快速评测携选中集委托上层触发（清空选择由 eval-tab 负责）。
    fireEvent.click(screen.getByRole("menuitem", { name: "快速评测" }));
    const payload = onTrigger.mock.calls[0]?.[0] as { layers?: string; question_ids?: string[] };
    expect(payload.layers).toBe("l1");
    expect([...(payload.question_ids ?? [])].sort()).toEqual([Q_ANCHORED.id, Q_MULTI.id].sort());
  });

  it("右键菜单取消选择带 X 图标且能清选择", async () => {
    renderWithI18n(<BankHarness initialSelected={[Q_ANCHORED.id]} kbId="kb-1" />);
    fireEvent.contextMenu(screen.getByText(Q_ANCHORED.query));
    const cancel = screen.getByRole("menuitem", { name: "取消选择" });
    expect(cancel.querySelector("svg")).toBeTruthy();
    fireEvent.click(cancel);
    await waitFor(() => {
      const box = document.querySelector(`[aria-label="选择「${Q_ANCHORED.query}」"]`);
      expect(box?.getAttribute("aria-checked")).toBe("false");
    });
  });

  it("右键删除所选：批量确认框展示计数，确认后逐题删除并修选择集", async () => {
    const mutateAsync = rs.fn().mockResolvedValue(undefined);
    hooksMock.useDeleteEvalQuestion.mockReturnValue({ mutateAsync, isPending: false });
    renderWithI18n(<BankHarness initialSelected={[Q_ANCHORED.id, Q_MULTI.id]} kbId="kb-1" />);
    fireEvent.contextMenu(screen.getByText(Q_ANCHORED.query));
    fireEvent.click(screen.getByRole("menuitem", { name: "删除所选" }));

    const dialog = await screen.findByRole("dialog");
    // 批量态展示已选计数而非单题 query。
    expect(dialog.textContent).toContain("已选 2 项");
    expect(dialog.textContent).not.toContain(Q_ANCHORED.query);
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(2));
    expect(mutateAsync).toHaveBeenCalledWith(Q_ANCHORED.id);
    expect(mutateAsync).toHaveBeenCalledWith(Q_MULTI.id);
    await waitFor(() => {
      expect(rs.mocked(toast.success).mock.calls.some(([m]) => m === "考题已删除")).toBe(true);
    });
    // 删完后选择集清空。
    expect(screen.getByRole("checkbox", { name: `选择「${Q_UNANCHORED.query}」` }).getAttribute("aria-checked")).toBe("false");
  });
});
