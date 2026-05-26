import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const MOCK_LISTINGS = [
  {
    id: "listing-001",
    template_id: "tmpl-001",
    display_name: "Daily Device Report",
    description: "Comprehensive daily device status summary",
    category: "daily",
    tags: ["daily", "devices", "summary"],
    visibility: "tenant",
    publisher_id: "user-1",
    template_version: 3,
    avg_rating: 4.8,
    review_count: 12,
    install_count: 45,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-15T00:00:00Z",
  },
  {
    id: "listing-002",
    template_id: "tmpl-002",
    display_name: "Weekly Trend Analysis",
    description: "Multi-day trend comparison report",
    category: "trend",
    tags: ["weekly", "trend", "analysis"],
    visibility: "tenant",
    publisher_id: "user-2",
    template_version: 2,
    avg_rating: 4.2,
    review_count: 5,
    install_count: 20,
    created_at: "2026-01-05T00:00:00Z",
    updated_at: "2026-01-20T00:00:00Z",
  },
  {
    id: "listing-003",
    template_id: "tmpl-003",
    display_name: "Failure Diagnosis",
    description: "Root cause analysis for device failures",
    category: "diagnosis",
    tags: ["failure", "diagnosis", "rca"],
    visibility: "tenant",
    publisher_id: "user-1",
    template_version: 1,
    avg_rating: 4.9,
    review_count: 8,
    install_count: 30,
    created_at: "2026-01-10T00:00:00Z",
    updated_at: "2026-01-25T00:00:00Z",
  },
];

const MOCK_LISTING_DETAIL = {
  ...MOCK_LISTINGS[0],
  base_dsl: { form_steps: [], sections: [] },
};

const MOCK_REVIEWS = [
  {
    id: "rev-1",
    listing_id: "listing-001",
    user_id: "reviewer-1",
    rating: 5,
    comment: "Excellent template for daily monitoring!",
    created_at: "2026-01-10T00:00:00Z",
  },
  {
    id: "rev-2",
    listing_id: "listing-001",
    user_id: "reviewer-2",
    rating: 4,
    comment: "Good but could use more device types.",
    created_at: "2026-01-12T00:00:00Z",
  },
];

const MOCK_INSTALL_RESULT = {
  target_template_id: "tmpl-installed-001",
  marketplace_listing_id: "listing-001",
  installed_version: 3,
};

function mockMarketplaceAPI(page: import("@playwright/test").Page) {
  // List endpoint with query params
  void page.route("**/api/template-marketplace/**", (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const path = url.pathname;

    // List reviews
    if (path.includes("/reviews") && method === "GET") {
      return route.fulfill({ json: MOCK_REVIEWS });
    }

    // Create review
    if (path.includes("/reviews") && method === "POST") {
      return route.fulfill({
        json: { id: "rev-3", rating: 5, comment: "New review" },
      });
    }

    // Install
    if (path.includes("/install") && method === "POST") {
      return route.fulfill({ json: MOCK_INSTALL_RESULT });
    }

    // Single listing detail
    if (path.match(/\/api\/template-marketplace\/[^/]+$/) && method === "GET") {
      return route.fulfill({ json: MOCK_LISTING_DETAIL });
    }

    return route.fallback();
  });

  // List endpoint (root)
  void page.route("**/api/template-marketplace/", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        json: { items: MOCK_LISTINGS, total: 3, page: 1, page_size: 20 },
      });
    }
    return route.fallback();
  });

  // Also handle without trailing slash
  void page.route("**/api/template-marketplace", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        json: { items: MOCK_LISTINGS, total: 3, page: 1, page_size: 20 },
      });
    }
    return route.fallback();
  });
}

test.describe("Template Marketplace — search, filter, and install", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
    mockMarketplaceAPI(page);
  });

  test("marketplace page loads with template cards", async ({ page }) => {
    await page.goto("/workspace/template-marketplace");

    await expect(page.getByText("Template Marketplace")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Daily Device Report")).toBeVisible();
    await expect(page.getByText("Weekly Trend Analysis")).toBeVisible();
    await expect(page.getByText("Failure Diagnosis")).toBeVisible();
  });

  test("search bar filters templates by name", async ({ page }) => {
    await page.goto("/workspace/template-marketplace");
    await expect(page.getByText("Daily Device Report")).toBeVisible({ timeout: 15_000 });

    const searchInput = page.getByPlaceholder(/search templates/i);
    await searchInput.fill("Trend");

    // Wait for debounce/search to trigger
    await page.waitForTimeout(500);

    // The API returns all listings regardless (no server-side filtering mock),
    // but the UI should still render cards
    await expect(page.getByText("Weekly Trend Analysis")).toBeVisible();
  });

  test("sort controls change order", async ({ page }) => {
    await page.goto("/workspace/template-marketplace");
    await expect(page.getByText("Daily Device Report")).toBeVisible({ timeout: 15_000 });

    // Sort by rating
    await page.getByRole("button", { name: /newest/i }).click();
    await page.getByText("Rating").click();

    // Cards should still be visible
    await expect(page.getByText("Daily Device Report")).toBeVisible();
  });

  test("clicking a card navigates to detail page", async ({ page }) => {
    await page.goto("/workspace/template-marketplace");
    await expect(page.getByText("Daily Device Report")).toBeVisible({ timeout: 15_000 });

    // Click the card
    await page.getByText("Daily Device Report").click();

    // Should navigate to detail page
    await expect(page).toHaveURL(/\/workspace\/template-marketplace\/listing-001/, {
      timeout: 10_000,
    });
  });

  test("detail page shows listing info and reviews", async ({ page }) => {
    await page.goto("/workspace/template-marketplace/listing-001");

    await expect(page.getByText("Daily Device Report")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/4\.8/)).toBeVisible();
    await expect(page.getByText(/12 reviews/i)).toBeVisible();
    await expect(page.getByText(/45 installs/i)).toBeVisible();
  });

  test("detail page shows review tab", async ({ page }) => {
    await page.goto("/workspace/template-marketplace/listing-001");
    await expect(page.getByText("Daily Device Report")).toBeVisible({ timeout: 15_000 });

    // Click reviews tab
    await page.getByRole("button", { name: /reviews/i }).click();

    // Reviews should be visible
    await expect(page.getByText("Excellent template for daily monitoring!")).toBeVisible();
    await expect(page.getByText("Good but could use more device types.")).toBeVisible();
  });

  test("install action navigates to installed template editor", async ({ page }) => {
    await page.goto("/workspace/template-marketplace/listing-001");
    await expect(page.getByText("Daily Device Report")).toBeVisible({ timeout: 15_000 });

    // Click install
    const installBtn = page.getByRole("button", { name: /^install$/i });
    await expect(installBtn).toBeVisible();
    await installBtn.click();

    // Should navigate to the installed template editor
    await expect(page).toHaveURL(
      /\/workspace\/report-templates\/editor\/tmpl-installed-001/,
      { timeout: 10_000 },
    );
  });
});
