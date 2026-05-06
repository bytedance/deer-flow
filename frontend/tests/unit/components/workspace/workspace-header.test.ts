import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useTenant: vi.fn(),
  useSidebar: vi.fn(),
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

vi.mock("@/components/ui/sidebar", () => ({
  SidebarMenu: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  SidebarMenuItem: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  SidebarMenuButton: ({ children }: React.PropsWithChildren) =>
    React.createElement("div", null, children),
  SidebarTrigger: () => React.createElement("button", null, "toggle"),
  useSidebar: mocks.useSidebar,
}));

vi.mock("@/core/auth/AuthProvider", () => ({
  useAuth: mocks.useAuth,
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      sidebar: {
        newChat: "New chat",
      },
    },
  }),
}));

vi.mock("@/core/tenant", () => ({
  useTenant: mocks.useTenant,
}));

vi.mock("@/env", () => ({
  env: {
    NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false",
  },
}));

import { WorkspaceHeader } from "@/components/workspace/workspace-header";

describe("WorkspaceHeader", () => {
  test("does not render tenant id badge for non-default tenants", () => {
    mocks.useSidebar.mockReturnValue({ state: "expanded" });
    mocks.usePathname.mockReturnValue("/workspace/chats/new");
    mocks.useTenant.mockReturnValue(["test", vi.fn()]);
    mocks.useAuth.mockReturnValue({
      user: {
        email: "yanghai@shenguyun.com",
        system_role: "user",
      },
    });

    const html = renderToStaticMarkup(React.createElement(WorkspaceHeader));

    expect(html).toContain("yanghai@shenguyun.com");
    expect(html).not.toContain(">test<");
  });

  test("still renders the admin badge for admin users", () => {
    mocks.useSidebar.mockReturnValue({ state: "expanded" });
    mocks.usePathname.mockReturnValue("/workspace/chats/new");
    mocks.useTenant.mockReturnValue(["default", vi.fn()]);
    mocks.useAuth.mockReturnValue({
      user: {
        email: "admin@example.com",
        system_role: "admin",
      },
    });

    const html = renderToStaticMarkup(React.createElement(WorkspaceHeader));

    expect(html).toContain(">admin<");
  });
});
