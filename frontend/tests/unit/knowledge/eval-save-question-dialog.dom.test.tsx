/**
 * 存为考题 dialog 契约测试（B′ 锚定拦截，2026-10-05）：
 * - 首击「保存」无确认提交被锚定核验 422 拦下 → 按钮行下方红块（缺失术语/
 *   建议锚/命中计数 + 「仍要入库」），无错误 toast；原「保存」保留原文案；
 * - 原「保存」再点恒无确认重提（盲双击不绕过）；「仍要入库」携 anchor_ack=true
 *   入库并走正常保存收尾（成功 toast + onSaved + 关闭）；
 * - missing_chunk 红块无确认钮（不可绕过）；
 * - 改参考答案 / 换勾选锚定集即清块（下一次保存重新机器核验）。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { toast } from "sonner";

const hooksMock = rs.hoisted(() => ({
  useAddEvalQuestion: rs.fn(),
}));

rs.mock("@/core/knowledge/hooks", () => hooksMock);

rs.mock("sonner", () => ({
  toast: { error: rs.fn(), success: rs.fn(), info: rs.fn(), warning: rs.fn() },
}));

import { EvalSaveQuestionDialog } from "@/components/workspace/knowledge/eval-save-question-dialog";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { AnchorBlockError } from "@/core/knowledge/api";
import type { AnchorBlockDetail } from "@/core/knowledge/types";

const CHUNK_A = "a".repeat(32) + "#0001";

/** 稳定引用：open 重置 effect 以 identity 为依赖，换数组会顺带清块干扰断言。 */
const DEFAULT_PATHS: Array<"vector" | "graph" | "wiki"> = ["vector"];

const BLOCK_DETAIL: AnchorBlockDetail = {
  reason: "mismatch",
  miss_terms: ["装箱"],
  hits: 1,
  best_hits: 3,
  suggested_chunk: "abc#0001",
};

function renderWithI18n(ui: ReactElement) {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      {ui}
    </I18nContext.Provider>,
  );
}

function renderDialog(mutateAsync: ReturnType<typeof rs.fn>, extraProps: Record<string, unknown> = {}) {
  hooksMock.useAddEvalQuestion.mockReturnValue({ mutateAsync, isPending: false });
  const onSaved = rs.fn();
  const onOpenChange = rs.fn();
  const result = renderWithI18n(
    <EvalSaveQuestionDialog
      defaultPaths={DEFAULT_PATHS}
      kbId="kb-1"
      onOpenChange={onOpenChange}
      onSaved={onSaved}
      open
      prefillQuery="装箱与拆箱的区别？"
      selectedChunkIds={[CHUNK_A]}
      selectionCount={1}
      {...extraProps}
    />,
  );
  return { ...result, onSaved, onOpenChange };
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("EvalSaveQuestionDialog B′ 锚定拦截", () => {
  it("首击被拦落红块（无错误 toast），原「保存」重提恒无确认，「仍要入库」携 anchor_ack=true 入库", async () => {
    const mutateAsync = rs
      .fn()
      .mockRejectedValueOnce(new AnchorBlockError(BLOCK_DETAIL))
      .mockRejectedValueOnce(new AnchorBlockError(BLOCK_DETAIL))
      .mockResolvedValue({ id: "q_new00003", query: "装箱与拆箱的区别？" });
    const { onSaved, onOpenChange } = renderDialog(mutateAsync);

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    const block = await screen.findByRole("alert");
    expect(block.textContent).toContain("装箱");
    expect(block.textContent).toContain(zhCN.knowledge.eval.anchorBlock.suggest);
    expect(screen.getByRole("button", { name: "仍要入库" })).toBeTruthy();
    // 原按钮保留原文案
    expect(screen.getAllByRole("button", { name: "保存" })).toHaveLength(1);
    expect(rs.mocked(toast.error)).not.toHaveBeenCalled();

    // 原按钮再点仍是无确认重提（盲双击不绕过）。
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(2));
    expect((mutateAsync.mock.calls[1]?.[0] as Record<string, unknown>).anchor_ack).toBeFalsy();

    // 「仍要入库」→ anchor_ack=true → 正常保存收尾（成功 toast + onSaved + 关闭）。
    fireEvent.click(screen.getByRole("button", { name: "仍要入库" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(3));
    expect((mutateAsync.mock.calls[2]?.[0] as Record<string, unknown>).anchor_ack).toBe(true);
    await waitFor(() => {
      expect(rs.mocked(toast.success).mock.calls.some(([m]) => m === "已存为考题")).toBe(true);
    });
    expect(onSaved).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("missing_chunk 红块渲染但无确认钮（不可绕过）", async () => {
    const mutateAsync = rs
      .fn()
      .mockRejectedValue(
        new AnchorBlockError({ reason: "missing_chunk", miss_terms: [], hits: 0, best_hits: 0, suggested_chunk: null }),
      );
    renderDialog(mutateAsync);

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    const block = await screen.findByRole("alert");
    expect(block.textContent).toContain(zhCN.knowledge.eval.anchorBlock.missing);
    expect(screen.queryByRole("button", { name: "仍要入库" })).toBeNull();
    expect(rs.mocked(toast.error)).not.toHaveBeenCalled();
  });

  it("改参考答案 / 换勾选锚定集即清红块（下一次保存重新机器核验）", async () => {
    const mutateAsync = rs.fn().mockRejectedValue(new AnchorBlockError(BLOCK_DETAIL));
    const { rerender } = renderDialog(mutateAsync);

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByRole("alert");

    fireEvent.change(screen.getByLabelText("参考答案（可选）"), { target: { value: "答案改了" } });
    expect(screen.queryByRole("alert")).toBeNull();

    // 再次被拦后换勾选锚定集（新数组新内容）也清块。
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByRole("alert");
    rerender(
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <EvalSaveQuestionDialog
          defaultPaths={DEFAULT_PATHS}
          kbId="kb-1"
          onOpenChange={() => undefined}
          open
          prefillQuery="装箱与拆箱的区别？"
          selectedChunkIds={["b".repeat(32) + "#0002"]}
          selectionCount={1}
        />
      </I18nContext.Provider>,
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("两块输入框都骑在 ScrollArea overlay 上（RAG 隐式滚动条配方，非原生滑块）", () => {
    renderDialog(rs.fn());
    for (const label of ["问题", "参考答案（可选）"]) {
      const field = screen.getByLabelText(label);
      // 结构钉（几何靠真浏览器量）：无边框 textarea 包在 data-slot="scroll-area" 里，
      // 高度随内容涨、超过 max-h 由 ScrollArea 接管（type=scroll、停 2s 淡出）。
      expect(field.closest('[data-slot="scroll-area"]')).not.toBeNull();
      expect(field.className).toContain("border-0");
      expect(field.className).toContain("resize-none");
    }
  });
});
