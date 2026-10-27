import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import KnowledgeBasePage from "@/app/workspace/knowledge-base/page";
import { SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceNavChatList } from "@/components/workspace/workspace-nav-chat-list";
import { I18nProvider } from "@/core/i18n/context";
import { KnowledgeError } from "@/core/knowledge-base/api";

const mocks = rs.hoisted(() => ({
  upload: rs.fn(),
  parse: rs.fn(),
  create: rs.fn(),
  refetch: rs.fn(),
  canUpload: true,
  error: null as Error | null,
}));
rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/knowledge-base",
}));
rs.mock("@/core/agents", () => ({
  useAgentsApiEnabled: () => ({ enabled: true }),
}));
rs.mock("@/core/knowledge-base/hooks", () => ({
  useKnowledgeDatasets: () => ({
    data: {
      datasets: [
        { id: "ds1", name: "Team knowledge" },
        { id: "ds2", name: "Other" },
      ],
      can_upload: mocks.canUpload,
      can_create: mocks.canUpload,
      max_file_bytes: 5,
    },
    isLoading: false,
    isFetching: false,
    error: mocks.error,
    refetch: mocks.refetch,
  }),
  useKnowledgeDocuments: () => ({
    data: {
      documents: [
        {
          id: "doc1",
          name: "notes.txt",
          size: 5,
          chunk_count: 0,
          status: "pending",
          progress: 0,
        },
      ],
      total: 1,
    },
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: mocks.refetch,
  }),
}));
rs.mock("@/core/knowledge-base/api", () => ({
  KnowledgeError: class extends Error {
    constructor(public code: string) {
      super(code);
    }
  },
  uploadDocument: mocks.upload,
  parseDocument: mocks.parse,
  createDataset: mocks.create,
}));
rs.mock("@/env", () => ({ env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" } }));

function mount(children = <KnowledgeBasePage />) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <I18nProvider initialLocale="zh-CN">
        <SidebarProvider>{children}</SidebarProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  document.cookie = "locale=zh-CN; path=/";
  mocks.canUpload = true;
  mocks.error = null;
  mocks.upload.mockReset();
  mocks.parse.mockReset();
  mocks.refetch.mockReset();
});
afterEach(cleanup);

describe("knowledge base", () => {
  it("places knowledge immediately after scheduled tasks and marks it active", () => {
    mount(<WorkspaceNavChatList />);
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "对话",
      "智能体",
      "定时任务",
      "知识库",
    ]);
    expect(links.at(-1)?.getAttribute("href")).toBe(
      "/workspace/knowledge-base",
    );
    expect(links.at(-1)?.getAttribute("data-active")).toBe("true");
  });
  it("uploads to the selected dataset, locks selection, and retains partial success", async () => {
    let complete!: (value: unknown) => void;
    mocks.upload.mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        }),
    );
    mount();
    fireEvent.change(screen.getByLabelText("选择知识库"), {
      target: { value: "ds2" },
    });
    const file = new File(["hello"], "sample.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("上传文件"), {
      target: { files: [file] },
    });
    expect(mocks.upload).toHaveBeenCalledWith("ds2", file);
    expect(screen.getByLabelText("选择知识库").hasAttribute("disabled")).toBe(
      true,
    );
    complete({ documents: [{ id: "uploaded" }], parsing_started: false });
    await screen.findByText(/已上传，解析未启动/);
    await waitFor(() =>
      expect(screen.getByLabelText("选择知识库").hasAttribute("disabled")).toBe(
        false,
      ),
    );
    expect(mocks.upload).toHaveBeenCalledTimes(1);
  });
  it("rejects oversized files before upload", async () => {
    mount();
    fireEvent.change(screen.getByLabelText("上传文件"), {
      target: { files: [new File(["123456"], "large.txt")] },
    });
    await screen.findByText("文件超过上传大小限制。");
    expect(mocks.upload).not.toHaveBeenCalled();
  });
  it("starts parsing without re-uploading the document", async () => {
    mocks.parse.mockResolvedValue({ parsing_started: true });
    mount();
    fireEvent.click(screen.getByRole("button", { name: "开始解析" }));
    await screen.findByRole("status");
    expect(mocks.parse).toHaveBeenCalledWith("ds1", "doc1");
    expect(mocks.upload).not.toHaveBeenCalled();
  });
  it("shows read access without upload or create controls", () => {
    mocks.canUpload = false;
    mount();
    expect(screen.queryByRole("button", { name: "上传文件" })).toBeNull();
    expect(screen.queryByRole("button", { name: "新建知识库" })).toBeNull();
    expect(screen.getByText(/你有查看权限/)).toBeDefined();
  });
  it("localizes an unconfigured connection and hides stale content", () => {
    mocks.error = new KnowledgeError("ragflow_not_configured");
    mount();
    expect(screen.getByRole("alert").textContent).toContain("尚未连接 RAGFlow");
    expect(screen.queryByLabelText("选择知识库")).toBeNull();
  });
});
