/**
 * Duplicate-upload confirm dialog (Task 11): two shapes — "identical" (same
 * name + same hash → skip default / keep a copy) and "conflict" (same name +
 * different or unknown hash → replace / keep both). The page owns the queue
 * and the mutation ordering; the dialog is presentational.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { DuplicateUploadDialog, type PendingDuplicate } from "@/components/workspace/knowledge/duplicate-upload-dialog";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { KnowledgeDocument } from "@/core/knowledge/types";

function doc(name: string, contentHash: string | null): KnowledgeDocument {
  return {
    id: "doc-1",
    kb_id: "kb-1",
    uploader_id: "user-1",
    name,
    size_bytes: 100,
    storage_path: "p",
    status: "ready",
    progress_percent: 100,
    chunk_count: 3,
    error: null,
    path_status: null,
    content_hash: contentHash,
    created_at: "2026-08-14T00:00:00Z",
  };
}

function renderDialog(pending: PendingDuplicate | null) {
  const onResolve = rs.fn();
  render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <DuplicateUploadDialog pending={pending} onResolve={onResolve} />
    </I18nContext.Provider>,
  );
  return { onResolve };
}

afterEach(cleanup);

describe("identical shape (same name + same hash)", () => {
  const pending: PendingDuplicate = {
    fileName: "report.pdf",
    kind: "identical",
    doc: doc("report.pdf", "hash-1"),
  };

  it("offers skip (default) and keep-copy actions, never replace", () => {
    renderDialog(pending);
    expect(screen.getByText("内容完全一致")).toBeTruthy();
    expect(screen.getByRole("button", { name: "跳过上传" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "仍上传副本" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "替换旧文档" })).toBeNull();
  });

  it("resolves skip via the default button", () => {
    const { onResolve } = renderDialog(pending);
    fireEvent.click(screen.getByRole("button", { name: "跳过上传" }));
    expect(onResolve).toHaveBeenCalledWith("skip");
  });

  it("resolves copy via the keep-copy button", () => {
    const { onResolve } = renderDialog(pending);
    fireEvent.click(screen.getByRole("button", { name: "仍上传副本" }));
    expect(onResolve).toHaveBeenCalledWith("copy");
  });
});

describe("conflict shape (same name + different or unknown hash)", () => {
  const pending: PendingDuplicate = {
    fileName: "report.pdf",
    kind: "conflict",
    doc: doc("report.pdf", "hash-old"),
  };

  it("offers replace and keep-both actions", () => {
    renderDialog(pending);
    expect(screen.getByText("同名文件已存在")).toBeTruthy();
    expect(screen.getByRole("button", { name: "替换旧文档" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "保留两份" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "跳过上传" })).toBeNull();
  });

  it("resolves replace via the destructive button", () => {
    const { onResolve } = renderDialog(pending);
    fireEvent.click(screen.getByRole("button", { name: "替换旧文档" }));
    expect(onResolve).toHaveBeenCalledWith("replace");
  });

  it("resolves copy via the keep-both button", () => {
    const { onResolve } = renderDialog(pending);
    fireEvent.click(screen.getByRole("button", { name: "保留两份" }));
    expect(onResolve).toHaveBeenCalledWith("copy");
  });

  it("resolves cancel via the outline button", () => {
    const { onResolve } = renderDialog(pending);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onResolve).toHaveBeenCalledWith("cancel");
  });

  it("shows the copy name preview for keep-both", () => {
    renderDialog({ ...pending, copyName: "report (2).pdf" });
    expect(screen.getByText(/report \(2\)\.pdf/)).toBeTruthy();
  });
});

describe("closed state", () => {
  it("renders nothing when pending is null", () => {
    renderDialog(null);
    expect(screen.queryByText("内容完全一致")).toBeNull();
    expect(screen.queryByText("同名文件已存在")).toBeNull();
  });
});
