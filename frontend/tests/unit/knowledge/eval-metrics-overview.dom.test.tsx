/**
 * EvalMetricsOverview DOM tests (spec 2026-08-24 §3.3/§3.4, plan Task 2).
 *
 * Props 驱动、不内置 fetch：overview 直接由测试注入。断言覆盖 Layer 1 表格
 * 五行结构 / 单元格三态着色（阈值来自 baseline_diff.threshold_percent props，
 * 非硬编码）/ 缺失 category 灰显 / 整区空态，以及 Layer 2 卡片的 null `-` /
 * ragas 未安装 Badge / seed_hit_rate 禁用态。文案断言走 i18n 字典（zh-CN 主，
 * en-US 一个用例验证双字典）。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { EvalMetricsOverview } from "@/components/workspace/knowledge/eval-metrics-overview";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { MetricsOverview, SparkMetricKey } from "@/core/knowledge/types";

const LAYER1_METRICS: NonNullable<MetricsOverview["layer1"]>["metrics"] = {
  summary: { hit_rate: 0.928, recall_at_k: 0.897, mrr: 0.812, path_accuracy: 0.946, question_count: 20 },
  fact: { hit_rate: 0.952, recall_at_k: 0.923, mrr: 0.876, path_accuracy: 0.985, question_count: 12 },
  relation: { hit_rate: 0.881, recall_at_k: 0.854, mrr: 0.654, path_accuracy: 0.923, question_count: 4 },
  concept: { hit_rate: 0.917, recall_at_k: 0.892, mrr: 0.789, path_accuracy: 0.958, question_count: 3 },
  global: { hit_rate: 0.763, recall_at_k: 0.721, mrr: 0.543, path_accuracy: 0.812, question_count: 1 },
  top_k: 5,
};

const FULL_OVERVIEW: MetricsOverview = {
  kb_id: "kb-1",
  layer1: {
    run_id: "run-l1",
    created_at: "2026-08-20T09:00:00+00:00",
    metrics: LAYER1_METRICS,
  },
  layer2: {
    run_id: "run-l2",
    created_at: "2026-08-19T21:00:00+00:00",
    ragas_available: true,
    ragas: { faithfulness: 0.933, answer_relevancy: 0.877, context_precision: 0.912, context_recall: 0.864 },
    arch_specific: { citation_precision: 0.91, citation_recall: 0.85, seed_hit_rate: 0.75 },
    routing_hit_rate: 0.87,
    langfuse_trace_url: "https://langfuse.example/trace/1",
    has_graph_questions: true,
  },
};

/** 7 个 L2 键的 run 级 sparkline 序列（每键 ≥2 点才成线；spec §6.2）。 */
const SPARKS: Record<SparkMetricKey, number[]> = {
  faithfulness: [0.9, 0.92, 0.933],
  answer_relevancy: [0.85, 0.877],
  context_precision: [0.88, 0.9, 0.912],
  context_recall: [0.8, 0.864],
  citation_precision: [0.89, 0.91],
  citation_recall: [0.82, 0.85],
  seed_hit_rate: [0.7, 0.75],
  routing_hit_rate: [0.8, 0.87],
};

