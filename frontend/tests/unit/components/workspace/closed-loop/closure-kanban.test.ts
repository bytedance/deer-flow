import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";

import { ClosureKanban } from "@/components/workspace/closed-loop/closure-kanban";
import type * as CoreClosedLoopModule from "@/core/closed-loop";
import type { ClosureTicket } from "@/core/closed-loop";

const mocks = vi.hoisted(() => ({
  useClosureTickets: vi.fn(),
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

function ticket(id: string, status: ClosureTicket["status"]): ClosureTicket {
  return {
    id,
    tenant_id: "default",
    title: `Ticket ${id}`,
    description: null,
    status,
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
  };
}

describe("ClosureKanban", () => {
  test("groups tickets by status into 5 columns", () => {
    mocks.useClosureTickets.mockReturnValue({
      tickets: [
        ticket("a", "pending"),
        ticket("b", "assigned"),
        ticket("c", "in_progress"),
        ticket("d", "pending_verification"),
        ticket("e", "closed"),
      ],
      isLoading: false,
      error: null,
    });

    const html = renderToStaticMarkup(
      React.createElement(ClosureKanban, { onSelect: vi.fn() }),
    );
    expect(html).toContain("待派单");
    expect(html).toContain("已派单");
    expect(html).toContain("处置中");
    expect(html).toContain("待验证");
    expect(html).toContain("已关闭");
    expect(html).toContain("Ticket a");
    expect(html).toContain("Ticket e");
  });

  test("shows loading state", () => {
    mocks.useClosureTickets.mockReturnValue({
      tickets: [],
      isLoading: true,
      error: null,
    });
    const html = renderToStaticMarkup(
      React.createElement(ClosureKanban, { onSelect: vi.fn() }),
    );
    expect(html).toContain("加载中");
  });
});
