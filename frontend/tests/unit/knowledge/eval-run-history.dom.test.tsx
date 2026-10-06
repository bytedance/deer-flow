/**
 * 历史视图契约测试（2026-08-27 spec §6.2，plan Task 7；2026-09-08 表格化 +
 * 代号退役）：
 * - 行渲染：表头四列词汇 + ⭐baseline 琥珀星 + 时间 + 环境 Badge + 评测内容
 *   用户词汇（检索/生成/检索+生成，L1/L2 代号界面禁现）+ 状态短文案 + 回退红 Badge；
 * - skipped/error 行可见（历史是唯一曝光面——不进 latest/trend）；
 * - 行点击 → onOpenRun 携带 runId（drawer 实例由 eval-tab 持有，与趋势点共用）；
 * - 三态 + in_flight 不产生伪行（运行中只由工具栏 spinner 表达）；
 * - formatRunTime 纯函数（spec ASCII 示例的 MM-DD HH:mm 口径）。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";

const hooksMock = rs.hoisted(() => ({
  useEvalRuns: rs.fn(),
  useDeleteEvalRuns: rs.fn(),
}));

rs.mock("@/core/knowledge/hooks", () => hooksMock);

const drawerMock = rs.hoisted(() => ({
  props: undefined as Record<string, unknown> | undefined,
}));

rs.mock("@/components/workspace/knowledge/eval-run-drawer", () => ({
  EvalRunDrawer: (props: Record<string, unknown>) => {
    drawerMock.props = props;
    return props.open ? <div data-testid="eval-run-drawer-mock" /> : null;
  },
}));

import { EvalRunHistory, formatRunTime } from "@/components/workspace/knowledge/eval-run-history";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { EvalRunSummary } from "@/core/knowledge/types";

const RUN_BASELINE: EvalRunSummary = {
  run_id: "run-baseline",
  created_at: "2026-08-26T14:30:00+00:00",
  completed_at: "2026-08-26T14:31:00+00:00",
  environment: "local",
  status: "completed",
  is_baseline: true,
  has_layer1: true,
  has_layer2: false,
  regression_detected: false,
  langfuse_trace_url: null,
};

const RUN_CI_ERROR: EvalRunSummary = {
  run_id: "run-ci",
  created_at: "2026-08-25T09:12:00+00:00",
  completed_at: null,
  environment: "ci",
  status: "error",
  is_baseline: false,
  has_layer1: false,
  has_layer2: true,
  regression_detected: false,
  langfuse_trace_url: null,
};

const RUN_REGRESSED: EvalRunSummary = {
  run_id: "run-regressed",
  created_at: "2026-08-24T03:00:00+00:00",
  completed_at: null,
  environment: "nightly",
  status: "completed",
  is_baseline: false,
  has_layer1: true,
  has_layer2: true,
  regression_detected: true,
  langfuse_trace_url: "https://langfuse.example/trace/7",
};

// 终止行（spec 2026-09-06 §11）：status 自由字符串列零迁移，历史行是唯一曝光面。
const RUN_CANCELLED: EvalRunSummary = {
  run_id: "run-cancelled",
  created_at: "2026-09-06T06:00:00+00:00",
  completed_at: "2026-09-06T06:03:00+00:00",
  environment: "local",
  status: "cancelled",
  is_baseline: false,
  has_layer1: true,
  has_layer2: true,
  regression_detected: false,
  langfuse_trace_url: null,
};

function runsState(runs: EvalRunSummary[], inFlight = false) {
  return { data: { in_flight: inFlight, runs, total: runs.length }, error: null, isLoading: false };
}

function renderWithI18n(ui: ReactElement) {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      {ui}
    </I18nContext.Provider>,
  );
}

function renderHistory(runs: EvalRunSummary[], inFlight = false) {
  hooksMock.useEvalRuns.mockReturnValue(runsState(runs, inFlight));
  const onOpenRun = rs.fn();
  renderWithI18n(<EvalRunHistory enabled kbId="kb-1" onOpenRun={onOpenRun} />);
  return onOpenRun;
}

beforeEach(() => {
  drawerMock.props = undefined;
  hooksMock.useEvalRuns.mockReset();
  // 删除 mutation 默认桩：组件无条件调用 useDeleteEvalRuns。
  hooksMock.useDeleteEvalRuns.mockReset();
  hooksMock.useDeleteEvalRuns.mockReturnValue({ mutateAsync: rs.fn().mockResolvedValue({ deleted: 1 }) });
});

afterEach(() => {
  cleanup();
});

describe("EvalRunHistory 行渲染", () => {
  it("环境/评测内容/状态/badge 组合正确；⭐ 与回退标红各就位", () => {
    renderHistory([RUN_BASELINE, RUN_CI_ERROR, RUN_REGRESSED]);
    // 环境三值
    expect(screen.getByText("本地")).toBeTruthy();
    expect(screen.getByText("CI")).toBeTruthy();
    expect(screen.getByText("定时")).toBeTruthy();
    // 评测内容列档位短词（2026-09-08 三轮去「评测」尾缀）；L1/L2 内部代号界面禁现；残 run 回退「生成」。
    expect(screen.getByText("快速")).toBeTruthy();
    expect(screen.getByText("生成")).toBeTruthy();
    expect(screen.getByText("完整")).toBeTruthy();
    expect(screen.queryByText(/L1|L2/)).toBeNull();
    // 表头五列词汇（含二轮时长列）
    expect(screen.getByText("运行时间")).toBeTruthy();
    expect(screen.getByText("评测内容")).toBeTruthy();
    expect(screen.getByText("状态")).toBeTruthy();
    expect(screen.getByText("时长")).toBeTruthy();
    // 时长列：RUN_BASELINE 60s → 1m（dur* 紧凑词汇与 banner 同源）；
    // 缺 completed_at 的两行诚实破折号。
    expect(screen.getByText("1m")).toBeTruthy();
    expect(screen.getAllByText("—")).toHaveLength(2);
    // 状态短文案
    expect(screen.getAllByText("完成").length).toBe(2);
    expect(screen.getByText("失败")).toBeTruthy();
    // 回退/基线收进运行时间列胶囊色（2026-09-08 三轮 + 四轮去星 + 九轮数字
    // 轴对齐）：回退=红、基线=琥珀（检索耗时胶囊同族）；时间列是数字列——
    // 胶囊内文字与裸行数字同轴（-ml-2 补偿盒体 px-2）；环境列全胶囊无裸行
    // 兄弟，盒体对齐网格线（不加 -ml-2）；基线星退役；状态列回退红 Badge
    // 退役。首列复选框后时间列是第 2 个 td。
    const regressedCell = screen.getByTestId("eval-run-row-run-regressed").querySelectorAll("td")[1];
    expect(regressedCell?.firstElementChild?.className).toContain("bg-red-500/10");
    expect(regressedCell?.firstElementChild?.className).toContain("-ml-2");
    const baselineCell = screen.getByTestId("eval-run-row-run-baseline").querySelectorAll("td")[1];
    expect(baselineCell?.firstElementChild?.className).toContain("bg-amber-500/10");
    expect(baselineCell?.querySelector("[data-testid=eval-run-baseline-star]")).toBeNull();
    // 无态行裸时间不摆空胶囊
    const plainCell = screen.getByTestId("eval-run-row-run-ci").querySelectorAll("td")[1];
    expect(plainCell?.firstElementChild?.className).not.toContain("rounded-full");
    expect(screen.queryByText("检测到回退")).toBeNull();
  });

  it("in_flight=true 不产生伪行（运行中只由工具栏 spinner 表达）", () => {
    renderHistory([RUN_BASELINE], true);
    // 只有那一行已落库的运行（表头行 + 1 数据行），没有「运行中」伪行
    expect(screen.getAllByRole("row")).toHaveLength(2);
    // 基线行运行时间裹琥珀胶囊（星退役后的唯一基线标记）；复选框列后时间列是第 2 个 td
    const baselineCell = screen.getByTestId("eval-run-row-run-baseline").querySelectorAll("td")[1];
    expect(baselineCell?.firstElementChild?.className).toContain("bg-amber-500/10");
  });

  it("行点击 → onOpenRun 携带 runId（复用 eval-tab 的 drawer 实例）", () => {
    const onOpenRun = renderHistory([RUN_CI_ERROR]);
    fireEvent.click(screen.getByTestId("eval-run-row-run-ci"));
    expect(onOpenRun).toHaveBeenCalledWith("run-ci");
  });

  it("cancelled 行渲染「已终止」状态短文案（spec §11）", () => {
    renderHistory([RUN_CANCELLED]);
    expect(screen.getByText("已终止")).toBeTruthy();
    expect(screen.queryByText("失败")).toBeNull();
    expect(screen.queryByText("跳过")).toBeNull();
  });

  it("空历史渲染空态引导", () => {
    renderHistory([]);
    expect(screen.getByText("尚无评测运行——点右上角运行评测发起首次评测")).toBeTruthy();
  });

  it("loading 与错误三态", () => {
    hooksMock.useEvalRuns.mockReturnValue({ data: undefined, error: null, isLoading: true });
    renderWithI18n(<EvalRunHistory enabled kbId="kb-1" onOpenRun={() => undefined} />);
    expect(screen.getByText("加载中…")).toBeTruthy();

    cleanup();
    hooksMock.useEvalRuns.mockReturnValue({ data: undefined, error: new Error("boom"), isLoading: false });
    renderWithI18n(<EvalRunHistory enabled kbId="kb-1" onOpenRun={() => undefined} />);
    expect(screen.getByText("评测数据加载失败")).toBeTruthy();
  });
});

describe("formatRunTime（纯函数）", () => {
  it("按 MM-DD HH:mm 口径格式化", () => {
    expect(formatRunTime("2026-08-26T14:30:00+00:00")).toMatch(/^\d{2}-\d{2} \d{2}:\d{2}$/);
  });

  it("null 或非法时间返回 -", () => {
    expect(formatRunTime(null)).toBe("-");
    expect(formatRunTime("not-a-date")).toBe("-");
  });
});

describe("EvalRunHistory 删除功能（2026-09-08，题库同构）", () => {
  it("复选框列与行尾三点：静止态隐藏 hover 现形（题库同款配方）", () => {
    renderHistory([RUN_BASELINE, RUN_CI_ERROR]);
    expect(screen.getByLabelText("全选")).toBeTruthy();
    const rowBox = within(screen.getByTestId("eval-run-row-run-baseline")).getByRole("checkbox");
    expect(rowBox.className).toContain("opacity-0");
    expect(rowBox.className).toContain("group-hover:opacity-100");
    // 多行各有一个三点wrapper——within 行内定位
    const more = within(screen.getByTestId("eval-run-row-run-baseline")).getByTestId("history-row-more");
    expect(more.className).toContain("opacity-0");
    expect(more.className).toContain("group-hover:opacity-100");
  });

  it("勾选行复选框不触发下钻；全选checkbox 同步选中态", () => {
    const onOpenRun = renderHistory([RUN_BASELINE, RUN_CI_ERROR]);
    const baseRow = screen.getByTestId("eval-run-row-run-baseline");
    fireEvent.click(within(baseRow).getByRole("checkbox"));
    expect(onOpenRun).not.toHaveBeenCalled();
    expect(within(baseRow).getByRole("checkbox").getAttribute("aria-checked")).toBe("true");
    // 只选了一行 → 全选未勾
    expect(screen.getByLabelText("全选").getAttribute("aria-checked")).toBe("false");
    fireEvent.click(screen.getByLabelText("全选"));
    expect(screen.getByLabelText("全选").getAttribute("aria-checked")).toBe("true");
    expect(within(screen.getByTestId("eval-run-row-run-ci")).getByRole("checkbox").getAttribute("aria-checked")).toBe("true");
  });

  it("行三点菜单删除此次运行 → 确认框 → mutateAsync 携带行 id", async () => {
    const mutateAsync = rs.fn().mockResolvedValue({ deleted: 1 });
    hooksMock.useDeleteEvalRuns.mockReturnValue({ mutateAsync });
    renderHistory([RUN_BASELINE]);
    // Radix Dropdown 在 pointerdown 开菜单（fireEvent.click 不触发）
    fireEvent.pointerDown(within(screen.getByTestId("history-row-more")).getByRole("button"), { button: 0 });
    fireEvent.click(screen.getByRole("menuitem", { name: "删除此次运行" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("删除运行历史");
    expect(dialog.textContent).toContain("将删除 1 条运行记录");
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith(["run-baseline"]));
  });

  it("右键未选中行只选中该行；右键菜单删除所选走确认", async () => {
    const mutateAsync = rs.fn().mockResolvedValue({ deleted: 1 });
    hooksMock.useDeleteEvalRuns.mockReturnValue({ mutateAsync });
    renderHistory([RUN_BASELINE, RUN_CI_ERROR]);
    fireEvent.contextMenu(screen.getByTestId("eval-run-row-run-ci"));
    // 文件管理器惯例：右键即选中该行，其余行不受影响；菜单开时背景
    // aria-hidden——属性查询绕过可访问性树过滤（Radix 陷阱先例）。
    const checkedOf = (rowId: string) =>
      screen.getByTestId(rowId).querySelector('[role=checkbox]')?.getAttribute("aria-checked");
    expect(checkedOf("eval-run-row-run-ci")).toBe("true");
    expect(checkedOf("eval-run-row-run-baseline")).toBe("false");
    fireEvent.click(screen.getByRole("menuitem", { name: "删除所选" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("将删除 1 条运行记录");
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith(["run-ci"]));
  });

  it("多选右键菜单：已选计数标签 + 删除所选携带全选中集 + 成功后修选择", async () => {
    const mutateAsync = rs.fn().mockResolvedValue({ deleted: 2 });
    hooksMock.useDeleteEvalRuns.mockReturnValue({ mutateAsync });
    renderHistory([RUN_BASELINE, RUN_CI_ERROR]);
    fireEvent.click(within(screen.getByTestId("eval-run-row-run-baseline")).getByRole("checkbox"));
    fireEvent.click(within(screen.getByTestId("eval-run-row-run-ci")).getByRole("checkbox"));
    fireEvent.contextMenu(screen.getByTestId("eval-run-row-run-baseline"));
    expect(screen.getByText("已选 2 项")).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: "删除所选" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("已选 2 项");
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith(["run-baseline", "run-ci"]));
    // 成功后选择集清空（复选框回未勾）
    await waitFor(() =>
      expect(within(screen.getByTestId("eval-run-row-run-baseline")).getByRole("checkbox").getAttribute("aria-checked")).toBe("false"),
    );
  });

  it("确认框含基线行追加警示行（删后回退门禁失参照）", async () => {
    renderHistory([RUN_BASELINE, RUN_CI_ERROR]);
    fireEvent.click(within(screen.getByTestId("eval-run-row-run-baseline")).getByRole("checkbox"));
    fireEvent.contextMenu(screen.getByTestId("eval-run-row-run-baseline"));
    fireEvent.click(screen.getByRole("menuitem", { name: "删除所选" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("所选包含基线运行");
    // 非基线单选不显警示
    cleanup();
    renderHistory([RUN_CI_ERROR]);
    fireEvent.contextMenu(screen.getByTestId("eval-run-row-run-ci"));
    fireEvent.click(screen.getByRole("menuitem", { name: "删除所选" }));
    const dialog2 = await screen.findByRole("dialog");
    expect(dialog2.textContent).not.toContain("所选包含基线运行");
  });
});

describe("EvalRunHistory 排序与时长格式（2026-09-08 九轮，题库/文档 tab 同构）", () => {
  const rowOrder = () => screen.getAllByRole("row").slice(1).map((row) => row.getAttribute("data-testid"));

  it("排序菜单：六键 + 升/降序恒常；时长降序重排且无值行沉底", () => {
    renderHistory([RUN_BASELINE, RUN_CI_ERROR, RUN_REGRESSED, RUN_CANCELLED]);
    const sortButton = screen.getByLabelText("排序方式");
    // 默认态隐形不扰
    expect(sortButton.className).toContain("opacity-0");
    fireEvent.pointerDown(sortButton, { button: 0 });
    const names = screen.getAllByRole("menuitem").map((item) => item.textContent);
    expect(names).toEqual(["默认顺序", "运行时间", "环境", "评测内容", "状态", "时长", "升序", "降序"]);
    fireEvent.click(screen.getByRole("menuitem", { name: "时长" }));
    fireEvent.pointerDown(screen.getByLabelText("排序方式"), { button: 0 });
    fireEvent.click(screen.getByRole("menuitem", { name: "降序" }));
    // 180s > 60s 先排；两个无值行恒沉底（null-sink 不随方向翻转，稳定保原序）
    expect(rowOrder()).toEqual([
      "eval-run-row-run-cancelled",
      "eval-run-row-run-baseline",
      "eval-run-row-run-ci",
      "eval-run-row-run-regressed",
    ]);
    // 激活后按钮常驻可追溯
    expect(screen.getByLabelText("排序方式").className).toContain("opacity-100");
    // 时间升序：按 created_at 重排（08-24 → 08-25 → 08-26 → 09-06）
    fireEvent.pointerDown(screen.getByLabelText("排序方式"), { button: 0 });
    fireEvent.click(screen.getByRole("menuitem", { name: "运行时间" }));
    fireEvent.pointerDown(screen.getByLabelText("排序方式"), { button: 0 });
    fireEvent.click(screen.getByRole("menuitem", { name: "升序" }));
    expect(rowOrder()).toEqual([
      "eval-run-row-run-regressed",
      "eval-run-row-run-ci",
      "eval-run-row-run-baseline",
      "eval-run-row-run-cancelled",
    ]);
  });

  it("时长格式下拉：按秒档显全量秒且按钮常驻；切回紧凑恢复 dur* 词汇", () => {
    renderHistory([RUN_BASELINE]);
    const fmtButton = screen.getByLabelText("时长格式");
    expect(fmtButton.className).toContain("opacity-0");
    fireEvent.pointerDown(fmtButton, { button: 0 });
    fireEvent.click(screen.getByRole("menuitem", { name: "按秒" }));
    expect(screen.getByText("60s")).toBeTruthy();
    expect(screen.getByLabelText("时长格式").className).toContain("opacity-100");
    fireEvent.pointerDown(screen.getByLabelText("时长格式"), { button: 0 });
    fireEvent.click(screen.getByRole("menuitem", { name: "紧凑" }));
    expect(screen.getByText("1m")).toBeTruthy();
  });

  it("按秒档取整不显小数（十轮用户纠正，与 durationParts 同 Math.round 口径）", () => {
    // 62.5s 浮点耗时 → 按秒档显 63s 而非 62.5s
    const RUN_FRACTIONAL: EvalRunSummary = {
      ...RUN_BASELINE,
      run_id: "run-fractional",
      created_at: "2026-09-08T06:00:00+00:00",
      completed_at: "2026-09-08T06:01:02.500+00:00",
    };
    renderHistory([RUN_FRACTIONAL]);
    fireEvent.pointerDown(screen.getByLabelText("时长格式"), { button: 0 });
    fireEvent.click(screen.getByRole("menuitem", { name: "按秒" }));
    expect(screen.getByText("63s")).toBeTruthy();
    expect(screen.queryByText("62.5s")).toBeNull();
  });
});
