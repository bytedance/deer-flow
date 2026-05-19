import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";

import { ClosureList } from "@/components/workspace/closed-loop/closure-list";
import type * as CoreClosedLoopModule from "@/core/closed-loop";
import type { ClosureTicket } from "@/core/closed-loop";

const mocks = vi.hoisted(() => ({
  useClosureTickets: vi.fn(),
  useRouter: vi.fn(),
  useSearchParams: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: mocks.useRouter,
  useSearchParams: mocks.useSearchParams,
}));

vi.mock("@/core/closed-loop", async () => {
  const actual = await vi.importActual<typeof CoreClosedLoopModule>(
    "@/core/closed-loop",
  );
  return {
    ...actual,
    useClosureTickets: mocks.useClosureTickets,
  };
});

function makeTicket(overrides: Partial<ClosureTicket>): ClosureTicket {
  return {
    id: overrides.id ?? "tkt-aaaaaaaaaaaaaaaa",
    tenant_id: "default",
    title: "测试单",
    description: null,
    status: "pending",
    priority: "normal",
    severity: null,
    device_id: null,
    device_name: null,
    created_by: "u1",
    assignee_id: null,
    verifier_id: null,
    source_type: "manual",
    source_run_id: null,
    source_thread_id: null,
    metadata: {},
    due_at: null,
    is_overdue: false,
    created_at: "2026-05-01T00:00:00Z",
    updated_at: "2026-05-01T00:00:00Z",
    assigned_at: null,
    started_at: null,
    submitted_at: null,
    closed_at: null,
    ...overrides,
  };
}

describe("ClosureList", () => {
  test("shows empty state when no tickets", () => {
    mocks.useRouter.mockReturnValue({ replace: vi.fn() });
    mocks.useSearchParams.mockReturnValue(new URLSearchParams(""));
    mocks.useClosureTickets.mockReturnValue({
      tickets: [],
      meta: { total: 0, page: 1, page_size: 50 },
      isLoading: false,
      error: null,
    });

    const html = renderToStaticMarkup(
      React.createElement(ClosureList, { onSelect: vi.fn() }),
    );
    expect(html).toContain("没有符合条件的闭环单");
  });

  test("highlights overdue rows", () => {
    mocks.useRouter.mockReturnValue({ replace: vi.fn() });
    mocks.useSearchParams.mockReturnValue(new URLSearchParams(""));
    mocks.useClosureTickets.mockReturnValue({
      tickets: [
        makeTicket({
          id: "tkt-overdueoverdueover",
          title: "过期单",
          is_overdue: true,
          due_at: "2026-04-01T00:00:00Z",
        }),
      ],
      meta: { total: 1, page: 1, page_size: 50 },
      isLoading: false,
      error: null,
    });

    const html = renderToStaticMarkup(
      React.createElement(ClosureList, { onSelect: vi.fn() }),
    );
    expect(html).toContain("过期单");
    expect(html).toContain("超期");
    expect(html).toContain("bg-red-500/5");
  });
});
