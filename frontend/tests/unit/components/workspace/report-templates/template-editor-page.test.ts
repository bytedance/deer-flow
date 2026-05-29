import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useParams: vi.fn(),
  useRouter: vi.fn(),
  useReportTemplate: vi.fn(),
  useReportTemplateVersion: vi.fn(),
  useTemplateDSL: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: mocks.useParams,
  useRouter: mocks.useRouter,
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      editor: {
        templateEditorFallbackTitle: "editor-title-test",
        unsavedChanges: "unsaved-test",
        allSaved: "saved-test",
        preview: "preview-test",
        yaml: "yaml-test",
        save: "save-test",
        export: "export-test",
        publish: "publish-test",
        marketplace: "marketplace-test",
        formSteps: "form-steps-test",
        dataSteps: "data-steps-test",
        sections: "sections-test",
        saveSuccess: "save-success-test",
        saveFailed: "save-failed-test",
        publishSuccess: "publish-success-test",
        publishFailed: "publish-failed-test",
      },
    },
  }),
}));

vi.mock("@/core/report-templates/hooks", () => ({
  useReportTemplate: mocks.useReportTemplate,
  useReportTemplateVersion: mocks.useReportTemplateVersion,
}));

vi.mock("@/core/report-templates/api", () => ({
  updateReportTemplate: vi.fn(),
  publishReportTemplate: vi.fn(),
}));

vi.mock("@/core/report-templates/use-template-dsl", () => ({
  useTemplateDSL: mocks.useTemplateDSL,
}));

vi.mock("@/core/auth/api-error", () => ({
  applyResolvedAuthError: vi.fn(),
  resolveAuthError: vi.fn(() => null),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/components/ui/tabs", () => ({
  Tabs: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  TabsContent: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  TabsList: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  TabsTrigger: ({ children }: React.PropsWithChildren) =>
    React.createElement("button", null, children),
}));

vi.mock(
  "@/components/workspace/report-templates/editor/editor-palette",
  () => ({
    EditorPalette: () => React.createElement("div", null, "palette"),
  }),
);

vi.mock(
  "@/components/workspace/report-templates/editor/form-steps-panel",
  () => ({
    FormStepsPanel: () => React.createElement("div", null, "form-panel"),
  }),
);

vi.mock(
  "@/components/workspace/report-templates/editor/data-steps-panel",
  () => ({
    DataStepsPanel: () => React.createElement("div", null, "data-panel"),
  }),
);

vi.mock(
  "@/components/workspace/report-templates/editor/sections-panel",
  () => ({
    SectionsPanel: () => React.createElement("div", null, "sections-panel"),
  }),
);

vi.mock(
  "@/components/workspace/report-templates/editor/editor-property-panel",
  () => ({
    EditorPropertyPanel: () =>
      React.createElement("div", null, "property-panel"),
  }),
);

vi.mock(
  "@/components/workspace/report-templates/editor/yaml-editor",
  () => ({
    YamlEditor: () => React.createElement("div", null, "yaml-editor"),
  }),
);

vi.mock(
  "@/components/workspace/report-templates/editor/validation-panel",
  () => ({
    ValidationPanel: () =>
      React.createElement("div", null, "validation-panel"),
  }),
);

vi.mock(
  "@/components/workspace/report-templates/editor/editor-actions-dialog",
  () => ({
    EditorActionsDialog: () => React.createElement("div", null, "dialog"),
  }),
);

import { TemplateEditorPage } from "@/components/workspace/report-templates/editor/template-editor-page";

describe("TemplateEditorPage", () => {
  it("renders editor header labels from i18n", () => {
    mocks.useParams.mockReturnValue({ id: "tpl_editor" });
    mocks.useRouter.mockReturnValue({ push: vi.fn() });
    mocks.useReportTemplate.mockReturnValue({
      detail: {
        template: {
          id: "tpl_editor",
          display_name: "",
          status: "draft",
          current_version: 3,
          etag: "etag-1",
        },
      },
      isLoading: false,
    });
    mocks.useReportTemplateVersion.mockReturnValue({
      snapshot: { dsl: { name: "tpl_editor" } },
    });
    mocks.useTemplateDSL.mockReturnValue({
      dsl: {
        form_steps: [{ id: "step-1" }],
        data_steps: [{ id: "data-1" }],
        sections: [{ id: "section-1" }],
        transforms: [],
      },
      dslYaml: "name: tpl_editor",
      isDirty: true,
      updateFormSteps: vi.fn(),
      updateDataSteps: vi.fn(),
      updateTransforms: vi.fn(),
      updateSections: vi.fn(),
      updateDSL: vi.fn(),
      loadFromYaml: vi.fn(),
      markClean: vi.fn(),
    });

    const html = renderToStaticMarkup(
      React.createElement(TemplateEditorPage),
    );

    expect(html).toContain("editor-title-test");
    expect(html).toContain("unsaved-test");
    expect(html).toContain("yaml-test");
    expect(html).toContain("save-test");
    expect(html).toContain("export-test");
    expect(html).toContain("publish-test");
    expect(html).toContain("marketplace-test");
    expect(html).toContain("form-steps-test");
    expect(html).toContain("data-steps-test");
    expect(html).toContain("sections-test");
    expect(html).not.toContain("Template Editor");
    expect(html).not.toContain("Unsaved changes");
    expect(html).not.toContain(">Save<");
  });
});
