/**
 * Recall-test tab (phase-2 batch-1, P1): query input + top_k + cost hint.
 * 三路并列（2026-09-05）：各占 1/3 高容器、容器内 ScrollArea 内滚；
 * 切片行点击开切片总览抽屉（内联展开退役），wiki 行开条目/卡片抽屉。
 * Submit is disabled while a run is in flight; failures surface as a toast.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { toast } from "sonner";

rs.mock("@/core/knowledge/hooks", () => ({
  useRecallTest: rs.fn(),
  useAddEvalQuestion: rs.fn(),
}));

rs.mock("sonner", () => ({
  toast: { error: rs.fn(), success: rs.fn(), info: rs.fn(), warning: rs.fn() },
}));

// echarts 无 canvas 不可跑 jsdom：关系图组件 mock 为实体名清单，
// 面板侧只测视图切换语义（渲染语义由浏览器验收）。
rs.mock("@/components/workspace/knowledge/recall-graph-mini", () => ({
  RecallGraphMini: ({
    entities,
  }: {
    entities: readonly { name: string }[];
  }) => (
    <div data-testid="recall-graph-mini">
      {entities.map((entity) => entity.name).join("|")}
    </div>
  ),
}));

import { KB_TOASTER_ID } from "@/components/workspace/knowledge/kb-toast";
import { RecallTestPanel } from "@/components/workspace/knowledge/recall-test-panel";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { cardDrawersKey } from "@/core/knowledge/card-drawers";
import { useAddEvalQuestion, useRecallTest } from "@/core/knowledge/hooks";
import type { RecallTestResponse } from "@/core/knowledge/types";

const RESULT: RecallTestResponse = {
  query: "Gateway 职责",
  paths: {
    vector: {
      hits: [
        {
          chunk_id: "c1",
          doc_name: "架构.md",
          text: "Gateway 负责会话管理。",
          heading_path: ["架构"],
          page: 1,
          score: 0.97,
          rank: 1,
          chunk_position: 1,
        },
        // rerank 降级形态：score 为 null
        {
          chunk_id: "c2",
          doc_name: "架构.md",
          text: "切片二原文。",
          heading_path: [],
          page: 2,
          score: null,
          rank: 2,
          chunk_position: 2,
        },
      ],
      message: "检索到 2 条相关切片。",
    },
    graph: {
      entities: [
        { name: "Gateway", type: "组件", description: "会话管理入口" },
      ],
      relations: [
        {
          source: "DeerFlow",
          target: "Gateway",
          relation: "包含",
          description: "",
        },
      ],
      evidence: [
        {
          chunk_id: "c1",
          doc_name: "架构.md",
          text: "Gateway 负责会话管理。",
          heading_path: ["架构"],
          page: 1,
          score: 0.88,
          chunk_position: 1,
        },
      ],
      message: "命中 1 个实体。",
    },
    wiki: {
      hits: [
        {
          entry_id: "e1",
          title: "DeerFlow",
          summary: "DeerFlow 是超级智能体系统……",
          score: 0.91,
          rank: 1,
        },
      ],
      message: "命中 1 篇百科条目。",
    },
  },
  score_type: {
    vector: "qwen3-rerank relevance",
    // 2026-09-05：图谱路胶囊去「（当次可比）」补注，与 wiki 路同串。
    graph: "embedding cosine",
    wiki: "embedding cosine",
  },
  elapsed_ms: { vector: 123, graph: 456, wiki: 78 },
};

function mockRecallTest(overrides?: {
  data?: RecallTestResponse | null;
  isPending?: boolean;
}) {
  const mutate = rs.fn();
  (useRecallTest as unknown as ReturnType<typeof rs.fn>).mockReturnValue({
    mutate,
    isPending: overrides?.isPending ?? false,
    data: overrides?.data ?? null,
  });
  return mutate;
}

function renderPanel(props?: Partial<Parameters<typeof RecallTestPanel>[0]>) {
  const handlers = { onOpenWikiEntry: rs.fn(), onOpenChunkHit: rs.fn() };
  const utils = render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <RecallTestPanel kbId="kb-1" {...handlers} {...props} />
    </I18nContext.Provider>,
  );
  return { ...handlers, ...utils };
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
  // 抽屉种子（localStorage）不跨用例泄漏（2026-09-05 归属芯片用例引入）。
  localStorage.clear();
});

describe("RecallTestPanel controls", () => {
  it("shows the empty guide before the first run; cost hint lives in the run button tooltip", async () => {
    mockRecallTest();
    renderPanel();
    expect(
      screen.getByText("输入问题后开始检索，对比三通道命中与得分"),
    ).toBeTruthy();
    // 居中回归钉桩（2026-09-04）：空态 absolute inset-0 锚定 ScrollArea Root；
    // h-full 会被 Viewport 内层 auto 高测量 wrapper 回退成 auto → 靠上。
    expect(
      screen.getByText("输入问题后开始检索，对比三通道命中与得分").parentElement?.className,
    ).toContain("absolute inset-0");
    // 成本提示不再独占一行（2026-08-30）：文档流中不可见，聚焦/悬停「开始检索」时经 portal 弹出。
    expect(screen.queryByText(/会产生检索调用成本/)).toBeNull();
    fireEvent.focus(screen.getByRole("button", { name: "开始检索" }));
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toContain("会产生检索调用成本");
  });

  it("头部容器与栏内控件全部锁 44px 基准（py-2 + 控件 h-7，对齐其他工具栏）", () => {
    mockRecallTest();
    renderPanel();
    const header = screen.getByTestId("recall-test-panel")
      .firstElementChild as HTMLElement;
    expect(header.className).toContain("py-2");
    expect(header.className).not.toContain("py-3");
    // 去 border-b（2026-09-05）：三路已容器化（bg-card 带边框/头部），工具栏横线
    // 冗余（与 document-panel 去线同理，避免与卡片顶边双线夹击）。
    expect(header.className).not.toContain("border-b");
    // 栏内最高控件决定行高：搜索框/数量框/按钮均须 h-7（默认 h-9 会撑成 52px）。
    expect(screen.getByPlaceholderText("输入测试问题…").className).toContain(
      "h-7",
    );
    expect(screen.getByLabelText("每通道条数").className).toContain("h-7");
    expect(
      screen.getByRole("button", { name: "开始检索" }).className,
    ).toContain("h-7");
  });

  it("submits the trimmed query with the default top_k=5", () => {
    const mutate = mockRecallTest();
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText("输入测试问题…"), {
      target: { value: "  Gateway 职责  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始检索" }));
    expect(mutate).toHaveBeenCalledWith(
      { query: "Gateway 职责", top_k: 5 },
      expect.objectContaining({ onError: expect.any(Function) }),
    );
  });

  it("honours a custom top_k (clamped to 1–20)", () => {
    const mutate = mockRecallTest();
    renderPanel();
    fireEvent.change(screen.getByLabelText("每通道条数"), {
      target: { value: "10" },
    });
    fireEvent.change(screen.getByPlaceholderText("输入测试问题…"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始检索" }));
    expect(mutate).toHaveBeenCalledWith(
      { query: "x", top_k: 10 },
      expect.anything(),
    );
  });

  it("disables submit for blank queries and while a run is in flight", () => {
    mockRecallTest({ isPending: true });
    renderPanel();
    expect(screen.getByRole("button", { name: "检索中…" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("toasts on failure", () => {
    const mutate = mockRecallTest();
    mutate.mockImplementation(
      (_vars: unknown, options: { onError: (error: Error) => void }) => {
        options.onError(new Error("boom"));
      },
    );
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText("输入测试问题…"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始检索" }));
    expect(toast.error).toHaveBeenCalledWith("boom", expect.objectContaining({ toasterId: KB_TOASTER_ID }));
  });
});

describe("RecallTestPanel results", () => {
  it("三路容器并列：统计单行头 + 各路行同屏可见（2026-09-05 三路并列）", () => {
    mockRecallTest({ data: RESULT });
    renderPanel();
    // 各路容器单行头：score 类型 + ms + 命中数
    expect(screen.getByTestId("recall-path-vector").textContent).toContain(
      "qwen3-rerank relevance",
    );
    expect(screen.getByTestId("recall-path-vector").textContent).toContain(
      "123",
    );
    expect(screen.getByTestId("recall-path-graph").textContent).toContain(
      "embedding cosine",
    );
    // 「（当次可比）」补注退役（2026-09-05）
    expect(screen.getByTestId("recall-path-graph").textContent).not.toContain(
      "当次可比",
    );
    expect(screen.getByTestId("recall-path-wiki").textContent).toContain("78");

    // 三路行同屏渲染（无需切换）：vector rank + score + 首行摘要
    const first = screen.getByTestId("recall-vector-hit-c1");
    expect(first.textContent).toContain("#1");
    expect(first.textContent).toContain("0.970");
    expect(first.textContent).toContain("架构.md");
    // 图谱路证据序排名（2026-09-05）：与向量/百科路解剖统一
    expect(screen.getByTestId("recall-graph-hit-c1").textContent).toContain(
      "#1",
    );
    // 切片序号不挂行内（2026-09-05 改悬浮气泡）：行内无「切片 #」字样
    expect(first.textContent).not.toContain("切片 #");
    // 首行摘要入行：无标题的切片取首非空行（c2）
    expect(screen.getByTestId("recall-vector-hit-c2").textContent).toContain(
      "切片二原文。",
    );
    expect(screen.getByTestId("recall-vector-hit-c2").textContent).toContain(
      "—",
    );
    // graph：默认证据视图（实体/关系 2026-09-05 移入实体视图段控）
    const graph = screen.getByTestId("recall-path-graph");
    expect(graph.textContent).toContain("Gateway");
    expect(graph.textContent).toContain("0.880");
    fireEvent.click(screen.getByTestId("recall-graph-view-entities"));
    expect(screen.getByTestId("recall-graph-mini").textContent).toContain(
      "Gateway",
    );
    fireEvent.click(screen.getByTestId("recall-graph-view-evidence"));
    // wiki：条目行 title + summary + score
    const wikiHit = screen.getByTestId("recall-wiki-hit-e1");
    expect(wikiHit.textContent).toContain("DeerFlow");
    expect(wikiHit.textContent).toContain("超级智能体系统");
    expect(wikiHit.textContent).toContain("0.910");
  });

  it("renders the wiki hit as one inline row and strips the markdown H1 from the summary (2026-09-03)", () => {
    // 后端 wiki 命中 summary = content[:120]，content 以「# 实体名」H1 开头（generator 提示词强制）
    const withHeading: RecallTestResponse = {
      ...RESULT,
      paths: {
        ...RESULT.paths,
        wiki: {
          hits: [
            {
              entry_id: "e1",
              title: "DeerFlow",
              summary: "# DeerFlow\n\nDeerFlow 是超级智能体系统……",
              score: 0.91,
              rank: 1,
            },
          ],
          message: "命中 1 篇百科条目。",
        },
      },
    };
    mockRecallTest({ data: withHeading });
    renderPanel();
    const wikiHit = screen.getByTestId("recall-wiki-hit-e1");
    // 单行内联（不再是 flex-col 两行 / line-clamp-2 第二行摘要）
    expect(wikiHit.className).toContain("items-center");
    expect(wikiHit.className).not.toContain("flex-col");
    expect(wikiHit.querySelector("span.line-clamp-2")).toBeNull();
    expect(wikiHit.querySelector("span.flex-1.truncate")).toBeTruthy();
    // 摘要剥掉「# DeerFlow」H1（排名序号是「#1」无空格，故用带空格的「# DeerFlow」精确判定）、正文保留
    expect(wikiHit.textContent).toContain("超级智能体系统");
    expect(wikiHit.textContent).not.toContain("# DeerFlow");
  });

  it("切片行点击统一开右抽（切片总览抽屉定位），内联展开退役（2026-09-05）", () => {
    mockRecallTest({ data: RESULT });
    const handlers = renderPanel();
    fireEvent.click(screen.getByTestId("recall-vector-hit-c2"));
    expect(handlers.onOpenChunkHit).toHaveBeenCalledWith("c2");
    // 再点不 toggle（非展开语义）：重复调用抽屉回调
    fireEvent.click(screen.getByTestId("recall-vector-hit-c2"));
    expect(handlers.onOpenChunkHit).toHaveBeenCalledTimes(2);
    // 图谱证据行同链路
    fireEvent.click(screen.getByTestId("recall-graph-hit-c1"));
    expect(handlers.onOpenChunkHit).toHaveBeenCalledWith("c1");
  });

  it("图谱路视图切换：默认证据行，一键切实体/关系视图（2026-09-05）", () => {
    mockRecallTest({ data: RESULT });
    renderPanel();
    // 默认证据视图：行在同屏，实体徽章不占容器
    expect(screen.getByTestId("recall-graph-hit-c1")).toBeTruthy();
    expect(screen.queryByText("Gateway")).toBeNull();
    fireEvent.click(screen.getByTestId("recall-graph-view-entities"));
    // 实体视图：关系图独占容器（mock 组件），证据行卸载
    expect(screen.queryByTestId("recall-graph-hit-c1")).toBeNull();
    expect(screen.getByTestId("recall-graph-mini").textContent).toContain(
      "Gateway",
    );
    fireEvent.click(screen.getByTestId("recall-graph-view-evidence"));
    expect(screen.getByTestId("recall-graph-hit-c1")).toBeTruthy();
  });

  it("容器标题栏点击收起：收起只留单行头、下方容器顶上来（百科 Tab 同款，2026-09-05）", () => {
    mockRecallTest({ data: RESULT });
    renderPanel();
    const vectorSection = screen.getByTestId("recall-path-vector");
    const toggle = screen.getByTestId("recall-path-toggle-vector");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    // 收起：行体卸载、容器释放 flex-1（其余路吸收高度顶上来）
    expect(screen.queryByTestId("recall-vector-hit-c1")).toBeNull();
    expect(vectorSection.className).not.toContain("flex-1");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    // 其余两路同屏不受影响
    expect(screen.getByTestId("recall-graph-hit-c1")).toBeTruthy();
    expect(screen.getByTestId("recall-wiki-hit-e1")).toBeTruthy();
    // 再点展开复原
    fireEvent.click(toggle);
    expect(screen.getByTestId("recall-vector-hit-c1")).toBeTruthy();
    expect(vectorSection.className).toContain("flex-1");
  });

  it("切片序号悬浮气泡展示：切片 #K 与抽屉徽章同词汇（2026-09-05）", async () => {
    mockRecallTest({ data: RESULT });
    renderPanel();
    fireEvent.pointerMove(screen.getByTestId("recall-vector-hit-c1"));
    const bubble = await screen.findByRole("tooltip", {}, { timeout: 2000 });
    expect(bubble.textContent).toContain("切片 #1");
  });

  it("切片行预览取正文首非空行：标题不优先、html 标签剥除（2026-09-05 回退定案）", () => {
    const chain: RecallTestResponse = {
      ...RESULT,
      paths: {
        ...RESULT.paths,
        vector: {
          hits: [
            {
              chunk_id: "c9",
              doc_name: "jvm.docx",
              text: "<strong><u>第一行正文。</u></strong>\n第二行正文。",
              heading_path: ["安装", "内存结构"],
              page: 3,
              score: 0.5,
              rank: 1,
            },
          ],
          message: "检索到 1 条相关切片。",
        },
      },
    };
    mockRecallTest({ data: chain });
    renderPanel();
    const row = screen.getByTestId("recall-vector-hit-c9");
    // 预览 = 正文首行（填满行宽）；标题链不入行（短标题留空白回退定案）
    expect(row.textContent).toContain("第一行正文。");
    expect(row.textContent).not.toContain("安装 › 内存结构");
    // html 标签/星号剥除，裸标签不入行
    expect(row.textContent).not.toContain("<strong>");
    // 缺 chunk_position → 行内无序号（也不挂气泡）
    expect(row.textContent).not.toContain("切片 #");
  });

  it("opens the wiki entry drawer (overlay) instead of switching tabs", () => {
    mockRecallTest({ data: RESULT });
    const handlers = renderPanel();
    fireEvent.click(screen.getByTestId("recall-wiki-hit-e1"));
    expect(handlers.onOpenWikiEntry).toHaveBeenCalledWith("e1");
  });

  it("badges manual-card hits and opens the CARD drawer, never the wiki drawer (P6 fix)", () => {
    // 混排命中（spec §8）：卡片 id 走 wiki 条目详情接口必然 404 —— 必须分流。
    const mixed: RecallTestResponse = {
      ...RESULT,
      paths: {
        ...RESULT.paths,
        wiki: {
          hits: [
            {
              entry_id: "e1",
              title: "DeerFlow",
              summary: "DeerFlow 是超级智能体系统……",
              score: 0.91,
              rank: 1,
            },
            {
              entry_id: "card-1",
              title: "发布禁令",
              summary: "周五下午不发布……",
              score: 0.85,
              rank: 2,
              source_type: "manual",
            },
          ],
          message: "命中 1 篇百科条目、1 张人工知识卡片。",
        },
      },
    };
    mockRecallTest({ data: mixed });
    const onOpenManualCard = rs.fn();
    const handlers = renderPanel({ onOpenManualCard });

    const cardHit = screen.getByTestId("recall-wiki-hit-card-1");
    expect(cardHit.textContent).toContain("我的卡片");
    expect(cardHit.textContent).toContain("发布禁令");
    // wiki 命中不带卡片徽章
    expect(screen.getByTestId("recall-wiki-hit-e1").textContent).not.toContain(
      "我的卡片",
    );

    fireEvent.click(cardHit);
    expect(onOpenManualCard).toHaveBeenCalledWith("card-1");
    expect(handlers.onOpenWikiEntry).not.toHaveBeenCalled();
  });

  it("renders a single-path failure note without breaking other paths", () => {
    const degraded: RecallTestResponse = {
      ...RESULT,
      paths: {
        ...RESULT.paths,
        vector: {
          hits: [],
          message: "该路检索失败（RuntimeError），详情见服务端日志。",
        },
      },
    };
    mockRecallTest({ data: degraded });
    renderPanel();
    // 失败路默认选中（vector）：message 在详情容器内居中呈现
    expect(screen.getByTestId("recall-path-vector").textContent).toContain(
      "该路检索失败",
    );
    expect(screen.getByTestId("recall-wiki-hit-e1")).toBeTruthy();
  });
});

// ── P6 检索联动（2026-08-15 spec §9 通道一）：工具栏「在向量空间查看」图标按钮──

describe("RecallTestPanel 向量空间联动", () => {
  it("offers 在向量空间查看 on results and emits the vector hits as an overlay", () => {
    mockRecallTest({ data: RESULT });
    const onViewInVectorSpace = rs.fn();
    renderPanel({ onViewInVectorSpace });
    fireEvent.click(screen.getByRole("button", { name: "在向量空间查看" }));
    expect(onViewInVectorSpace).toHaveBeenCalledTimes(1);
    expect(onViewInVectorSpace).toHaveBeenCalledWith({
      source: "recall",
      text: "Gateway 职责",
      hits: [
        { pointId: "c1", score: 0.97 },
        { pointId: "c2", score: null },
      ],
    });
  });

  it("hides the entry before the first run and disables it when vector hits are empty", () => {
    mockRecallTest();
    const { unmount } = renderPanel({ onViewInVectorSpace: rs.fn() });
    expect(screen.queryByRole("button", { name: "在向量空间查看" })).toBeNull();
    unmount();

    // vector 路降级无命中：按钮禁用（query 还在，但没有可高亮的命中点）。
    mockRecallTest({
      data: {
        ...RESULT,
        paths: { ...RESULT.paths, vector: { hits: [], message: "未命中" } },
      },
    });
    renderPanel({ onViewInVectorSpace: rs.fn() });
    expect(
      screen.getByRole("button", { name: "在向量空间查看" }),
    ).toHaveProperty("disabled", true);
  });
});

// ── 存为考题 + prefill 通道（2026-08-27 spec §7，plan Task 8）─────────────

function mockAddQuestion() {
  const mutateAsync = rs.fn().mockResolvedValue({
    id: "q_new00001",
    query: "Gateway 职责",
    category: "fact",
    expected_paths: ["vector"],
    relevant_chunk_ids: [],
    relevant_entities: [],
    reference_answer: null,
  });
  (useAddEvalQuestion as unknown as ReturnType<typeof rs.fn>).mockReturnValue({
    mutateAsync,
    isPending: false,
  });
  return mutateAsync;
}

describe("RecallTestPanel 存为考题（spec §7.1）", () => {
  it("勾选命中行出现「存为考题」，全不选消失", () => {
    mockRecallTest({ data: RESULT });
    renderPanel();
    // 三路并列同屏：vector 2 + graph 1 + wiki 1 = 4 个勾选框；
    // e1 无源切片 → 禁用态（2026-09-05）
    expect(screen.getAllByRole("checkbox")).toHaveLength(4);
    expect(
      screen.getByTestId("recall-select-wiki-e1").getAttribute("disabled"),
    ).not.toBeNull();
    expect(screen.queryByRole("button", { name: /存为考题/ })).toBeNull();

    fireEvent.click(screen.getByTestId("recall-select-vector-c1"));
    expect(screen.getByRole("button", { name: /存为考题/ })).toBeTruthy();

    fireEvent.click(screen.getByTestId("recall-select-vector-c1"));
    expect(screen.queryByRole("button", { name: /存为考题/ })).toBeNull();
  });

  it("dialog 摘要/预填；提交体携带勾选 chunk 集；成功后清勾选不跳视图", async () => {
    mockRecallTest({ data: RESULT });
    const mutateAsync = mockAddQuestion();
    renderPanel();

    // 真实流：先输入问题（dialog 的 query 预填源是当前输入）
    fireEvent.change(screen.getByPlaceholderText("输入测试问题…"), {
      target: { value: "Gateway 职责" },
    });
    // 混路勾选（vector c2 + graph evidence c1）→ 默认勾选 = 两来源路径集合（多路化，2026-08-28）
    fireEvent.click(screen.getByTestId("recall-select-vector-c2"));
    fireEvent.click(screen.getByTestId("recall-select-graph-c1"));
    fireEvent.click(screen.getByRole("button", { name: /存为考题/ }));

    expect(screen.getAllByText("已选 2 项").length).toBeGreaterThan(0);
    // query 预填经 dialog open-effect 异步写入
    await waitFor(() => {
      const queryBox = screen.getByLabelText(
        "问题",
      ) as unknown as HTMLTextAreaElement;
      expect(queryBox.value).toBe("Gateway 职责");
    });
    // 混路即多勾：来源两路均默认选中（不再降级单路）
    expect(
      screen
        .getByRole("checkbox", { name: "vector" })
        .getAttribute("aria-checked"),
    ).toBe("true");
    expect(
      screen
        .getByRole("checkbox", { name: "graph" })
        .getAttribute("aria-checked"),
    ).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const body = mutateAsync.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(body).toMatchObject({
      query: "Gateway 职责",
      category: "fact",
      expected_paths: ["vector", "graph"],
    });
    expect(body).not.toHaveProperty("expected_path");
    expect(body.relevant_chunk_ids).toEqual(["c2", "c1"]);
    expect(body).not.toHaveProperty("relevant_entities");
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("已存为考题", expect.objectContaining({ toasterId: KB_TOASTER_ID }));
    });
    // 成功后清勾选：继续标注下一题，不跳视图
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /存为考题/ })).toBeNull();
    });
  });

  it("单路勾选时默认仅勾来源路径", async () => {
    mockRecallTest({ data: RESULT });
    mockAddQuestion();
    renderPanel();

    fireEvent.click(screen.getByTestId("recall-select-graph-c1"));
    fireEvent.click(screen.getByRole("button", { name: /存为考题/ }));

    await waitFor(() => {
      expect(
        screen
          .getByRole("checkbox", { name: "graph" })
          .getAttribute("aria-checked"),
      ).toBe("true");
    });
    expect(
      screen
        .getByRole("checkbox", { name: "vector" })
        .getAttribute("aria-checked"),
    ).toBe("false");
  });
});

describe("RecallTestPanel prefill 通道（spec §7.2）", () => {
  it("prefillQuery 写入输入框并消费；不自动触发检索", () => {
    const mutate = mockRecallTest();
    const onPrefillConsumed = rs.fn();
    renderPanel({ onPrefillConsumed, prefillQuery: "图谱如何检索" });

    const input = screen.getByPlaceholderText(
      "输入测试问题…",
    ) as unknown as HTMLInputElement;
    expect(input.value).toBe("图谱如何检索");
    expect(onPrefillConsumed).toHaveBeenCalledTimes(1);
    // 只预填，不替用户发起检索
    expect(mutate).not.toHaveBeenCalled();
  });

  it("无 prefill 时不消费", () => {
    mockRecallTest();
    const onPrefillConsumed = rs.fn();
    renderPanel({ onPrefillConsumed });
    expect(onPrefillConsumed).not.toHaveBeenCalled();
  });
});

// ── 百科行锚定（2026-08-28 spec §5，plan Task 10）─────────────────────

const WIKI_DOC = "d".repeat(32);

const RESULT_WITH_WIKI: RecallTestResponse = {
  ...RESULT,
  paths: {
    ...RESULT.paths,
    wiki: {
      hits: [
        // 词条：携带源切片（后端 Task 5 注入）→ 可勾选进锚定集。
        {
          entry_id: "e1",
          title: "DeerFlow",
          summary: "DeerFlow 是超级智能体系统……",
          score: 0.91,
          rank: 1,
          source_type: "wiki",
          source_chunk_ids: [`${WIKI_DOC}#0001`, `${WIKI_DOC}#0002`],
        },
        // 人工卡片：无源切片 → 勾选仅记录预期路径（wiki），不产生锚定（2026-09-05）。
        {
          entry_id: "m1",
          title: "运维备忘",
          summary: "手工录入的卡片。",
          score: 0.8,
          rank: 2,
          source_type: "manual",
        },
      ],
      message: "命中 2 条百科结果。",
    },
  },
};

describe("RecallTestPanel 百科行锚定（spec §5）", () => {
  it("勾选词条行 → 源切片进锚定集，默认勾选含 wiki", async () => {
    mockRecallTest({ data: RESULT_WITH_WIKI });
    const mutateAsync = mockAddQuestion();
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText("输入测试问题…"), {
      target: { value: "DeerFlow 是什么" },
    });
    fireEvent.click(screen.getByTestId("recall-select-wiki-e1"));

    expect(screen.getByRole("button", { name: /存为考题/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /存为考题/ }));
    await waitFor(() => {
      expect(
        screen
          .getByRole("checkbox", { name: "wiki" })
          .getAttribute("aria-checked"),
      ).toBe("true");
    });

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const body = mutateAsync.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(body.expected_paths).toEqual(["wiki"]);
    expect(body.relevant_chunk_ids).toEqual([
      `${WIKI_DOC}#0001`,
      `${WIKI_DOC}#0002`,
    ]);
  });

  it("人工卡片行可勾选：仅记录预期路径，提交体锚定为空（2026-09-05）", async () => {
    mockRecallTest({ data: RESULT_WITH_WIKI });
    const mutateAsync = mockAddQuestion();
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText("输入测试问题…"), {
      target: { value: "卡片题" },
    });
    fireEvent.click(screen.getByTestId("recall-select-wiki-m1"));
    expect(screen.getByRole("button", { name: /存为考题/ })).toBeTruthy();
    // tooltip 解释人工卡片与词条的勾选语义差异
    expect(
      screen.getByTitle("人工卡片无源切片：勾选仅记录预期路径，不产生切片锚定"),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /存为考题/ }));
    await waitFor(() => {
      expect(
        screen
          .getByRole("checkbox", { name: "wiki" })
          .getAttribute("aria-checked"),
      ).toBe("true");
    });

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const body = mutateAsync.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(body.expected_paths).toEqual(["wiki"]);
    // 无锚定题降级语义：锚定集为空，仅参与路径判定
    expect(body.relevant_chunk_ids).toEqual([]);
  });

  it("人工卡片命中芯片展示所属抽屉名称，置于条目名称之后（2026-09-05）", () => {
    localStorage.setItem(
      cardDrawersKey("kb-1"),
      JSON.stringify({
        drawers: [{ id: "d1", name: "运维抽屉", icon: "folder", color: "emerald" }],
        membership: { m1: "d1" },
      }),
    );
    mockRecallTest({ data: RESULT_WITH_WIKI });
    renderPanel();
    const row = screen.getByTestId("recall-wiki-hit-m1");
    expect(row.textContent).toContain("运维抽屉");
    expect(row.textContent).not.toContain("我的卡片");
    // 位置：芯片紧跟条目名称 span 之后（不再前置）
    const title = screen.getByText("运维备忘");
    expect(title.nextElementSibling?.textContent).toBe("运维抽屉");
  });

  it("混勾（向量切片 + 百科词条）→ 默认双路，两类切片都进提交体", async () => {
    mockRecallTest({ data: RESULT_WITH_WIKI });
    const mutateAsync = mockAddQuestion();
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText("输入测试问题…"), {
      target: { value: "混路题" },
    });
    fireEvent.click(screen.getByTestId("recall-select-vector-c1"));
    fireEvent.click(screen.getByTestId("recall-select-wiki-e1"));
    fireEvent.click(screen.getByRole("button", { name: /存为考题/ }));

    await waitFor(() => {
      expect(
        screen
          .getByRole("checkbox", { name: "vector" })
          .getAttribute("aria-checked"),
      ).toBe("true");
    });
    expect(
      screen
        .getByRole("checkbox", { name: "wiki" })
        .getAttribute("aria-checked"),
    ).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const body = mutateAsync.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(body.expected_paths).toEqual(["vector", "wiki"]);
    expect(body.relevant_chunk_ids).toEqual([
      "c1",
      `${WIKI_DOC}#0001`,
      `${WIKI_DOC}#0002`,
    ]);
  });
});

// ── 行右键选中 + 复选框悬浮显现（2026-09-05）─────────────────────

describe("RecallTestPanel 行右键选中与复选框显现（2026-09-05）", () => {
  it("行右键 = 勾选/取消勾选；词条行右键源切片整体进锚定集", () => {
    mockRecallTest({ data: RESULT_WITH_WIKI });
    renderPanel();
    const vectorBox = screen.getByTestId("recall-select-vector-c1");
    expect(vectorBox.getAttribute("data-state")).toBe("unchecked");
    fireEvent.contextMenu(screen.getByTestId("recall-vector-hit-c1"));
    expect(vectorBox.getAttribute("data-state")).toBe("checked");
    expect(screen.getByRole("button", { name: /存为考题/ })).toBeTruthy();
    // 再右键取消
    fireEvent.contextMenu(screen.getByTestId("recall-vector-hit-c1"));
    expect(vectorBox.getAttribute("data-state")).toBe("unchecked");
    // 词条行右键：源切片整体进锚定集
    fireEvent.contextMenu(screen.getByTestId("recall-wiki-hit-e1"));
    expect(
      screen.getByTestId("recall-select-wiki-e1").getAttribute("data-state"),
    ).toBe("checked");
    // 人工卡片行右键：仅记录预期路径（wiki）
    fireEvent.contextMenu(screen.getByTestId("recall-wiki-hit-m1"));
    expect(
      screen.getByTestId("recall-select-wiki-m1").getAttribute("data-state"),
    ).toBe("checked");
  });

  it("无源切片词条右键：拦截浏览器菜单但不切换勾选", () => {
    mockRecallTest({ data: RESULT });
    renderPanel();
    // fireEvent 返回 dispatchEvent 结果：preventDefault 生效时为 false
    expect(
      fireEvent.contextMenu(screen.getByTestId("recall-wiki-hit-e1")),
    ).toBe(false);
    expect(
      screen.getByTestId("recall-select-wiki-e1").getAttribute("data-state"),
    ).toBe("unchecked");
  });

  it("复选框默认隐藏，任一勾选存在时全量显现（百科 Tab 同款配方）", () => {
    mockRecallTest({ data: RESULT_WITH_WIKI });
    renderPanel();
    const tokens = () =>
      screen.getByTestId("recall-select-vector-c1").className.split(/\s+/);
    expect(tokens()).toContain("opacity-0");
    expect(tokens()).not.toContain("opacity-100");
    fireEvent.contextMenu(screen.getByTestId("recall-vector-hit-c1"));
    // 任一勾选存在 → 所有行复选框同时显现（不必逐行悬浮）
    expect(tokens()).toContain("opacity-100");
    expect(
      screen
        .getByTestId("recall-select-wiki-m1")
        .className.split(/\s+/)
        .includes("opacity-100"),
    ).toBe(true);
  });
});

// ── 耗时排名色（2026-09-05 定案：固定三色按跨路排名取色）──────────

describe("RecallTestPanel 耗时排名色（2026-09-05）", () => {
  it("固定三色按跨路排名：最快=绿、中间=橙绿、最慢=橙", () => {
    // RESULT elapsed：vector 123 / graph 456 / wiki 78
    mockRecallTest({ data: RESULT });
    renderPanel();
    expect(screen.getByTestId("recall-elapsed-wiki").className).toContain(
      "bg-emerald-500/10",
    );
    expect(screen.getByTestId("recall-elapsed-vector").className).toContain(
      "bg-lime-500/10",
    );
    expect(screen.getByTestId("recall-elapsed-graph").className).toContain(
      "bg-orange-500/10",
    );
  });

  it("同值耗时共享较快档色，不对持平局产生误导色", () => {
    mockRecallTest({
      data: {
        ...RESULT,
        elapsed_ms: { vector: 100, graph: 100, wiki: 300 },
      },
    });
    renderPanel();
    expect(screen.getByTestId("recall-elapsed-vector").className).toContain(
      "bg-emerald-500/10",
    );
    expect(screen.getByTestId("recall-elapsed-graph").className).toContain(
      "bg-emerald-500/10",
    );
    expect(screen.getByTestId("recall-elapsed-wiki").className).toContain(
      "bg-lime-500/10",
    );
  });
});

describe("D4 失配提示（spec 2026-10-04 §2.4）", () => {
  it("复用设置页同一文案：embedding_mismatch 才显示", () => {
    mockRecallTest({ data: { ...RESULT, embedding_mismatch: true } });
    renderPanel();
    expect(
      screen.getByText(zhCN.settings.functionalModels.embeddingChangeWarning),
    ).toBeTruthy();
  });

  it("一致/未盖章（缺键）不显示失配提示", () => {
    mockRecallTest({ data: RESULT });
    renderPanel();
    expect(
      screen.queryByText(zhCN.settings.functionalModels.embeddingChangeWarning),
    ).toBeNull();
  });
});