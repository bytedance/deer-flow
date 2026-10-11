import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { UserSettingsPage } from "@/components/workspace/settings/user-settings-page";
import { GatewayApiError } from "@/core/api/errors";
import type * as AdminUsers from "@/core/auth/admin-users";
import {
  loadAdminUsers,
  updateUserAccount,
  type AdminUser,
} from "@/core/auth/admin-users";
import { useAuth } from "@/core/auth/AuthProvider";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: rs.fn() }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/auth/admin-users", () => ({
  ...(rs.requireActual<typeof AdminUsers>("@/core/auth/admin-users") as object),
  loadAdminUsers: rs.fn(),
  updateUserAccount: rs.fn(),
}));

const admin: AdminUser = {
  id: "u-admin",
  email: "admin@example.com",
  system_role: "admin",
  needs_setup: false,
  disabled: false,
  oauth_provider: null,
};
const suspended: AdminUser = {
  id: "u-user",
  email: "user@example.com",
  system_role: "user",
  needs_setup: false,
  disabled: true,
  oauth_provider: null,
};
// Pre-gap-3 backends omit `disabled` entirely — absent means not disabled.
const legacyRow: AdminUser = {
  id: "u-legacy",
  email: "legacy@example.com",
  system_role: "user",
  needs_setup: false,
  oauth_provider: null,
};

const auth = (role: "admin" | "user") =>
  ({ user: { id: "u-admin", system_role: role } }) as ReturnType<
    typeof useAuth
  >;

function rowFor(email: string) {
  const row = screen.getByText(email).closest("li");
  expect(row).not.toBeNull();
  return row as HTMLElement;
}

beforeEach(() => {
  rs.mocked(useAuth).mockReturnValue(auth("admin"));
  rs.mocked(loadAdminUsers).mockResolvedValue([admin, suspended, legacyRow]);
});
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <UserSettingsPage />
    </QueryClientProvider>,
  );
  return client;
}

test("non-admin sees the admin-only note and loads nothing", () => {
  rs.mocked(useAuth).mockReturnValue(auth("user"));
  mount();
  expect(screen.getByText(enUS.settings.users.adminOnly)).toBeTruthy();
  expect(loadAdminUsers).not.toHaveBeenCalled();
});

test("lists email, read-only role, and disabled state per account", async () => {
  mount();
  await screen.findByText("admin@example.com");

  const activeRow = rowFor("admin@example.com");
  expect(
    within(activeRow).getByText(`Role: admin · ${enUS.settings.users.active}`),
  ).toBeTruthy();
  const disabledRow = rowFor("user@example.com");
  expect(
    within(disabledRow).getByText(
      `Role: user · ${enUS.settings.users.disabled}`,
    ),
  ).toBeTruthy();
  const legacy = rowFor("legacy@example.com");
  expect(
    within(legacy).getByText(`Role: user · ${enUS.settings.users.active}`),
  ).toBeTruthy();
});

test("disable toggle PATCHes only the disabled field and refreshes", async () => {
  mount();
  rs.mocked(updateUserAccount).mockResolvedValue({ ...admin, disabled: true });
  await screen.findByText("admin@example.com");

  fireEvent.click(
    within(rowFor("admin@example.com")).getByRole("button", {
      name: enUS.settings.users.disable,
    }),
  );

  await waitFor(() =>
    expect(updateUserAccount).toHaveBeenCalledWith("u-admin", {
      disabled: true,
    }),
  );
  // The invalidation refires the active list query, so the row's status
  // flips without a manual reload.
  await waitFor(() => expect(loadAdminUsers).toHaveBeenCalledTimes(2));
});

test("enable toggle targets the suspended account", async () => {
  mount();
  rs.mocked(updateUserAccount).mockResolvedValue({
    ...suspended,
    disabled: false,
  });
  await screen.findByText("user@example.com");

  fireEvent.click(
    within(rowFor("user@example.com")).getByRole("button", {
      name: enUS.settings.users.enable,
    }),
  );

  await waitFor(() =>
    expect(updateUserAccount).toHaveBeenCalledWith("u-user", {
      disabled: false,
    }),
  );
});

test("a 409 rejection surfaces the gateway detail verbatim", async () => {
  mount();
  rs.mocked(updateUserAccount).mockRejectedValueOnce(
    new GatewayApiError({
      message: "cannot disable the last remaining active admin",
      status: 409,
      code: null,
      params: {},
      rawMessage: "",
    }),
  );
  await screen.findByText("admin@example.com");

  fireEvent.click(
    within(rowFor("admin@example.com")).getByRole("button", {
      name: enUS.settings.users.disable,
    }),
  );

  expect(
    await screen.findByText("cannot disable the last remaining active admin"),
  ).toBeTruthy();
});

test("a non-gateway failure falls back to the localized copy", async () => {
  mount();
  rs.mocked(updateUserAccount).mockRejectedValueOnce(new Error("boom"));
  await screen.findByText("admin@example.com");

  fireEvent.click(
    within(rowFor("admin@example.com")).getByRole("button", {
      name: enUS.settings.users.disable,
    }),
  );

  expect(
    await screen.findByText(enUS.settings.users.updateFailed),
  ).toBeTruthy();
  expect(screen.queryByText("boom")).toBeNull();
});

test("a failed load shows one alert with the localized copy", async () => {
  // mockRejectedValueOnce outranks the beforeEach default for the mount query.
  rs.mocked(loadAdminUsers).mockRejectedValueOnce(new Error("gateway down"));
  mount();

  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByText(enUS.settings.users.failed)).toBeTruthy();
  expect(screen.queryByText("gateway down")).toBeNull();
});
