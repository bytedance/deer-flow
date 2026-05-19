import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";

import { ClosureActionForm } from "@/components/workspace/closed-loop/closure-action-form";
import type { ClosureTicket } from "@/core/closed-loop";

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

vi.mock("@/core/auth/AuthProvider", () => ({
  useAuth: mocks.useAuth,
}));

function makeTicket(overrides: Partial<ClosureTicket> = {}): ClosureTicket {
  return {
    id: "tkt-1",
    tenant_id: "default",
    title: "test",
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
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    assigned_at: null,
    started_at: null,
    submitted_at: null,
    closed_at: null,
    ...overrides,
  };
}

describe("ClosureActionForm", () => {
  test("pending status exposes only assign action", () => {
    mocks.useAuth.mockReturnValue({ user: { system_role: "user" } });
    const html = renderToStaticMarkup(
      React.createElement(ClosureActionForm, {
        ticket: makeTicket({ status: "pending" }),
        pending: false,
        onSubmit: vi.fn(),
      }),
    );
    expect(html).toContain("派单");
    expect(html).not.toContain("验证关闭");
    expect(html).not.toContain("退回");
  });

  test("pending_verification hides verify/reject when user lacks permission", () => {
    mocks.useAuth.mockReturnValue({ user: { system_role: "user" } });
    const html = renderToStaticMarkup(
      React.createElement(ClosureActionForm, {
        ticket: makeTicket({ status: "pending_verification" }),
        pending: false,
        onSubmit: vi.fn(),
      }),
    );
    expect(html).toContain("当前状态下无可执行动作");
    expect(html).not.toContain("验证关闭");
    expect(html).not.toContain("退回");
  });

  test("pending_verification shows verify/reject for tenant_admin", () => {
    mocks.useAuth.mockReturnValue({ user: { system_role: "tenant_admin" } });
    const html = renderToStaticMarkup(
      React.createElement(ClosureActionForm, {
        ticket: makeTicket({ status: "pending_verification" }),
        pending: false,
        onSubmit: vi.fn(),
      }),
    );
    expect(html).toContain("验证关闭");
    expect(html).toContain("退回");
  });

  test("closed status renders no actions", () => {
    mocks.useAuth.mockReturnValue({ user: { system_role: "tenant_admin" } });
    const html = renderToStaticMarkup(
      React.createElement(ClosureActionForm, {
        ticket: makeTicket({ status: "closed" }),
        pending: false,
        onSubmit: vi.fn(),
      }),
    );
    expect(html).toContain("当前状态下无可执行动作");
  });

  test("in_progress status exposes submit_verification", () => {
    mocks.useAuth.mockReturnValue({ user: { system_role: "user" } });
    const html = renderToStaticMarkup(
      React.createElement(ClosureActionForm, {
        ticket: makeTicket({ status: "in_progress" }),
        pending: false,
        onSubmit: vi.fn(),
      }),
    );
    expect(html).toContain("提交验证");
  });
});
