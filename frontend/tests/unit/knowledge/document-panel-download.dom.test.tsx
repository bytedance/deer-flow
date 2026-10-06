/**
 * Document source download entry (2026-09-10 round-trip export): the row kebab
 * menu and the row right-click menu both carry 下载原文, routed through the
 * page-level onDownload (browser download over the gateway /source route).
 * The panel stays presentational — it owns no URL or fetch logic.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { DocumentPanel } from "@/components/workspace/knowledge/document-panel";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { KnowledgeBase, KnowledgeDocument } from "@/core/knowledge/types";

const KB: KnowledgeBase = {
  id: "kb-1",
  owner_id: "user-1",
  name: "资料库",
  description: "",
  visibility: "private",
  created_at: "2026-08-09T10:00:00Z",
};

const DOC: KnowledgeDocument = {
  id: "doc-1",
  kb_id: "kb-1",
  uploader_id: "user-1",
  name: "报告.pdf",
  size_bytes: 1024,
  storage_path: "/data/报告.pdf",
  status: "ready",
  progress_percent: 100,
  chunk_count: 2,
  error: null,
  path_status: null,
  content_hash: null,
  created_at: "2026-09-01T10:00:00Z",
};

function renderPanel(onDownload: (doc: KnowledgeDocument) => void) {
  render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <DocumentPanel
        kb={KB}
        documents={[DOC]}
        onUpload={() => undefined}
        onDeleteDocument={() => undefined}
        onRetryDocument={() => undefined}
        onOpenChunks={() => undefined}
        onDownload={onDownload}
        supportedSuffixes={[".pdf"]}
      />
    </I18nContext.Provider>,
  );
}

afterEach(cleanup);

describe("DocumentPanel 下载原文", () => {
  it("kebab menu offers 下载原文 and routes it through onDownload", () => {
    const onDownload = rs.fn();
    renderPanel(onDownload);
    // Radix Dropdown 在 pointerdown 开菜单（fireEvent.click 不触发，对齐
    // eval-run-history 先例）。
    fireEvent.pointerDown(screen.getByRole("button", { name: "更多操作" }), {
      button: 0,
    });
    fireEvent.click(screen.getByText("下载原文"));
    expect(onDownload).toHaveBeenCalledWith(DOC);
  });

  it("row right-click menu mirrors the same entry", () => {
    const onDownload = rs.fn();
    renderPanel(onDownload);
    fireEvent.contextMenu(screen.getByText("报告.pdf"));
    fireEvent.click(screen.getByText("下载原文"));
    expect(onDownload).toHaveBeenCalledWith(DOC);
  });
});
