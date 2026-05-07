import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

vi.mock("@/core/auth/AuthProvider", () => ({
  useAuth: mocks.useAuth,
}));

vi.mock("@/components/admin/admin-scope-banner", () => ({
  AdminScopeBanner: () => React.createElement("div", null, "scope-banner"),
}));

vi.mock("@/core/admin/api", () => ({
  getAdminLogs: vi.fn(),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      admin: {
        auditLogs: "Audit Logs",
        error: "Error",
        tenant: "Tenant",
        direction: "Direction",
        all: "All",
        input_dir: "Input",
        output_dir: "Output",
        startDate: "Start Date",
        endDate: "End Date",
        filter: "Filter",
        records: "Records",
        totalRecords: "Total Records",
        timestamp: "Timestamp",
        model: "Model",
        blocked: "Blocked",
        noLogRecords: "No log records",
      },
    },
  }),
}));

import AdminLogsPage from "@/app/admin/logs/page";

describe("AdminLogsPage", () => {
  test("hides the tenant filter for tenant-scoped admins", () => {
    mocks.useAuth.mockReturnValue({
      user: {
        system_role: "admin",
        tenant_id: "acme",
      },
    });

    const html = renderToStaticMarkup(React.createElement(AdminLogsPage));

    expect(html).toContain("scope-banner");
    expect(html).not.toContain('placeholder="tenant"');
  });

  test("keeps the tenant filter for the default system admin", () => {
    mocks.useAuth.mockReturnValue({
      user: {
        system_role: "admin",
        tenant_id: "default",
      },
    });

    const html = renderToStaticMarkup(React.createElement(AdminLogsPage));

    expect(html).toContain('placeholder="tenant"');
  });
});
