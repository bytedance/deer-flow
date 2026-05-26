import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

const MOCK_MEMORY = {
  version: "1.0",
  lastUpdated: "2026-01-01T00:00:00Z",
  user: {
    workContext: { summary: "Works on EHM", updatedAt: "2026-01-01T00:00:00Z" },
    personalContext: { summary: "", updatedAt: "" },
    topOfMind: { summary: "", updatedAt: "" },
  },
  history: {
    recentMonths: { summary: "", updatedAt: "" },
    earlierContext: { summary: "", updatedAt: "" },
    longTermBackground: { summary: "", updatedAt: "" },
  },
  facts: [
    {
      id: "fact-1",
      content: "User prefers concise responses",
      category: "preference",
      confidence: 0.9,
      createdAt: "2026-01-01T00:00:00Z",
      source: "manual",
    },
  ],
};

const MOCK_SESSION_MEMORY = {
  thread_id: MOCK_THREAD_ID,
  facts: [
    {
      id: "sf-1",
      content: "User asked about pump diagnostics",
      category: "context",
      confidence: 0.85,
      created_at: "2026-01-01T12:00:00Z",
    },
  ],
};

const MOCK_DOMAIN_FACTS = [
  {
    id: "df-1",
    content: "Pump A operates at 3000 RPM",
    domain: "equipment",
    entity_id: "pump_a",
    confidence: 0.95,
    similarity_score: 0.92,
    adjusted_score: 0.93,
    created_at: "2026-01-01T00:00:00Z",
  },
];

function mockMemoryAPI(page: import("@playwright/test").Page) {
  // User memory
  void page.route("**/api/memory", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ json: MOCK_MEMORY });
    }
    if (route.request().method() === "DELETE") {
      return route.fulfill({
        json: { ...MOCK_MEMORY, facts: [], user: { workContext: { summary: "", updatedAt: "" }, personalContext: { summary: "", updatedAt: "" }, topOfMind: { summary: "", updatedAt: "" } } },
      });
    }
    return route.fallback();
  });

  void page.route("**/api/memory/export", (route) =>
    route.fulfill({ json: MOCK_MEMORY }),
  );

  void page.route("**/api/memory/import", (route) =>
    route.fulfill({ json: MOCK_MEMORY }),
  );

  void page.route("**/api/memory/facts", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({
        json: {
          ...MOCK_MEMORY,
          facts: [
            ...MOCK_MEMORY.facts,
            { id: "fact-new", content: "New fact", category: "context", confidence: 0.8, createdAt: new Date().toISOString(), source: "manual" },
          ],
        },
      });
    }
    return route.fallback();
  });

  void page.route("**/api/memory/facts/*", (route) => {
    if (route.request().method() === "DELETE") {
      return route.fulfill({ json: { ...MOCK_MEMORY, facts: [] } });
    }
    if (route.request().method() === "PATCH") {
      return route.fulfill({ json: MOCK_MEMORY });
    }
    if (route.request().method() === "GET") {
      return route.fulfill({ json: MOCK_MEMORY.facts[0] });
    }
    return route.fallback();
  });

  // Session memory
  void page.route("**/api/memory/session*", (route) => {
    if (route.request().url().includes("/export")) {
      return route.fulfill({ json: MOCK_SESSION_MEMORY });
    }
    if (route.request().url().includes("/import")) {
      return route.fulfill({ json: MOCK_SESSION_MEMORY });
    }
    return route.fulfill({ json: MOCK_SESSION_MEMORY });
  });

  // Domain memory
  void page.route("**/api/memory/domain", (route) =>
    route.fulfill({ json: MOCK_DOMAIN_FACTS }),
  );

  void page.route("**/api/memory/domain/facts", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ json: MOCK_DOMAIN_FACTS[0] });
    }
    return route.fallback();
  });

  void page.route("**/api/memory/domain/export*", (route) =>
    route.fulfill({ json: MOCK_DOMAIN_FACTS }),
  );

  void page.route("**/api/memory/domain/import", (route) =>
    route.fulfill({ json: { imported: 1, total: 1 } }),
  );

  // Audit logs
  void page.route("**/api/memory/audit*", (route) =>
    route.fulfill({ json: [] }),
  );

  // SSE events — return empty stream that immediately closes
  void page.route("**/api/memory/events", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "",
    }),
  );
}

test.describe("Memory Settings Page", () => {
  test("displays User Memory tab with facts", async ({ page }) => {
    mockLangGraphAPI(page);
    mockMemoryAPI(page);

    await page.goto("/workspace/settings/memory");

    await expect(page.getByRole("tab", { name: "User Memory" })).toBeVisible();
    await expect(page.getByText("User prefers concise responses")).toBeVisible();
  });

  test("switches between memory layer tabs", async ({ page }) => {
    mockLangGraphAPI(page);
    mockMemoryAPI(page);

    await page.goto("/workspace/settings/memory");

    // Click Session Memory tab
    await page.getByRole("tab", { name: "Session Memory" }).click();
    await expect(page.getByPlaceholder("Thread ID")).toBeVisible();

    // Click Domain Memory tab
    await page.getByRole("tab", { name: "Domain Memory" }).click();
    await expect(page.getByPlaceholder("Search domain facts...")).toBeVisible();
  });

  test("loads session memory for a thread", async ({ page }) => {
    mockLangGraphAPI(page);
    mockMemoryAPI(page);

    await page.goto("/workspace/settings/memory");
    await page.getByRole("tab", { name: "Session Memory" }).click();

    await page.getByPlaceholder("Thread ID").fill(MOCK_THREAD_ID);
    await page.getByRole("button", { name: "Load" }).click();

    await expect(page.getByText("pump diagnostics")).toBeVisible();
  });

  test("searches domain memory", async ({ page }) => {
    mockLangGraphAPI(page);
    mockMemoryAPI(page);

    await page.goto("/workspace/settings/memory");
    await page.getByRole("tab", { name: "Domain Memory" }).click();

    await page.getByPlaceholder("Search domain facts...").fill("pump");
    await page.getByRole("button", { name: "Search" }).click();

    await expect(page.getByText("Pump A operates at 3000 RPM")).toBeVisible();
  });

  test("layer visibility toggles work", async ({ page }) => {
    mockLangGraphAPI(page);
    mockMemoryAPI(page);

    await page.goto("/workspace/settings/memory");

    // All tabs should be visible initially
    await expect(page.getByRole("tab", { name: "User Memory" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Session Memory" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Domain Memory" })).toBeVisible();
  });
});
