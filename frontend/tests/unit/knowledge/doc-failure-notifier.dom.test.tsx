/**
 * Doc failure notifier (2026-08-31): replaces the sonner-toast hook. The
 * detection semantics survive unchanged (announce only transitions into
 * ``failed``, never backfire on first load, dedupe per episode, re-announce
 * after a retry), but the output is panel state instead of a toast call —
 * entries persist until dismissed, and a document leaving ``failed`` (retry
 * or deletion) withdraws its entry. ``report`` folds upload-time rejections
 * (empty file 400, unsupported suffix) into the same in-tab panel.
 */
import { afterEach, describe, expect, it } from "@rstest/core";
import { act, cleanup, render } from "@testing-library/react";

import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { KnowledgeDocument } from "@/core/knowledge/types";
import { useDocFailureNotifier } from "@/core/knowledge/use-doc-failure-notifier";

function doc(partial: Partial<KnowledgeDocument>): KnowledgeDocument {
  return {
    id: "doc-1",
    kb_id: "kb-1",
    uploader_id: "user-1",
    name: "户号.pptx",
    size_bytes: 0,
    storage_path: "p",
    status: "indexing",
    progress_percent: 50,
    chunk_count: null,
    error: null,
    path_status: null,
    content_hash: null,
    created_at: "2026-08-30T10:00:00Z",
    ...partial,
  };
}

let latest: ReturnType<typeof useDocFailureNotifier>;

function Harness({ documents }: { documents: KnowledgeDocument[] }) {
  latest = useDocFailureNotifier(documents);
  return null;
}

function withI18n(documents: KnowledgeDocument[]) {
  return (
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <Harness documents={documents} />
    </I18nContext.Provider>
  );
}

afterEach(cleanup);

describe("useDocFailureNotifier", () => {
  it("首次载入已失败的文档不补发条目（只报新发生的失败）", () => {
    render(withI18n([doc({ status: "failed", error: "retry limit reached (5 attempts)" })]));
    expect(latest.failures).toHaveLength(0);
  });

  it("轮询到新失败：一条条目（文件名 + 友好原因），原始英文不外露", () => {
    const { rerender } = render(withI18n([doc({})]));
    rerender(withI18n([doc({ status: "failed", error: "retry limit reached (5 attempts), please try again later" })]));

    expect(latest.failures).toHaveLength(1);
    expect(latest.failures[0]).toMatchObject({ key: "doc-1", name: "户号.pptx", retryable: true });
    expect(latest.failures[0]!.reason).toContain("解析服务多次重试仍失败");
    expect(latest.failures[0]!.reason).not.toContain("retry limit");
  });

  it("同一周期多个失败各自成条", () => {
    const { rerender } = render(withI18n([doc({}), doc({ id: "doc-2", name: "报告.docx" })]));
    rerender(
      withI18n([
        doc({ status: "failed", error: "retry limit reached (5 attempts)" }),
        doc({ id: "doc-2", name: "报告.docx", status: "failed", error: "MinerU parse timed out after 1800s" }),
      ]),
    );

    expect(latest.failures).toHaveLength(2);
    expect(latest.failures.map((f) => f.name)).toEqual(["户号.pptx", "报告.docx"]);
    expect(latest.failures[1]!.reason).toContain("解析超时");
  });

  it("同一失败只提醒一次；重试离开 failed 即撤条，再次失败重新进列表", () => {
    const { rerender } = render(withI18n([doc({})]));

    rerender(withI18n([doc({ status: "failed", error: "retry limit reached" })]));
    expect(latest.failures).toHaveLength(1);

    // 相同数据再来一轮轮询：不重复
    rerender(withI18n([doc({ status: "failed", error: "retry limit reached" })]));
    expect(latest.failures).toHaveLength(1);

    // 用户点重试：状态离开 failed——条目立即撤掉（界面只剩处理中状态）
    rerender(withI18n([doc({ status: "uploaded", error: null })]));
    expect(latest.failures).toHaveLength(0);

    // 再次失败属于新的一轮，重新进列表
    rerender(withI18n([doc({ status: "failed", error: "retry limit reached" })]));
    expect(latest.failures).toHaveLength(1);
  });

  it("report 收编上传即拒条目；dismissOne 单关闭、dismissAll 总关闭", () => {
    render(withI18n([doc({})]));

    act(() => {
      latest.report("户号.pptx", "文件内容为空");
      latest.report("年报.pdf", "不支持的文件类型");
    });
    expect(latest.failures).toHaveLength(2);
    expect(latest.failures[0]!.key).toMatch(/^rejection-/);
    expect(latest.failures[0]).toMatchObject({ name: "户号.pptx", reason: "文件内容为空", retryable: false });

    act(() => {
      latest.dismissOne(latest.failures[0]!.key);
    });
    expect(latest.failures).toHaveLength(1);
    expect(latest.failures[0]!.name).toBe("年报.pdf");

    act(() => {
      latest.dismissAll();
    });
    expect(latest.failures).toHaveLength(0);
  });
});
