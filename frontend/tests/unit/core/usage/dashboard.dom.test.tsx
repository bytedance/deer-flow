import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  usage: rs.fn(),
  runs: rs.fn(),
  permissions: ["runs:read"],
  staticMode: false,
}));
rs.mock("@/core/usage/api", () => ({
  fetchUsage: mocks.usage,
  fetchUsageRuns: mocks.runs,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "alice", permissions: mocks.permissions } }),
}));
rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => mocks.staticMode,
}));

import { UsageDashboard } from "@/components/workspace/usage/usage-dashboard";
import { GatewayApiError } from "@/core/api/errors";
import { I18nProvider } from "@/core/i18n/context";

const clients: QueryClient[] = [];
const usage = {
  total_cost: 0.005,
  currency: "USD",
  days: [
    {
      date: "2026-10-25",
      total_tokens: 100,
      input_tokens: 70,
      output_tokens: 30,
      runs: 1,
      cost: 0.005,
    },
  ],
  by_model: {
    flash: {
      tokens: 100,
      runs: 1,

      input_tokens: 70,
      cache_read_tokens: 10,
      cost: 0.005,
    },
  },
  total_tokens: 100,
  total_runs: 1,
};

function renderDashboard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale="en-US">
        <UsageDashboard />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.permissions = ["runs:read"];
  mocks.staticMode = false;
  mocks.usage.mockReset().mockResolvedValue(usage);
  mocks.runs.mockReset().mockResolvedValue({ runs: [], has_more: false });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

test("switches the server-side period and shows only token usage", async () => {
  renderDashboard();
  await screen.findByRole("heading", { name: "Usage by model" });
  expect(screen.getByTestId("usage-total-tokens").textContent).toBe("100");
  expect(screen.queryByTestId("usage-total-cost")).toBeNull();
  expect(screen.queryByText("Estimated cost")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Last 30 days" }));
  await waitFor(() =>
    expect(mocks.usage.mock.calls.some((call) => call[0] === 30)).toBe(true),
  );
});

test("does not issue requests without runs:read", () => {
  mocks.permissions = [];
  renderDashboard();
  expect(screen.getByText(/You do not have permission/)).toBeTruthy();
  expect(mocks.usage).not.toHaveBeenCalled();
  expect(mocks.runs).not.toHaveBeenCalled();
});

test("accepts upstream cost fields while presenting run tokens", async () => {
  mocks.runs.mockResolvedValue({
    runs: [
      {
        run_id: "r1",
        thread_id: "t1",
        thread_title: "Recent chat",
        assistant_id: null,
        status: "success",
        model_name: "flash",
        created_at: null,
        updated_at: null,
        duration_seconds: 1,
        total_tokens: 42,
        message_count: 2,
        error: null,
        cost: 0.1,
        currency: "CNY",
      },
    ],
    has_more: false,
  });
  renderDashboard();
  await screen.findByRole("link", { name: "Recent chat" });
  expect(screen.getByText("42")).toBeTruthy();
  expect(
    screen.queryByRole("columnheader", { name: "Estimated cost" }),
  ).toBeNull();
});

test("static demos never request personal usage data", () => {
  mocks.staticMode = true;
  renderDashboard();
  expect(
    screen.getByText("Usage reporting is not available in the static demo."),
  ).toBeTruthy();
  expect(mocks.usage).not.toHaveBeenCalled();
  expect(mocks.runs).not.toHaveBeenCalled();
});

test("does not display the previous period's totals while a new period loads", async () => {
  let finish: (value: typeof usage) => void = () => undefined;
  const pending = new Promise<typeof usage>((resolve) => {
    finish = resolve;
  });
  mocks.usage.mockImplementation((days: number) =>
    days === 30 ? pending : Promise.resolve(usage),
  );
  renderDashboard();
  await screen.findByTestId("usage-total-tokens");
  fireEvent.click(screen.getByRole("button", { name: "Last 30 days" }));
  expect(screen.queryByTestId("usage-total-tokens")).toBeNull();
  finish({ ...usage, total_tokens: 300 });
  await waitFor(() =>
    expect(screen.getByTestId("usage-total-tokens").textContent).toBe("300"),
  );
});

test("errors show a retry instead of zero-valued summary cards", async () => {
  mocks.usage.mockRejectedValue(
    new GatewayApiError({
      message: "unavailable",
      status: 503,
      code: null,
      params: {},
      rawMessage: "",
    }),
  );
  renderDashboard();
  await screen.findByText(/requires a SQLite or PostgreSQL/);
  expect(screen.queryByTestId("usage-total-tokens")).toBeNull();
  mocks.usage.mockResolvedValue(usage);
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByTestId("usage-total-tokens");
});

test("run pagination resets when the failure filter changes", async () => {
  mocks.runs.mockResolvedValue({ runs: [], has_more: true });
  renderDashboard();
  const next = await screen.findByRole("button", { name: "Next page" });
  await waitFor(() => expect(next).toHaveProperty("disabled", false));
  fireEvent.click(next);
  await waitFor(() =>
    expect(mocks.runs.mock.calls.some((call) => call[0] === 20)).toBe(true),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Run status" }), {
    target: { value: "error" },
  });
  await waitFor(() =>
    expect(
      mocks.runs.mock.calls.some(
        (call) => call[0] === 0 && call[1] === "error",
      ),
    ).toBe(true),
  );
  expect(screen.getByText("Page 1")).toBeTruthy();
});
