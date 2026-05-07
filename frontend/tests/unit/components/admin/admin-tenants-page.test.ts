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
  createTenant: vi.fn(),
  deleteTenant: vi.fn(),
  deleteTenantUser: vi.fn(),
  listTenantUsers: vi.fn(),
  listTenants: vi.fn(),
  updateTenant: vi.fn(),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      admin: {
        tenants: "Tenants",
        error: "Error",
        createTenant: "Create Tenant",
        tenantIdPlaceholder: "Tenant ID",
        displayNamePlaceholder: "Display name",
        create: "Create",
        tenantManagementRestricted: "Tenant scoped management only",
      },
    },
  }),
}));

import AdminTenantsPage from "@/app/admin/tenants/page";

describe("AdminTenantsPage", () => {
  test("hides the create-tenant controls for tenant-scoped admins", () => {
    mocks.useAuth.mockReturnValue({
      user: {
        system_role: "admin",
        tenant_id: "acme",
      },
    });

    const html = renderToStaticMarkup(React.createElement(AdminTenantsPage));

    expect(html).toContain("scope-banner");
    expect(html).toContain("Tenant scoped management only");
    expect(html).not.toContain("Create Tenant");
    expect(html).not.toContain("Tenant ID");
  });

  test("shows the create-tenant controls for the default system admin", () => {
    mocks.useAuth.mockReturnValue({
      user: {
        system_role: "admin",
        tenant_id: "default",
      },
    });

    const html = renderToStaticMarkup(React.createElement(AdminTenantsPage));

    expect(html).toContain("Create Tenant");
    expect(html).toContain("Tenant ID");
    expect(html).not.toContain("Tenant scoped management only");
  });
});
