import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  usePathname: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    ...props
  }: React.PropsWithChildren<Record<string, unknown>>) =>
    React.createElement("a", props, children),
}));

vi.mock("next/navigation", () => ({
  usePathname: mocks.usePathname,
}));

vi.mock("@/core/auth/AuthProvider", () => ({
  useAuth: mocks.useAuth,
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      admin: {
        dashboard: "Dashboard",
        tenants: "Tenants",
        usage: "Usage",
        logs: "Logs",
        currentTenant: "Current Tenant",
        globalScope: "All Tenants",
        tenantScope: "Current Tenant",
      },
      settings: {
        account: {
          signOut: "Sign Out",
        },
      },
    },
  }),
}));

import { AdminSidebar } from "@/components/admin/admin-sidebar";

describe("AdminSidebar", () => {
  test("renders the logged-in account information", () => {
    mocks.usePathname.mockReturnValue("/admin");
    mocks.useAuth.mockReturnValue({
      user: {
        email: "yanghai@shenguyun.com",
        system_role: "admin",
        tenant_id: "acme",
      },
      logout: vi.fn(),
    });

    const html = renderToStaticMarkup(React.createElement(AdminSidebar));

    expect(html).toContain("yanghai@shenguyun.com");
    expect(html).toContain(">admin<");
    expect(html).toContain("Current Tenant: acme");
    expect(html).toContain(">Current Tenant<");
    expect(html).toContain("Sign Out");
  });
});
