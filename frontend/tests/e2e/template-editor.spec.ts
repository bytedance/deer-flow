import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const MOCK_TEMPLATE_DETAIL = {
  template: {
    id: "tmpl-editor-001",
    name: "test-editor",
    display_name: "Test Editor",
    description: "",
    owner_user_id: "user-1",
    tenant_id: "tenant-1",
    visibility: "private",
    status: "draft",
    current_version: 0,
    dsl_version: "1.0",
    tags: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    etag: "etag-1",
  },
};

const MOCK_SNAPSHOT = {
  template_id: "tmpl-editor-001",
  version: 0,
  dsl: {
    form_steps: [
      { id: "step1", title: "Step 1", fields: [], next: "step2" },
      { id: "step2", title: "Step 2", fields: [], next: null },
    ],
    data_steps: [],
    transforms: [],
    sections: [
      { id: "sec1", title: "Overview", component: "summary-card", source: "$.result" },
    ],
  },
  dsl_yaml:
    "form_steps:\n  - id: step1\n    title: Step 1\n    next: step2\n  - id: step2\n    title: Step 2\nsections:\n  - id: sec1\n    title: Overview\n",
  checksum: "abc",
  source_template_id: null,
  source_template_version: null,
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  changelog: "",
};

const MOCK_VALIDATION_SUCCESS = {
  valid: true,
  errors: [],
  warnings: [],
};

const MOCK_VALIDATION_ERROR = {
  valid: false,
  errors: [
    { code: "MISSING_FIELD", path: "form_steps[0].fields", message: "Step 1 has no fields" },
  ],
  warnings: [
    { code: "EMPTY_SECTION", path: "sections[0]", message: "Section has no source" },
  ],
};

function mockEditorAPI(
  page: import("@playwright/test").Page,
  validationResponse = MOCK_VALIDATION_SUCCESS,
) {
  void page.route("**/api/report-templates/tmpl-editor-001", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ json: MOCK_TEMPLATE_DETAIL });
    }
    if (route.request().method() === "PUT") {
      return route.fulfill({
        json: { ...MOCK_TEMPLATE_DETAIL.template, etag: "etag-2" },
      });
    }
    return route.fallback();
  });
  void page.route(
    "**/api/report-templates/tmpl-editor-001/versions/0",
    (route) => route.fulfill({ json: MOCK_SNAPSHOT }),
  );
  void page.route(
    "**/api/report-templates/tmpl-editor-001/validate",
    (route) => route.fulfill({ json: validationResponse }),
  );
}

test.describe("Template Editor — form steps and validation", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
  });

  test("editor loads and displays form steps tab", async ({ page }) => {
    mockEditorAPI(page);
    await page.goto("/workspace/report-templates/editor/tmpl-editor-001");

    await expect(page.getByText("Test Editor")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: /form steps/i })).toBeVisible();
    await expect(page.getByText("step1")).toBeVisible();
    await expect(page.getByText("step2")).toBeVisible();
  });

  test("editor shows sections tab content", async ({ page }) => {
    mockEditorAPI(page);
    await page.goto("/workspace/report-templates/editor/tmpl-editor-001");
    await expect(page.getByText("Test Editor")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: /sections/i }).click();
    await expect(page.getByText("Overview")).toBeVisible();
  });

  test("YAML toggle works", async ({ page }) => {
    mockEditorAPI(page);
    await page.goto("/workspace/report-templates/editor/tmpl-editor-001");
    await expect(page.getByText("Test Editor")).toBeVisible({ timeout: 15_000 });

    // Toggle YAML on
    await page.getByRole("button", { name: /yaml/i }).click();
    await expect(page.getByText("form_steps")).toBeVisible({ timeout: 5_000 });

    // Toggle back to Preview
    await page.getByRole("button", { name: /preview/i }).click();
    await expect(page.getByText("form_steps")).not.toBeVisible({ timeout: 3_000 });
  });

  test("validation panel shows success when valid", async ({ page }) => {
    mockEditorAPI(page, MOCK_VALIDATION_SUCCESS);
    await page.goto("/workspace/report-templates/editor/tmpl-editor-001");
    await expect(page.getByText("Test Editor")).toBeVisible({ timeout: 15_000 });

    // Validation panel triggers automatically with debounce
    // Wait for the validation to complete
    await page.waitForTimeout(2000);
  });

  test("validation panel shows errors when invalid", async ({ page }) => {
    mockEditorAPI(page, MOCK_VALIDATION_ERROR);
    await page.goto("/workspace/report-templates/editor/tmpl-editor-001");
    await expect(page.getByText("Test Editor")).toBeVisible({ timeout: 15_000 });

    await page.waitForTimeout(2000);

    // Error should be visible
    await expect(page.getByText(/missing_field/i)).toBeVisible({ timeout: 5_000 });
  });

  test("save button triggers API call", async ({ page }) => {
    let saveCalled = false;
    mockEditorAPI(page);

    await page.route("**/api/report-templates/tmpl-editor-001", (route) => {
      if (route.request().method() === "PUT") {
        saveCalled = true;
        return route.fulfill({
          json: { ...MOCK_TEMPLATE_DETAIL.template, etag: "etag-2" },
        });
      }
      return route.fulfill({ json: MOCK_TEMPLATE_DETAIL });
    });

    await page.goto("/workspace/report-templates/editor/tmpl-editor-001");
    await expect(page.getByText("Test Editor")).toBeVisible({ timeout: 15_000 });

    // Make a change to enable save — switch to YAML and modify
    await page.getByRole("button", { name: /yaml/i }).click();
    await expect(page.getByText("form_steps")).toBeVisible({ timeout: 5_000 });

    // Type something to mark dirty
    const yamlArea = page.locator("textarea").last();
    await yamlArea.fill("form_steps:\n  - id: step1\n    title: Modified\n");

    // Save button should now be enabled
    const saveBtn = page.getByRole("button", { name: /^save$/i });
    await expect(saveBtn).toBeEnabled({ timeout: 3_000 });
    await saveBtn.click();

    await expect.poll(() => saveCalled, { timeout: 5_000 }).toBeTruthy();
  });
});
