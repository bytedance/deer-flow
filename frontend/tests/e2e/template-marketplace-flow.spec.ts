import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const MOCK_BLUEPRINTS = [
  {
    id: "daily-report",
    name: "Daily Report",
    description: "Daily device status summary",
    category: "daily",
    tags: ["daily", "summary"],
    form_steps_count: 2,
    sections_count: 4,
  },
  {
    id: "trend-analysis",
    name: "Trend Analysis",
    description: "Multi-day trend comparison",
    category: "trend",
    tags: ["trend", "analysis"],
    form_steps_count: 3,
    sections_count: 5,
  },
];

const MOCK_BLUEPRINT_DETAIL = {
  ...MOCK_BLUEPRINTS[0],
  base_dsl: {
    form_steps: [{ id: "step1", fields: [] }],
    data_steps: [],
    transforms: [],
    sections: [{ id: "sec1", title: "Overview", component: "summary-card" }],
  },
  user_configurable: ["name", "description"],
  recommended_scripts: ["collect_daily_metrics"],
  preview_sections: [{ id: "sec1", title: "Overview" }],
};

const MOCK_CREATED_TEMPLATE = {
  template_id: "tmpl-001",
  name: "my-daily-report",
  display_name: "My Daily Report",
};

const MOCK_TEMPLATE_DETAIL = {
  template: {
    id: "tmpl-001",
    name: "my-daily-report",
    display_name: "My Daily Report",
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
  template_id: "tmpl-001",
  version: 0,
  dsl: {
    form_steps: [{ id: "step1", fields: [] }],
    data_steps: [],
    transforms: [],
    sections: [{ id: "sec1", title: "Overview", component: "summary-card" }],
  },
  dsl_yaml: "form_steps:\n  - id: step1\n",
  checksum: "abc",
  source_template_id: null,
  source_template_version: null,
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  changelog: "",
};

const MOCK_LISTING = {
  id: "listing-001",
  template_id: "tmpl-001",
  display_name: "My Daily Report",
  description: "A great daily report template",
  category: "daily",
  tags: ["daily"],
  visibility: "tenant",
  publisher_id: "user-1",
  template_version: 1,
  avg_rating: 4.5,
  review_count: 2,
  install_count: 10,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

const MOCK_INSTALL_RESULT = {
  target_template_id: "tmpl-installed",
  marketplace_listing_id: "listing-001",
  installed_version: 1,
};

function mockBlueprintAPI(page: import("@playwright/test").Page) {
  void page.route("**/api/template-blueprints/", (route) => {
    return route.fulfill({ json: MOCK_BLUEPRINTS });
  });
  void page.route("**/api/template-blueprints/daily-report", (route) => {
    return route.fulfill({ json: MOCK_BLUEPRINT_DETAIL });
  });
  void page.route(
    "**/api/template-blueprints/daily-report/create-template",
    (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ json: MOCK_CREATED_TEMPLATE });
      }
      return route.fallback();
    },
  );
}

function mockTemplateAPI(page: import("@playwright/test").Page) {
  void page.route("**/api/report-templates/tmpl-001", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ json: MOCK_TEMPLATE_DETAIL });
    }
    if (route.request().method() === "PUT") {
      return route.fulfill({ json: { ...MOCK_TEMPLATE_DETAIL.template, etag: "etag-2" } });
    }
    return route.fallback();
  });
  void page.route(
    "**/api/report-templates/tmpl-001/versions/0",
    (route) => route.fulfill({ json: MOCK_SNAPSHOT }),
  );
  void page.route(
    "**/api/report-templates/tmpl-001/validate",
    (route) =>
      route.fulfill({
        json: { valid: true, errors: [], warnings: [] },
      }),
  );
  void page.route(
    "**/api/report-templates/tmpl-001/publish",
    (route) =>
      route.fulfill({
        json: { ...MOCK_TEMPLATE_DETAIL.template, status: "published", current_version: 1 },
      }),
  );
  void page.route(
    "**/api/report-templates/tmpl-001/publish-to-marketplace",
    (route) =>
      route.fulfill({ json: MOCK_LISTING }),
  );
}

function mockMarketplaceAPI(page: import("@playwright/test").Page) {
  void page.route("**/api/template-marketplace/**", (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (url.endsWith("/install") && method === "POST") {
      return route.fulfill({ json: MOCK_INSTALL_RESULT });
    }
    if (url.endsWith("/reviews") && method === "POST") {
      return route.fulfill({ json: { id: "rev-1", rating: 5, comment: "Great!" } });
    }
    if (url.endsWith("/reviews") && method === "GET") {
      return route.fulfill({ json: [] });
    }
    if (method === "GET") {
      return route.fulfill({ json: MOCK_LISTING });
    }
    return route.fallback();
  });
  void page.route("**/api/template-marketplace/", (route) => {
    return route.fulfill({
      json: { items: [MOCK_LISTING], total: 1, page: 1, page_size: 20 },
    });
  });
}

test.describe("Blueprint → Editor → Publish → Marketplace → Install flow", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
    mockBlueprintAPI(page);
    mockTemplateAPI(page);
    mockMarketplaceAPI(page);
  });

  test("blueprint catalog loads and shows cards", async ({ page }) => {
    await page.goto("/workspace/report-templates/new");
    await expect(page.getByText("Create from Blueprint")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Daily Report")).toBeVisible();
    await expect(page.getByText("Trend Analysis")).toBeVisible();
  });

  test("selecting a blueprint opens create dialog", async ({ page }) => {
    await page.goto("/workspace/report-templates/new");
    await expect(page.getByText("Daily Report")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: /use blueprint/i }).first().click();

    await expect(page.getByText("Create from: Daily Report")).toBeVisible();
    await expect(page.getByPlaceholder("My Custom Report")).toBeVisible();
  });

  test("full flow: blueprint → editor → save → publish", async ({ page }) => {
    await page.goto("/workspace/report-templates/new");
    await expect(page.getByText("Daily Report")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: /use blueprint/i }).first().click();
    await page.getByPlaceholder("My Custom Report").fill("My Daily Report");
    await page.getByRole("button", { name: /create template/i }).click();

    // Should navigate to editor
    await expect(page).toHaveURL(/\/workspace\/report-templates\/editor\/tmpl-001/, {
      timeout: 15_000,
    });

    // Editor loads
    await expect(page.getByText("My Daily Report")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: /save/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /publish/i })).toBeVisible();
  });
});
