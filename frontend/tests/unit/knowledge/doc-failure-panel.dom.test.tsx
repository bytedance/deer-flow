/**
 * In-tab failure notification panel (2026-08-31): document errors no longer
 * ride the global sonner toast (viewport-level — it can never stay inside the
 * tab), so this panel is absolutely positioned at the bottom-right corner of
 * the document tab. User-finalized interaction contract: ✕ on the right;
 * compact single-line collapse; hover on the body (never on ✕) expands the
 * folded list; header ✕ dismisses all, per-row ✕ dismisses one; entries
 * persist until manually dismissed (no auto-expiry timer).
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { DocFailurePanel } from "@/components/workspace/knowledge/doc-failure-panel";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { DocFailureEntry } from "@/core/knowledge/use-doc-failure-notifier";

const A: DocFailureEntry = { key: "doc-a", name: "户号.pptx", reason: "文件内容为空", retryable: true };
const B: DocFailureEntry = { key: "doc-b", name: "报告.docx", reason: "解析超时，请重试", retryable: true };
// 上传即拒类（无文档行，不可重试）
const C: DocFailureEntry = { key: "rejection-1", name: "新建 Microsoft Word 文档.docx", reason: "文件内容为空", retryable: false };

function renderPanel(
  failures: DocFailureEntry[],
  handlers?: { onDismiss?: (key: string) => void; onDismissAll?: () => void; onRetry?: (key: string) => void },
) {
  const onDismiss = handlers?.onDismiss ?? rs.fn();
  const onDismissAll = handlers?.onDismissAll ?? rs.fn();
  const onRetry = handlers?.onRetry ?? rs.fn();
  render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <DocFailurePanel failures={failures} onDismiss={onDismiss} onDismissAll={onDismissAll} onRetry={onRetry} />
    </I18nContext.Provider>,
  );
  return { onDismiss, onDismissAll, onRetry };
}

afterEach(cleanup);

describe("DocFailurePanel", () => {
  it("无条目时不渲染任何内容", () => {
    renderPanel([]);
    expect(screen.queryByTestId("doc-failure-panel")).toBeNull();
  });

  it("绝对定位在 tab 内右下角（不跑到文档 tab 外侧）", () => {
    renderPanel([A]);
    const panel = screen.getByTestId("doc-failure-panel");
    expect(panel.className).toContain("absolute");
    expect(panel.className).toContain("bottom-3");
    expect(panel.className).toContain("right-3");
  });

  it("单条：文件名/原因两行（长名截断），重试与关闭在右侧，底色沿用全局 toast（2026-08-31）", () => {
    const { onRetry } = renderPanel([C]);
    // 长文件名独占一行并截断（不再和原因挤一行溢出）
    const name = screen.getByText("新建 Microsoft Word 文档.docx");
    expect(name.className).toContain("truncate");
    expect(screen.getByText("文件内容为空")).toBeTruthy();
    expect(screen.queryByText(/文档处理失败/)).toBeNull();
    // 底色沿用全局消息框：纯白（暗色纯黑），靠阴影与页面拉开层次
    expect(screen.getByTestId("doc-failure-panel").className).toContain("bg-white");
    // 上传即拒类无文档行——不出重试按钮，只有关闭
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull();
    expect(screen.getByRole("button", { name: "全部关闭" })).toBeTruthy();
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("可重试条目的重试按钮回流 onRetry（条目 key 即文档 id）", () => {
    const { onRetry } = renderPanel([A]);
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledWith("doc-a");
  });

  it("多条折叠为汇总行；悬停主体展开明细，离开面板收起", () => {
    renderPanel([A, B]);
    expect(screen.getByText("文档处理失败（2）")).toBeTruthy();
    expect(screen.queryByText(/报告\.docx/)).toBeNull();

    fireEvent.mouseEnter(screen.getByTestId("doc-failure-summary"));
    expect(screen.getByText("户号.pptx")).toBeTruthy();
    expect(screen.getByText("报告.docx")).toBeTruthy();

    fireEvent.mouseLeave(screen.getByTestId("doc-failure-panel"));
    expect(screen.queryByText(/报告\.docx/)).toBeNull();
  });

  it("悬停总关闭 ✕ 不展开列表（✕ 独立于展开感应区）", () => {
    renderPanel([A, B]);
    fireEvent.mouseEnter(screen.getByRole("button", { name: "全部关闭" }));
    expect(screen.queryByText(/报告\.docx/)).toBeNull();
  });

  it("展开明细：行内 ✕ 单关闭、头部 ✕ 总关闭，可重试行带重试按钮", () => {
    const handlers = renderPanel([A, B]);

    fireEvent.mouseEnter(screen.getByTestId("doc-failure-summary"));
    // 展开行里每个可重试条目都有重试入口
    expect(screen.getAllByRole("button", { name: "重试" })).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", { name: "关闭" })[0]!);
    expect(handlers.onDismiss).toHaveBeenCalledWith("doc-a");
    expect(handlers.onDismissAll).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "全部关闭" }));
    expect(handlers.onDismissAll).toHaveBeenCalledTimes(1);
  });
});
