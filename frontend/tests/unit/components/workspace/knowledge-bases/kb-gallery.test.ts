/* @vitest-environment jsdom */

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const galleryMocks = vi.hoisted(() => ({
  useKnowledgeBases: vi.fn(() => ({
    knowledgeBases: [],
    isLoading: false,
  })),
  useAdminKnowledgeBases: vi.fn(() => ({
    knowledgeBases: [],
    isLoading: false,
  })),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: {
        loading: "加载中...",
      },
      knowledgeBase: {
        title: "知识库",
        description: "创建和管理知识库",
        newKnowledgeBase: "新建知识库",
        emptyTitle: "还没有知识库",
        emptyDescription: "创建后即可使用",
        tabAll: "全部",
        tabMine: "我的",
        tabTenant: "租户",
        tabPublic: "公开",
        tabAdmin: "管理",
        tabHealth: "健康",
      },
    },
  }),
}));

vi.mock("@/core/knowledge-base", () => ({
  useKnowledgeBases: galleryMocks.useKnowledgeBases,
  useAdminKnowledgeBases: galleryMocks.useAdminKnowledgeBases,
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement("button", props, children),
}));

vi.mock("@/components/ui/tabs", () => ({
  Tabs: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", null, children),
  TabsList: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", null, children),
  TabsTrigger: ({
    children,
    value,
  }: {
    children: React.ReactNode;
    value: string;
  }) => React.createElement("button", { "data-value": value }, children),
  TabsContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", null, children),
}));

vi.mock("@/components/workspace/knowledge-bases/kb-form-dialog", () => ({
  KBFormDialog: () => null,
}));

import { KBGallery } from "@/components/workspace/knowledge-bases/kb-gallery";

describe("KBGallery", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("renders the health tab label from i18n instead of a hard-coded English string", () => {
    React.act(() => {
      root.render(React.createElement(KBGallery));
    });

    expect(container.textContent).toContain("健康");
    expect(container.textContent).not.toContain("Health");
  });
});