function renderOverview(
  overview: MetricsOverview,
  props?: { onViewTrace?: (url: string) => void; sparks?: Record<SparkMetricKey, number[]> },
  locale: "zh-CN" | "en-US" = "zh-CN",
) {
  return render(
    <I18nContext.Provider value={{ locale, setLocale: () => undefined, t: locale === "zh-CN" ? zhCN : enUS }}>
      <EvalMetricsOverview overview={overview} {...props} />
    </I18nContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("Layer 1 表格", () => {
  it("renders five rows (4 categories + summary) with formatted values", () => {
    renderOverview(FULL_OVERVIEW);

    const table = screen.getByTestId("eval-layer1-table");
    const rows = table.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(5);

    // category 单元格带题量后缀；数值语言统一（2026-09-05）：全列百分数 1 位小数。
    // 行头渲染本地化显示名（tk.eval.category.*），wire 键不外露（2026-08-26 补遗）。
    expect(rows[0]?.textContent).toContain("事实 (n=12)");
    expect(rows[0]?.textContent).toContain("95.2%");
    expect(rows[0]?.textContent).toContain("92.3%");
    expect(rows[0]?.textContent).toContain("87.6%");

    // 汇总行加粗并与 category 行区分；容器化后加底色（卡内 muted 前进层级）；
    // 题量后缀全行统一（2026-09-05）：summary 的 n 即全题口径。
    const summaryRow = rows[4];
    expect(summaryRow?.textContent).toContain("汇总");
    expect(summaryRow?.textContent).toContain("(n=20)");
    expect(summaryRow?.textContent).toContain("89.7%");
    expect(summaryRow?.className).toContain("border-t-2");
    expect(summaryRow?.className).toContain("bg-muted/40");
    expect(summaryRow?.className).toContain("font-semibold");
    // 两块均容器化（2026-09-05）：项目面板配方 bg-card + border + shadow-xs，
    // 与趋势卡/检索测试路容器同词汇——三块信息边界统一。
    expect(table.closest("section")?.className).toContain("bg-card");
    expect(screen.getByTestId("eval-card-faithfulness").closest("section")?.className).toContain("bg-card");
  });

  it("renders a localized five-column header row", () => {
    renderOverview(FULL_OVERVIEW);

    const headers = Array.from(
      screen.getByTestId("eval-layer1-table").querySelectorAll("thead th"),
    );
    expect(headers.map((h) => h.textContent)).toEqual(["分类", "命中率", "召回率@5", "MRR", "路径准确率"]);
  });

  it("数值列表头与单元格右对齐 + tabular-nums，分类列保持左对齐（2026-08-30）", () => {
    renderOverview(FULL_OVERVIEW);
    const headers = Array.from(screen.getByTestId("eval-layer1-table").querySelectorAll("thead th"));
    // 数值列表头右对齐（与数据同轴）；分类表头保持左对齐。
    // 主流规范：文本左、数值右（Material/Ant Design 数据表）。
    for (const header of headers.slice(1)) {
      expect(header.className).toContain("text-right");
    }
    expect(headers[0]!.className).not.toContain("text-right");
    // 数值单元格右对齐 + 等宽数字：% 与小数位纵向成列，不再参差。
    for (const testId of ["eval-cell-hit-fact", "eval-cell-recall-fact", "eval-cell-mrr-fact", "eval-cell-path-fact"]) {
      const cell = screen.getByTestId(testId);
      expect(cell.className).toContain("text-right");
      expect(cell.className).toContain("tabular-nums");
    }
    // 紧凑档（2026-09-05）：行高降一档（py-1.5），文字与分割线不再疏离；
    // 列宽保持 w-full 自然平摊——列距随栏宽伸缩（二轮纠正：固定列宽退役）。
    for (const header of headers.slice(1)) {
      expect(header.className).not.toContain("w-24");
    }
    expect(screen.getByTestId("eval-cell-hit-fact").className).toContain("py-1.5");
    // 表头行高再降一档（h-8）+ 卡体顶边距 pt-2：表头与分割线贴齐（2026-09-05 三迭代）。
    expect(headers[1]!.className).toContain("h-8");
  });

  it("each layer card owns its own horizontal scroller (2026-09-05): min-w floor sinks into the card", () => {
    renderOverview(FULL_OVERVIEW);
    // 每卡独立横向滑块：窄栏时表格/瓦片各自横滚，不拖另一卡同滚（旧设计共用总览块一个）。
    const l1 = screen.getByTestId("eval-layer1-scroll");
    const l2 = screen.getByTestId("eval-layer2-scroll");
    expect(l1.querySelector("[class*='min-w-[25rem]']")).toBeTruthy();
    expect(l2.querySelector("[class*='min-w-[27rem]']")).toBeTruthy();
    // 瓦片卡体同时是容器查询面（2026-09-07 窄栏溢出治理）：sparkline 按档隐线的 @container。
    expect(l2.querySelector("[class*='@container']")).toBeTruthy();
    // 两滑块分属不同卡片——互不联动。
    expect(l1.closest("section")).not.toBe(l2.closest("section"));
    // 表格外壳退役老原生滑块（overflow-x-auto）：横滚权归卡内 overlay 滑块（题库表同款）。
    const tableContainer = screen.getByTestId("eval-layer1-table").parentElement;
    expect(tableContainer?.className).not.toContain("overflow-x-auto");
  });

  it("collapses both layer sections from their header toggles (recall container vocabulary, 2026-09-05)", () => {
    renderOverview(FULL_OVERVIEW);
    // 整栏点击收起：主体卸载、头部 meta（ⓘ/徽章）保留；aria-expanded 同步。
    fireEvent.click(screen.getByTestId("eval-layer1-toggle"));
    expect(screen.queryByTestId("eval-layer1-table")).toBeNull();
    expect(screen.getByTestId("eval-layer1-toggle").getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByTestId("eval-layer1-toggle"));
    expect(screen.getByTestId("eval-layer1-table")).toBeTruthy();
    fireEvent.click(screen.getByTestId("eval-layer2-toggle"));
    expect(screen.queryByTestId("eval-card-faithfulness")).toBeNull();
    expect(screen.getByTestId("eval-layer2-toggle").getAttribute("aria-expanded")).toBe("false");
  });

  it("renders localized category display names instead of wire keys (zh-CN)", () => {
    renderOverview(FULL_OVERVIEW);

    const table = screen.getByTestId("eval-layer1-table");
    const rows = table.querySelectorAll("tbody tr");
    // 显示名：事实/关系/概念/全局/汇总；wire 键 fact/relation/... 不外露
    expect(rows[0]?.textContent).toContain("事实");
    expect(rows[1]?.textContent).toContain("关系");
    expect(rows[2]?.textContent).toContain("概念");
    expect(rows[3]?.textContent).toContain("全局");
    expect(rows[4]?.textContent).toContain("汇总");
    expect(table.textContent).not.toContain("fact (");
    expect(table.textContent).not.toContain("relation (");
    expect(table.textContent).not.toContain("concept (");
    expect(table.textContent).not.toContain("global (");
  });

  it("renders en-US category display names", () => {
    renderOverview(FULL_OVERVIEW, undefined, "en-US");

    const rows = screen.getByTestId("eval-layer1-table").querySelectorAll("tbody tr");
    expect(rows[0]?.textContent).toContain("Fact (n=12)");
    expect(rows[1]?.textContent).toContain("Relation");
    expect(rows[4]?.textContent).toContain("Summary");
  });

  it("passes the full variant-prefixed progress class literally so Tailwind can scan it", () => {
    renderOverview(FULL_OVERVIEW);

    // RagasCard(faithfulness=0.933 → ok 档);ArchCard(seed_hit_rate=0.75 → warn 档)
    // ——两类卡片都要拿到完整组合类,而不是运行时拼接的半成品。
    const progressOf = (testId: string) =>
      screen.getByTestId(testId).querySelector('[data-slot="progress"]')?.className ?? "";
    expect(progressOf("eval-card-faithfulness")).toContain("[&_[data-slot=progress-indicator]]:bg-(--eval-ok)");
    expect(progressOf("eval-card-seed_hit_rate")).toContain("[&_[data-slot=progress-indicator]]:bg-(--eval-warn)");
  });

  it("tints the Recall@k cells by baseline_diff delta using the backend threshold", () => {
    const regressed: MetricsOverview = {
      ...FULL_OVERVIEW,
      layer1: {
        ...FULL_OVERVIEW.layer1!,
        baseline_diff: { recall_at_k_delta: -0.05, regression_detected: true, threshold_percent: 3.0, regressed_categories: ["fact"] },
      },
    };
    renderOverview(regressed);

    // 分类行全中性（2026-09-06）：delta/绝对裸色退役，回归信号归卡头徽章 + 趋势；
    // 汇总行改胶囊（2026-09-05），全表仅胶囊带色。
    const categoryRecallCells = ["fact", "relation", "concept", "global"].map((c) =>
      screen.getByTestId(`eval-cell-recall-${c}`),
    );
    for (const cell of categoryRecallCells) {
      expect(cell.className).not.toContain("eval-danger");
      expect(cell.className).not.toContain("eval-warn");
    }
    // 汇总 recall 0.897 → ≥0.8 中档 lime 胶囊；颜色在胶囊、单元格无裸红字。
    const summaryRecall = screen.getByTestId("eval-cell-recall-summary");
    expect(summaryRecall.querySelector('[class*="bg-lime-500/10"]')).toBeTruthy();
    expect(summaryRecall.className).not.toContain("eval-danger");
    // 回退徽章出现在 Layer 1 标题旁。
    expect(screen.getByText("检测到回退")).toBeTruthy();
  });

  it("warns (not danger) on a sub-threshold drop and leaves other columns untinted", () => {
    const mild: MetricsOverview = {
      ...FULL_OVERVIEW,
      layer1: {
        ...FULL_OVERVIEW.layer1!,
        baseline_diff: { recall_at_k_delta: -0.02, regression_detected: false, threshold_percent: 3.0 },
      },
    };
    renderOverview(mild);

    // 汇总行改胶囊（2026-09-05）：recall 0.897 → lime 胶囊、hit 0.928 → emerald 胶囊；
    // 单元格不再走 delta/绝对文字着色（颜色收进胶囊）。
    const recallCell = screen.getByTestId("eval-cell-recall-summary");
    expect(recallCell.querySelector('[class*="bg-lime-500/10"]')).toBeTruthy();
    expect(recallCell.className).not.toContain("eval-warn");
    expect(screen.getByTestId("eval-cell-hit-summary").querySelector('[class*="bg-emerald-500/10"]')).toBeTruthy();
    // 分类行全中性（2026-09-06）：relation mrr 0.654 不再着琥珀字。
    expect(screen.getByTestId("eval-cell-mrr-relation").className).not.toContain("eval-warn");
    // 对齐（2026-09-06）：分类行 py-1.5、汇总行 py-1（抵消胶囊 py-0.5）行高一致。
    expect(screen.getByTestId("eval-cell-recall-fact").className.split(/\s+/)).toContain("py-1.5");
    // 未触发门禁 → 无回退徽章。
    expect(screen.queryByText("检测到回退")).toBeNull();
  });

  it("汇总行数值按 90/80 三档渲染胶囊；分类行无基线时走绝对文字档（2026-09-05）", () => {
    const low: MetricsOverview = {
      ...FULL_OVERVIEW,
      layer1: {
        ...FULL_OVERVIEW.layer1!,
        metrics: {
          summary: { hit_rate: 0.55, recall_at_k: 0.9, mrr: 0.65, path_accuracy: 0.4, question_count: 20 },
        },
      },
    };
    renderOverview(low);

    // 汇总行胶囊三档（2026-09-05，90/80 分档）：path 0.4 / mrr 0.65 → <0.8 orange
    // 胶囊；recall 0.9 → ≥0.9 emerald 胶囊；颜色在胶囊、单元格无裸红/琥珀字。
    const path = screen.getByTestId("eval-cell-path-summary");
    expect(path.querySelector('[class*="bg-orange-500/10"]')).toBeTruthy();
    expect(path.className).not.toContain("eval-danger");
    const mrr = screen.getByTestId("eval-cell-mrr-summary");
    expect(mrr.querySelector('[class*="bg-orange-500/10"]')).toBeTruthy();
    expect(mrr.className).not.toContain("eval-warn");
    const recall = screen.getByTestId("eval-cell-recall-summary");
    expect(recall.querySelector('[class*="bg-emerald-500/10"]')).toBeTruthy();
    expect(recall.className).not.toContain("eval-warn");
    expect(recall.className).not.toContain("eval-danger");
    // 对齐（2026-09-06）：胶囊 -mr-1.5 抵消右内边距使数字右缘与分类行同列；
    // 汇总格 py-1 抵消胶囊 py-0.5 使行高与分类行（py-1.5）一致。
    expect(recall.querySelector('[class*="-mr-1.5"]')).toBeTruthy();
    expect(recall.className.split(/\s+/)).toContain("py-1");
  });

  it("汇总行胶囊不受 baseline delta 影响（2026-09-05）", () => {
    const withDiff: MetricsOverview = {
      ...FULL_OVERVIEW,
      layer1: {
        ...FULL_OVERVIEW.layer1!,
        metrics: {
          summary: { hit_rate: 0.5, recall_at_k: 0.5, mrr: 0.5, path_accuracy: 0.5, question_count: 20 },
        },
        baseline_diff: { recall_at_k_delta: 0.02, regression_detected: false, threshold_percent: 3.0 },
      },
    };
    renderOverview(withDiff);

    // 汇总行改胶囊后不受 delta/绝对文字着色影响（2026-09-05）：0.5 → orange 胶囊；
    // delta 信号只作用于 category 行 recall 列。
    expect(screen.getByTestId("eval-cell-recall-summary").querySelector('[class*="bg-orange-500/10"]')).toBeTruthy();
    expect(screen.getByTestId("eval-cell-hit-summary").querySelector('[class*="bg-orange-500/10"]')).toBeTruthy();
    expect(screen.getByTestId("eval-cell-hit-summary").className).not.toContain("eval-danger");
  });

  it("greys out categories missing from by_category with a no-questions note", () => {
    const sparse: MetricsOverview = {
      ...FULL_OVERVIEW,
      layer1: {
        ...FULL_OVERVIEW.layer1!,
        metrics: {
          summary: LAYER1_METRICS.summary,
          fact: LAYER1_METRICS.fact!,
          // relation / concept / global 本批次未出现
        },
      },
    };
    renderOverview(sparse);

    const missingRow = screen.getByTestId("eval-row-relation");
    expect(missingRow.className).toContain("text-muted-foreground");
    // 缺失行题量后缀与数据行同词汇（n=0），不再用长解释句（2026-09-06 对齐）。
    expect(missingRow.textContent).toContain("(n=0)");
    expect(missingRow.textContent).not.toContain("本批次无此类题目");
    // 缺失行同样用显示名而非 wire 键（2026-08-26 补遗）
    expect(missingRow.textContent).toContain("关系");
    expect(missingRow.textContent).not.toContain("relation");
    // 有数据的行不受影响。
    expect(screen.getByTestId("eval-row-fact").textContent).toContain("95.2%");
  });

  it("renders the whole-section empty state when layer1 is null", () => {
    renderOverview({ ...FULL_OVERVIEW, layer1: null });

    expect(screen.getByText("尚无检索质量数据")).toBeTruthy();
    expect(screen.queryByTestId("eval-layer1-table")).toBeNull();
  });
});

describe("Layer 2 卡片", () => {
  it("renders four ragas cards and three arch-specific cards with values", () => {
    renderOverview(FULL_OVERVIEW);

    // 百分比主显示（2026-08-27 二轮）：同义小数不再渲染。
    expect(screen.getByTestId("eval-card-faithfulness").textContent).toContain("93.3%");
    expect(screen.getByTestId("eval-card-answer_relevancy").textContent).toContain("87.7%");
    expect(screen.getByTestId("eval-card-context_precision").textContent).toContain("91.2%");
    expect(screen.getByTestId("eval-card-context_recall").textContent).toContain("86.4%");
    expect(screen.getByTestId("eval-card-citation_precision").textContent).toContain("引用准确率");
    expect(screen.getByTestId("eval-card-seed_hit_rate").textContent).toContain("实体命中率");
    // 路由命中率瓦片填满引用组空槽（2026-09-08 总览露出）
    expect(screen.getByTestId("eval-card-routing_hit_rate").textContent).toContain("路由命中率");
    expect(screen.getByTestId("eval-card-routing_hit_rate").textContent).toContain("87.0%");
  });

  it("renders short localized card titles that cannot wrap, with full names only in ⓘ tooltips (2026-08-27 redesign round 2)", () => {
    renderOverview(FULL_OVERVIEW);

    // 中文短标题单行不换行——窄栏下不再两行挤压、进度条保持同一水平线。
    for (const [testId, title] of [
      ["faithfulness", "忠实度"],
      ["answer_relevancy", "相关性"],
      ["context_precision", "精确率"],
      ["context_recall", "召回率"],
      ["seed_hit_rate", "实体命中率"],
      ["routing_hit_rate", "路由命中率"],
    ] as const) {
      const titleEl = screen.getByTestId(`eval-card-title-${testId}`);
      expect(titleEl?.textContent).toContain(title);
      expect(titleEl?.className).toContain("truncate");
    }
    // ⓘ tooltip 承载「中文全称（English）：解释」；卡片正文不出现英文全名。
    expect(screen.getByTestId("eval-card-faithfulness").textContent).not.toContain("Faithfulness");
    expect(screen.getByTestId("eval-card-note-faithfulness").getAttribute("aria-label")).toContain("（Faithfulness）");
    expect(screen.getByTestId("eval-card-note-context_recall").getAttribute("aria-label")).toContain("（Context Recall）");
    expect(screen.getByTestId("eval-card-note-seed_hit_rate").getAttribute("aria-label")).toBe(
      "实体命中率（Seed Entity Hit Rate）：命中预设种子实体的图谱类问题占比",
    );
    // 路由命中率 ⓘ 承载口径区分（与 L1 路径准确率不同源）
    expect(screen.getByTestId("eval-card-note-routing_hit_rate").getAttribute("aria-label")).toContain(
      "与检索质量的路径准确率（离线检索选路）口径不同",
    );
  });

  it("shows the percent as the primary figure (no duplicate decimal) and pins the card grids", () => {
    renderOverview(FULL_OVERVIEW);

    // 百分比为主显示；同义小数（0.933）不再重复渲染（2026-08-27 二轮）。
    const card = screen.getByTestId("eval-card-faithfulness");
    expect(card.textContent).toContain("93.3%");
    expect(card.textContent).not.toContain("0.933");
    // 三轮：百分比降档 text-lg + tabular-nums；容器化后瓦片内左对齐（2026-09-05）。
    const percentEl = Array.from(card.querySelectorAll("div")).find((el) => el.className.includes("font-semibold"));
    expect(percentEl?.className).toContain("text-lg");
    expect(percentEl?.className).toContain("tabular-nums");

    // 固定列数：宽度下限沉进本卡 min-w-[27rem]（触底时仅本卡横滚）；窄档隐线走卡体 @container 降档。
    // 两组统一 grid-cols-4（2026-09-05）：引用组留一空槽，纵向列轴对齐。
    const ragasGrid = screen.getByTestId("eval-card-faithfulness").parentElement;
    expect(ragasGrid?.className).toContain("grid-cols-4");
    const archGrid = screen.getByTestId("eval-card-citation_precision").parentElement;
    expect(archGrid?.className).toContain("grid-cols-4");
  });

  it("labels the two card groups (probabilistic RAGAS vs deterministic citation/graph)", () => {
    renderOverview(FULL_OVERVIEW);

    expect(screen.getByText("RAGAS 概率性指标")).toBeTruthy();
    expect(screen.getByText("引用与图谱指标")).toBeTruthy();
  });

  it("shows a Layer 1 info tooltip explaining all four table metrics (no internal layer jargon)", () => {
    renderOverview(FULL_OVERVIEW);

    const label = screen.getByTestId("eval-layer1-info").getAttribute("aria-label") ?? "";
    // 首句总述 + 四指标各占一行（\n 分行，TooltipContent pre-wrap 渲染）。
    expect(label).toBe(
      "检索阶段的确定性指标，结果可复现。\n命中率：正确内容进入检索结果的问题占比\n召回率@k：前 k 条结果覆盖正确内容的比例\nMRR：首条正确结果越靠前得分越高\n路径准确率：图谱检索路径选择正确的占比",
    );
  });

  it("renders a dash and muted card for null metric values", () => {
    const withNull: MetricsOverview = {
      ...FULL_OVERVIEW,
      layer2: {
        ...FULL_OVERVIEW.layer2!,
        ragas: { faithfulness: null, answer_relevancy: 0.877, context_precision: 0.912, context_recall: 0.864 },
      },
    };
    renderOverview(withNull);

    const card = screen.getByTestId("eval-card-faithfulness");
    expect(card.textContent).toContain("-");
    // 容器化后 null 态 = 透明度降档 + 无进度条（瓦片基底恒 bg-muted/40）。
    expect(card.className).toContain("opacity-60");
    expect(card.querySelector('[data-slot="progress"]')).toBeNull();
  });

  it("shows a short localized missing badge (never the raw backend reason)", () => {
    const missing: MetricsOverview = {
      ...FULL_OVERVIEW,
      layer2: {
        ...FULL_OVERVIEW.layer2!,
        ragas_available: false,
        ragas_skip_reason: "ragas 未安装（可选依赖；`uv sync --extra ragas` 后可用）",
        ragas: { faithfulness: null, answer_relevancy: null, context_precision: null, context_recall: null },
      },
    };
    renderOverview(missing);

    // 徽章只显示固定本地化短文案，后端原始原因（含 shell 命令）不得进产品 UI。
    expect(screen.getByTestId("eval-ragas-badge").textContent).toBe("ragas 未安装");
    expect(screen.queryByText(/uv sync/)).toBeNull();
    expect(screen.getByTestId("eval-card-faithfulness").className).toContain("opacity-60");
  });

  it("shows a runtime-error badge and keeps the raw reason out of the inline header", () => {
    const failed: MetricsOverview = {
      ...FULL_OVERVIEW,
      layer2: {
        ...FULL_OVERVIEW.layer2!,
        ragas_available: false,
        ragas_skip_reason: "ragas 执行失败: judge LLM timeout",
        ragas: { faithfulness: null, answer_relevancy: null, context_precision: null, context_recall: null },
      },
    };
    renderOverview(failed);

    expect(screen.getByTestId("eval-ragas-badge").textContent).toBe("ragas 运行异常");
    // 原始错误不直接渲染；仅作为诊断 ⓘ 的无障碍标签（悬停内容交给 Radix）。
    expect(screen.queryByText(/judge LLM timeout/)).toBeNull();
    expect(screen.getByTestId("eval-ragas-error-info").getAttribute("aria-label")).toContain("judge LLM timeout");
  });

  it("moves the methodology note into an info tooltip and keeps the header non-wrapping", () => {
    renderOverview(FULL_OVERVIEW);

    // 灰色长说明不再常驻行内（窄屏不再竖排挤压）；ⓘ 说明不带内部 Layer 术语（2026-08-27 三轮）。
    expect(screen.queryByText(/judge 方差/)).toBeNull();
    const title = screen.getByTestId("eval-layer2-title");
    expect(title.textContent).toBe("生成质量");
    expect(title.className).toContain("whitespace-nowrap");
    expect(title.className).toContain("shrink-0");
    // 说明 ⓘ 的无障碍标签即说明全文。
    expect(screen.getByTestId("eval-layer2-info").getAttribute("aria-label")).toBe(
      "生成阶段指标；RAGAS 为概率性指标（judge 方差），仅供参考",
    );
  });

  it("disables the seed_hit_rate card with a note when the batch has no graph questions", () => {
    const noGraph: MetricsOverview = {
      ...FULL_OVERVIEW,
      layer2: { ...FULL_OVERVIEW.layer2!, has_graph_questions: false },
    };
    renderOverview(noGraph);

    const card = screen.getByTestId("eval-card-seed_hit_rate");
    expect(card.className).toContain("opacity-60");
    expect(card.textContent).toContain("本批次无 graph 类题目");
  });

  it("renders the whole-section empty state when layer2 is null", () => {
    renderOverview({ ...FULL_OVERVIEW, layer2: null });

    expect(screen.getByText("尚无生成质量数据")).toBeTruthy();
    expect(screen.queryByTestId("eval-card-faithfulness")).toBeNull();
  });

  it("emits onViewTrace with the langfuse url only when the link is clicked", () => {
    // 回归守护：卡片标题已本地化为「忠实度」，trace 链接必须仍按 testId 哨兵渲染
    // （2026-08-27 前用 title === "Faithfulness" 判断，本地化后会静默丢失）。
    const onViewTrace = rs.fn();
    renderOverview(FULL_OVERVIEW, { onViewTrace });
    fireEvent.click(screen.getByRole("button", { name: "查看 trace →" }));
    expect(onViewTrace).toHaveBeenCalledWith("https://langfuse.example/trace/1");
  });

  it("hides the trace link when langfuse_trace_url is absent", () => {
    const noTrace: MetricsOverview = {
      ...FULL_OVERVIEW,
      layer2: { ...FULL_OVERVIEW.layer2!, langfuse_trace_url: undefined },
    };
    renderOverview(noTrace, { onViewTrace: rs.fn() });

    expect(screen.queryByRole("button", { name: "查看 trace →" })).toBeNull();
  });
});

describe("Layer 2 sparkline（spec 2026-09-06 §5，plan Task 3）", () => {
  const L2_TILE_IDS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "citation_precision",
    "citation_recall",
    "seed_hit_rate",
  ] as const;

  it("embeds a fixed 28×12 sparkline in each of the 7 L2 tiles, on the value row", () => {
    renderOverview(FULL_OVERVIEW, { sparks: SPARKS });

    for (const id of L2_TILE_IDS) {
      const valueRow = screen.getByTestId(`eval-card-value-${id}`);
      const svg = valueRow.querySelector("svg");
      expect(svg, `tile ${id} 应含 sparkline svg`).toBeTruthy();
      // 折线（polyline）——与 ⓘ 图标（path）区分；端点实心圆（circle）。
      expect(svg!.querySelector("polyline")).toBeTruthy();
      expect(svg!.querySelector("circle")).toBeTruthy();
      // 缩档 28×12（w-7 h-3）+ 中性 muted-foreground（不引入第 11 套颜色词汇）。
      const cls = svg!.getAttribute("class") ?? "";
      expect(cls).toContain("w-7");
      expect(cls).toContain("h-3");
      expect(cls).toContain("text-muted-foreground");
      // 窄栏溢出治理（2026-09-07）：容器查询降档类——默认 hidden，卡体 ≥35rem 才同行出现。
      expect(cls).toContain("hidden");
      expect(cls).toContain("@min-[35rem]:block");
      // 与数值同行：数字与 svg 都是 value-row 容器的直接子节点（兄弟）。
      const number = valueRow.querySelector(".font-semibold");
      expect(number).toBeTruthy();
      expect(number!.parentElement).toBe(valueRow);
      expect(svg!.parentElement).toBe(valueRow);
    }
  });

  it("tier-hides sparklines below the 35rem container (2026-09-07 narrow-column overflow fix)", () => {
    renderOverview(FULL_OVERVIEW, { sparks: SPARKS });

    // 卡体 = 容器查询面：@container + 下限按数值固有宽重算的 min-w-[27rem]
    // （触底瓦片内宽 ≈67 ≥ 最坏 "100.0%" ≈65，数值独享一行不溢出）。
    const body = screen.getByTestId("eval-layer2-scroll").querySelector("[class*='@container']");
    expect(body).toBeTruthy();
    expect(body!.className).toContain("min-w-[27rem]");
    // 7 瓦片迷你线全带降档类：窄档（容器 <35rem，瓦片内宽容不下 值+gap+线）
    // 隐线只留数值，宽档恢复同行——扫描层装饰先降，主信息恒 text-lg 不缩不换。
    for (const id of L2_TILE_IDS) {
      const cls = screen.getByTestId(`eval-card-value-${id}`).querySelector("svg")!.getAttribute("class") ?? "";
      expect(cls).toContain("hidden");
      expect(cls).toContain("@min-[35rem]:block");
    }
  });

  it("gives the retired context_recall tile a sparkline (its only scan surface)", () => {
    renderOverview(FULL_OVERVIEW, { sparks: SPARKS });

    // context_recall 不在主图图例/picker，但瓦片 sparkline 是它唯一的走势扫描入口。
    const svg = screen.getByTestId("eval-card-value-context_recall").querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg!.querySelector("polyline")).toBeTruthy();
  });

  it("draws no sparkline when a series is empty or has a single point", () => {
    const partial: Record<SparkMetricKey, number[]> = {
      ...SPARKS,
      faithfulness: [], // 空数组 → 无线
      context_recall: [0.86], // 单点（<2）→ 无线
    };
    renderOverview(FULL_OVERVIEW, { sparks: partial });

    expect(screen.getByTestId("eval-card-value-faithfulness").querySelector("svg")).toBeNull();
    expect(screen.getByTestId("eval-card-value-context_recall").querySelector("svg")).toBeNull();
    // 其余瓦片照常出线。
    expect(screen.getByTestId("eval-card-value-answer_relevancy").querySelector("svg")).toBeTruthy();
    // 数值行仍在（无 sparkline 时保持原样：数字照显）。
    expect(screen.getByTestId("eval-card-faithfulness").textContent).toContain("93.3%");
  });

  it("draws no sparkline when the sparks prop is absent (trend query not resolved)", () => {
    renderOverview(FULL_OVERVIEW);

    for (const id of L2_TILE_IDS) {
      expect(screen.getByTestId(`eval-card-value-${id}`).querySelector("svg")).toBeNull();
    }
  });

  it("keeps the Layer 1 retrieval table free of sparklines (L1 无瓦片表面)", () => {
    renderOverview(FULL_OVERVIEW, { sparks: SPARKS });

    // 检索质量是表格而非瓦片：sparkline 只落 7 个 L2 瓦片，L1 表格区零 svg。
    expect(screen.getByTestId("eval-layer1-table").querySelectorAll("svg")).toHaveLength(0);
  });
});

describe("i18n", () => {
  it("renders en-US copy from the dictionary", () => {
    renderOverview({ ...FULL_OVERVIEW, layer1: null }, undefined, "en-US");

    expect(screen.getByText("No retrieval-quality data yet")).toBeTruthy();
    expect(screen.getByTestId("eval-card-faithfulness").textContent).toContain("93.3%");
    // en-US 下卡片标题与分组标签同为英文。
    expect(screen.getByTestId("eval-card-faithfulness").textContent).toContain("Faithfulness");
    expect(screen.getByText("RAGAS probabilistic metrics")).toBeTruthy();
    expect(screen.getByTestId("eval-layer2-title").textContent).toBe("Generation Quality");
  });

  it("renders the en-US column headers", () => {
    renderOverview(FULL_OVERVIEW, undefined, "en-US");

    const headers = Array.from(
      screen.getByTestId("eval-layer1-table").querySelectorAll("thead th"),
    );
    expect(headers.map((h) => h.textContent)).toEqual(["Category", "Hit Rate", "Recall@5", "MRR", "Path Accuracy"]);
  });
});
