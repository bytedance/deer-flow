import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useRouter: vi.fn(),
  useMarketplaceListing: vi.fn(),
  useReportTemplate: vi.fn(),
  useReportTemplateVersions: vi.fn(),
  useReportTemplateVersion: vi.fn(),
  useUpdateReportTemplate: vi.fn(),
  usePublishReportTemplate: vi.fn(),
  useValidateReportTemplate: vi.fn(),
  useArchiveReportTemplate: vi.fn(),
  useDeleteReportTemplate: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    ...props
  }: React.PropsWithChildren<Record<string, unknown>>) =>
    React.createElement("a", props, children),
}));

vi.mock("next/navigation", () => ({
  useRouter: mocks.useRouter,
}));

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  DialogContent: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  DialogDescription: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  DialogFooter: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  DialogHeader: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  DialogTitle: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
}));

vi.mock("@/core/auth/api-error", () => ({
  applyResolvedAuthError: vi.fn(),
  resolveAuthError: vi.fn(() => null),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: {
        loading: "加载中-测试",
        cancel: "取消-测试",
        delete: "删除-测试",
      },
      marketplace: {
        visibilityPrivate: "私有-测试",
        visibilityTenant: "租户-测试",
        visibilityBuiltin: "内置-测试",
        statusDraft: "草稿-测试",
        statusPublished: "已发布-测试",
        statusArchived: "已归档-测试",
      },
      editor: {
        validationSuccess: "校验通过-测试",
        validationFailed: "校验失败-测试",
        saveSuccess: "保存成功-测试",
        saveFailed: "保存失败-测试",
        publishSuccess: "发布成功-测试",
        publishFailed: "发布失败-测试",
        validating: "校验中-测试",
        publishing: "发布中-测试",
      },
      reportTemplates: {
        backToTemplates: "返回模板列表-测试",
        notFound: "模板不存在-测试",
        installedFromMarketplace: "来自市场-测试",
        updateAvailable: "有更新-测试",
        validateDsl: "校验 DSL-测试",
        saveDraft: "保存草稿-测试",
        publishNewVersion: "发布新版本-测试",
        archive: "归档-测试",
        archiveSuccess: "归档成功-测试",
        archiveFailed: "归档失败-测试",
        deleteSuccess: "删除成功-测试",
        deleteFailed: "删除失败-测试",
        versions: "版本列表-测试",
        workingDraft: "工作草稿-测试",
        jsonParseFailed: "JSON 解析失败-测试",
        publishedReadonly: "已发布只读-测试",
        builtinReadonly: "内置只读-测试",
        dslJson: "DSL JSON-测试",
        dslYaml: "DSL YAML-测试",
        deleteTemplateTitle: "删除模板-测试",
        deleteTemplateDescription: "及其所有版本将被永久删除-测试",
        deletePermanently: "永久删除-测试",
        deleting: "删除中-测试",
      },
    },
  }),
}));

vi.mock("@/core/marketplace/hooks", () => ({
  useMarketplaceListing: mocks.useMarketplaceListing,
}));

vi.mock("@/core/report-templates", () => ({
  useArchiveReportTemplate: mocks.useArchiveReportTemplate,
  useDeleteReportTemplate: mocks.useDeleteReportTemplate,
  usePublishReportTemplate: mocks.usePublishReportTemplate,
  useReportTemplate: mocks.useReportTemplate,
  useReportTemplateVersion: mocks.useReportTemplateVersion,
  useReportTemplateVersions: mocks.useReportTemplateVersions,
  useUpdateReportTemplate: mocks.useUpdateReportTemplate,
  useValidateReportTemplate: mocks.useValidateReportTemplate,
}));

import { ReportTemplateDetailPage } from "@/components/workspace/report-templates/report-template-detail-page";

function pendingMutation() {
  return {
    isPending: false,
    mutateAsync: vi.fn(),
  };
}

describe("ReportTemplateDetailPage", () => {
  it("renders report template detail actions and labels from i18n", () => {
    mocks.useRouter.mockReturnValue({ push: vi.fn() });
    mocks.useReportTemplate.mockReturnValue({
      detail: {
        template: {
          id: "tpl_1",
          name: "tpl-demo",
          display_name: "模板一",
          description: "",
          owner_user_id: "u1",
          tenant_id: "t1",
          visibility: "private",
          status: "archived",
          current_version: 3,
          dsl_version: "1",
          tags: [],
          created_at: "2026-05-29T00:00:00Z",
          updated_at: "2026-05-29T00:00:00Z",
          etag: "etag-1",
          marketplace_source: {
            listing_id: "listing-1",
            display_name: "Source Listing",
            source_version: 1,
          },
        },
      },
      isLoading: false,
      error: null,
    });
    mocks.useReportTemplateVersions.mockReturnValue({ versions: [1, 2] });
    mocks.useReportTemplateVersion.mockReturnValue({
      snapshot: {
        dsl: { hello: "world" },
        dsl_yaml: "hello: world",
      },
    });
    mocks.useMarketplaceListing.mockReturnValue({
      listing: { template_version: 4 },
    });
    mocks.useUpdateReportTemplate.mockReturnValue(pendingMutation());
    mocks.usePublishReportTemplate.mockReturnValue(pendingMutation());
    mocks.useValidateReportTemplate.mockReturnValue(pendingMutation());
    mocks.useArchiveReportTemplate.mockReturnValue(pendingMutation());
    mocks.useDeleteReportTemplate.mockReturnValue(pendingMutation());

    const html = renderToStaticMarkup(
      React.createElement(ReportTemplateDetailPage, { templateId: "tpl_1" }),
    );

    expect(html).toContain("返回模板列表-测试");
    expect(html).toContain("私有-测试");
    expect(html).toContain("已归档-测试");
    expect(html).toContain("来自市场-测试");
    expect(html).toContain("有更新-测试");
    expect(html).toContain("校验 DSL-测试");
    expect(html).toContain("保存草稿-测试");
    expect(html).toContain("发布新版本-测试");
    expect(html).toContain("归档-测试");
    expect(html).toContain("删除-测试");
    expect(html).toContain("版本列表-测试");
    expect(html).toContain("工作草稿-测试");
    expect(html).toContain("DSL JSON-测试");
    expect(html).toContain("DSL YAML-测试");
    expect(html).toContain("删除模板-测试");
    expect(html).toContain("永久删除-测试");
    expect(html).not.toContain("Back to report templates");
    expect(html).not.toContain("Validate DSL");
    expect(html).not.toContain("Publish new version");
  });
});
