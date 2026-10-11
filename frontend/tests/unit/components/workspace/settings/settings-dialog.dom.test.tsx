import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";

import {
  SettingsDialog,
  type SettingsSection,
} from "@/components/workspace/settings/settings-dialog";
import type * as AdminUsers from "@/core/auth/admin-users";
import { loadAdminUsers, type AdminUser } from "@/core/auth/admin-users";
import { useAuth } from "@/core/auth/AuthProvider";
import { enUS } from "@/core/i18n/locales/en-US";
import { isStaticWebsiteOnly } from "@/core/static-mode";

rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: rs.fn() }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/auth/admin-users", () => ({
  ...(rs.requireActual<typeof AdminUsers>("@/core/auth/admin-users") as object),
  loadAdminUsers: rs.fn(),
}));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: rs.fn() }));

const admin: AdminUser = {
  id: "u-admin",
  email: "admin@example.com",
  system_role: "admin",
  needs_setup: false,
  disabled: false,
  oauth_provider: null,
};

const auth = (role: "admin" | "user") =>
  ({ user: { id: "u-admin", system_role: role } }) as ReturnType<
    typeof useAuth
  >;

beforeEach(() => {
  rs.mocked(useAuth).mockReturnValue(auth("admin"));
  rs.mocked(isStaticWebsiteOnly).mockReturnValue(false);
  rs.mocked(loadAdminUsers).mockResolvedValue([admin]);
});
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

// The deep-link bridge calls `openSettingsDialog(section)`, so
// `defaultSection` is the section a `?settings=<section>` URL lands on.
function mountDialog(section?: SettingsSection) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <SettingsDialog open defaultSection={section} />
    </QueryClientProvider>,
  );
}

test("a non-admin `?settings=users` deep link falls back to the first section", async () => {
  rs.mocked(useAuth).mockReturnValue(auth("user"));
  mountDialog("users");
  expect(screen.queryByRole("button", { name: "Users" })).toBeNull();
  await screen.findByText(enUS.settings.models.adminOnly);
  expect(screen.queryByText(enUS.settings.users.adminOnly)).toBeNull();
});

test("an admin `?settings=users` deep link lands on user management", async () => {
  mountDialog("users");
  expect(screen.getByRole("button", { name: "Users" })).toBeTruthy();
  await screen.findByText("admin@example.com");
  expect(screen.queryByText(enUS.settings.models.adminOnly)).toBeNull();
});

test("a static-website admin deep link keeps the Users entry but loads nothing", async () => {
  // The nav splice keys on the role only, so the demo's nominal admin still
  // sees the Users entry; the page-level mode gate is what stops the query.
  rs.mocked(isStaticWebsiteOnly).mockReturnValue(true);
  mountDialog("users");
  expect(screen.getByRole("button", { name: "Users" })).toBeTruthy();
  await screen.findByText(enUS.settings.users.adminOnly);
  expect(loadAdminUsers).not.toHaveBeenCalled();
});
