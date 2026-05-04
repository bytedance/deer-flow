import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  createTenant,
  getAdminStats,
  getAdminUsage,
  getBudgetStatus,
  getCostBreakdown,
  getCostSummary,
  listTenants,
  updateBudget,
  updateTenant,
} from "@/core/admin/api";

const BASE = "http://localhost:8001";

function mockFetch(response: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(response),
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch({}));
  vi.stubEnv("NEXT_PUBLIC_BACKEND_BASE_URL", BASE);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("getAdminStats", () => {
  test("returns parsed stats", async () => {
    const stats = { total_tenants: 5, active_tenants_today: 3 };
    vi.stubGlobal("fetch", mockFetch(stats));

    const result = await getAdminStats();
    expect(result).toEqual(stats);
  });

  test("throws on error response", async () => {
    vi.stubGlobal("fetch", mockFetch({ detail: "Forbidden" }, 403));

    await expect(getAdminStats()).rejects.toThrow("Forbidden");
  });
});

describe("listTenants", () => {
  test("returns tenant list", async () => {
    const tenants = [{ tenant_id: "t1", name: "Tenant 1" }];
    vi.stubGlobal("fetch", mockFetch(tenants));

    const result = await listTenants();
    expect(result).toEqual(tenants);
  });
});

describe("createTenant", () => {
  test("posts and returns new tenant", async () => {
    const tenant = { tenant_id: "new", name: "New" };
    vi.stubGlobal("fetch", mockFetch(tenant));

    const result = await createTenant({ tenant_id: "new", name: "New" });
    expect(result).toEqual(tenant);
  });
});

describe("updateTenant", () => {
  test("puts and returns updated tenant", async () => {
    const tenant = { tenant_id: "t1", name: "Updated" };
    vi.stubGlobal("fetch", mockFetch(tenant));

    const result = await updateTenant("t1", { name: "Updated" });
    expect(result).toEqual(tenant);
  });
});

describe("getAdminUsage", () => {
  test("returns usage records without filters", async () => {
    const records = [{ timestamp: "2026-01-01", tenant_id: "t1", model_name: "gpt-4", input_tokens: 100, output_tokens: 50, total_tokens: 150, cost_usd: 0.01, thread_id: null }];
    vi.stubGlobal("fetch", mockFetch(records));

    const result = await getAdminUsage();
    expect(result).toEqual(records);
  });

  test("appends date query params", async () => {
    const fetchMock = mockFetch([]);
    vi.stubGlobal("fetch", fetchMock);

    await getAdminUsage("2026-01-01", "2026-01-31");

    const url = fetchMock.mock.calls[0]![0] as string;
    expect(url).toContain("start_date=2026-01-01");
    expect(url).toContain("end_date=2026-01-31");
  });
});

describe("getCostSummary", () => {
  test("returns cost summary", async () => {
    const summary = { today_cost_usd: 1.5, month_cost_usd: 45.0, total_cost_usd: 500.0, today_tokens: 10000, month_tokens: 300000 };
    vi.stubGlobal("fetch", mockFetch(summary));

    const result = await getCostSummary();
    expect(result).toEqual(summary);
  });
});

describe("getCostBreakdown", () => {
  test("returns breakdown items", async () => {
    const items = [{ date: "2026-01-01", model_name: "gpt-4", input_tokens: 100, output_tokens: 50, cost_usd: 0.01 }];
    vi.stubGlobal("fetch", mockFetch(items));

    const result = await getCostBreakdown();
    expect(result).toEqual(items);
  });
});

describe("getBudgetStatus", () => {
  test("returns budget status", async () => {
    const budget = { daily_cost: 10, daily_limit: 100, daily_remaining: 90, daily_pct: 10, monthly_cost: 200, monthly_limit: 1000, monthly_remaining: 800, monthly_pct: 20, is_exceeded: false, alert_triggered: false };
    vi.stubGlobal("fetch", mockFetch(budget));

    const result = await getBudgetStatus();
    expect(result).toEqual(budget);
  });
});

describe("updateBudget", () => {
  test("puts and returns updated budget", async () => {
    const budget = { daily_cost: 0, daily_limit: 200, daily_remaining: 200, daily_pct: 0, monthly_cost: 0, monthly_limit: 2000, monthly_remaining: 2000, monthly_pct: 0, is_exceeded: false, alert_triggered: false };
    vi.stubGlobal("fetch", mockFetch(budget));

    const result = await updateBudget({ daily_limit_usd: 200 });
    expect(result).toEqual(budget);
  });
});
