import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

const mockState = rs.hoisted(() => ({
  user: {
    id: "00000000-0000-0000-0000-000000000001",
    email: "admin@example.com",
    system_role: "admin" as "admin" | "user",
    needs_setup: false,
    oauth_provider: null as string | null,
  },
  staticMode: false,
  refreshUser: rs.fn<() => Promise<void>>(),
  toastSuccess: rs.fn(),
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: mockState.user,
    refreshUser: mockState.refreshUser,
  }),
}));

rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => mockState.staticMode,
}));

rs.mock("sonner", () => ({
  toast: { success: mockState.toastSuccess },
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: { loading: "Loading...", cancel: "Cancel" },
      settings: {
        users: {
          title: "User management",
          description: "Manage user roles.",
          adminRequired: "A signed-in administrator account is required.",
          searchPlaceholder: "Search users by email",
          empty: "No users found.",
          noResults: "No users match your search.",
          loadFailed: "Failed to load users.",
          retry: "Try again",
          currentUser: "You",
          localAccount: "Local account",
          ssoAccount: (provider: string) => `SSO · ${provider}`,
          roles: { admin: "Admin", user: "User" },
          actions: {
            promote: "Promote",
            demote: "Demote",
            changing: "Changing...",
            promoteUser: (email: string) => `Promote ${email} to admin`,
            demoteUser: (email: string) => `Demote ${email} to user`,
          },
          confirm: {
            title: "Change user role?",
            promote: (email: string) => `Promote ${email}?`,
            demote: (email: string) => `Demote ${email}?`,
            sessionWarning: "Active sessions will be invalidated.",
          },
          blocked: {
            lastAdmin: "The last administrator cannot be demoted.",
          },
          success: {
            promoted: (email: string) => `${email} promoted.`,
            demoted: (email: string) => `${email} demoted.`,
          },
          errors: {
            forbidden: "Permission denied.",
            lastAdmin: "The last administrator cannot be demoted.",
            notFound: "User not found.",
            conflict: "Role conflict.",
            network: "Network error.",
            unknown: "Role change failed.",
          },
        },
      },
    },
  }),
}));

import { UsersSettingsPage } from "@/components/workspace/settings/users-settings-page";

const adminUser = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "admin@example.com",
  system_role: "admin" as const,
  created_at: "2026-07-31T06:30:00Z",
  needs_setup: false,
  oauth_provider: null,
};

const secondAdmin = {
  id: "00000000-0000-0000-0000-000000000002",
  email: "second-admin@example.com",
  system_role: "admin" as const,
  created_at: "2026-07-31T06:31:00Z",
  needs_setup: false,
  oauth_provider: "oidc",
};

const regularUser = {
  id: "00000000-0000-0000-0000-000000000003",
  email: "user@example.com",
  system_role: "user" as const,
  created_at: "2026-07-31T06:32:00Z",
  needs_setup: false,
  oauth_provider: null,
};

const oidcUser = {
  id: "00000000-0000-0000-0000-000000000004",
  email: "oidc-user@example.com",
  system_role: "user" as const,
  created_at: "2026-07-31T06:33:00Z",
  needs_setup: false,
  oauth_provider: "oidc",
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <UsersSettingsPage />
    </QueryClientProvider>,
  );
}

function installUsersFetch(
  users: Array<
    typeof adminUser | typeof secondAdmin | typeof regularUser | typeof oidcUser
  >,
  patchResponse?: object,
) {
  return rs.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    if ((init?.method ?? "GET") === "PATCH") {
      return Promise.resolve(
        new Response(JSON.stringify(patchResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url === "/api/v1/admin/users") {
      return Promise.resolve(
        new Response(JSON.stringify({ users, total: users.length }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    throw new Error(`Unexpected request: ${url}`);
  });
}

beforeEach(() => {
  mockState.user = { ...adminUser };
  mockState.staticMode = false;
  mockState.refreshUser.mockReset().mockResolvedValue(undefined);
  mockState.toastSuccess.mockReset();
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("UsersSettingsPage", () => {
  test("does not request users for a non-admin or static-site admin", async () => {
    const fetchSpy = rs.spyOn(globalThis, "fetch");
    mockState.user = { ...adminUser, system_role: "user" };
    renderPage();

    expect(
      screen.getByText("A signed-in administrator account is required."),
    ).toBeTruthy();
    await Promise.resolve();
    expect(fetchSpy).not.toHaveBeenCalled();

    cleanup();
    mockState.user = { ...adminUser, id: "default" };
    mockState.staticMode = false;
    renderPage();
    expect(
      screen.getByText("A signed-in administrator account is required."),
    ).toBeTruthy();
    await Promise.resolve();
    expect(fetchSpy).not.toHaveBeenCalled();

    cleanup();
    mockState.user = { ...adminUser };
    mockState.staticMode = true;
    renderPage();
    expect(
      screen.getByText("A signed-in administrator account is required."),
    ).toBeTruthy();
    await Promise.resolve();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("renders account source, role, current user, and pre-disables the last admin demotion", async () => {
    installUsersFetch([adminUser, regularUser, oidcUser]);
    renderPage();

    await screen.findByText("admin@example.com");
    expect(screen.getAllByText("Local account")).toHaveLength(2);
    expect(screen.getByText("SSO · oidc")).toBeTruthy();
    expect(screen.getByText("You")).toBeTruthy();
    expect(screen.getByText("Admin")).toBeTruthy();
    expect(screen.getAllByText("User")).toHaveLength(2);
    expect(
      within(
        screen.getByTestId(`admin-user-row-${adminUser.id}`),
      ).getByRole<HTMLButtonElement>("button", {
        name: "Demote admin@example.com to user",
      }).disabled,
    ).toBe(true);
  });

  test("promotes a user only after confirmation", async () => {
    const fetchSpy = installUsersFetch([adminUser, regularUser], {
      user: { ...regularUser, system_role: "admin" },
      previous_role: "user",
      sessions_invalidated: true,
    });
    renderPage();

    const row = await screen.findByTestId(`admin-user-row-${regularUser.id}`);
    fireEvent.click(
      within(row).getByRole("button", {
        name: "Promote user@example.com to admin",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Change user role?" });
    expect(within(dialog).getByText("Promote user@example.com?")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Promote" }));

    await waitFor(() => {
      const patchCall = fetchSpy.mock.calls.find(
        ([, init]) => init?.method === "PATCH",
      );
      expect(patchCall?.[0]).toBe(`/api/v1/admin/users/${regularUser.id}/role`);
      expect(patchCall?.[1]?.body).toBe(
        JSON.stringify({ system_role: "admin" }),
      );
    });
    expect(mockState.toastSuccess).toHaveBeenCalledWith(
      "user@example.com promoted.",
    );
    expect(mockState.refreshUser).not.toHaveBeenCalled();
  });

  test("allows self-demotion when another admin exists and refreshes the current session", async () => {
    installUsersFetch([adminUser, secondAdmin], {
      user: { ...adminUser, system_role: "user" },
      previous_role: "admin",
      sessions_invalidated: true,
    });
    renderPage();

    const row = await screen.findByTestId(`admin-user-row-${adminUser.id}`);
    const demote = within(row).getByRole<HTMLButtonElement>("button", {
      name: "Demote admin@example.com to user",
    });
    expect(demote.disabled).toBe(false);
    fireEvent.click(demote);
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Demote",
      }),
    );

    await waitFor(() => {
      expect(mockState.refreshUser).toHaveBeenCalledTimes(1);
    });
    expect(mockState.toastSuccess).toHaveBeenCalledWith(
      "admin@example.com demoted.",
    );
  });

  test("keeps the confirmation open when the server rejects a last-admin race", async () => {
    rs.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      if (init?.method === "PATCH") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail: {
                code: "last_admin",
                message: "The final administrator cannot be demoted.",
              },
            }),
            {
              status: 409,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      if (url === "/api/v1/admin/users") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              users: [adminUser, secondAdmin],
              total: 2,
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    renderPage();

    const row = await screen.findByTestId(`admin-user-row-${secondAdmin.id}`);
    fireEvent.click(
      within(row).getByRole("button", {
        name: "Demote second-admin@example.com to user",
      }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Demote",
      }),
    );

    await within(dialog).findByRole("alert");
    expect(
      within(dialog).getByText("The last administrator cannot be demoted."),
    ).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(mockState.refreshUser).not.toHaveBeenCalled();
  });

  test("refreshes the actor when a role change loses administrator permission", async () => {
    rs.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "PATCH") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail: {
                code: "admin_required",
                message: "Administrator privileges changed.",
              },
            }),
            {
              status: 403,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({ users: [adminUser, secondAdmin], total: 2 }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
    });
    renderPage();

    const row = await screen.findByTestId(`admin-user-row-${secondAdmin.id}`);
    fireEvent.click(
      within(row).getByRole("button", {
        name: "Demote second-admin@example.com to user",
      }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Demote",
      }),
    );

    await waitFor(() => {
      expect(mockState.refreshUser).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByText("Permission denied.")).toBeTruthy();
  });

  test("shows a network error only for a fetch failure", async () => {
    rs.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "PATCH") {
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({ users: [adminUser, regularUser], total: 2 }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
    });
    renderPage();

    const row = await screen.findByTestId(`admin-user-row-${regularUser.id}`);
    fireEvent.click(
      within(row).getByRole("button", {
        name: "Promote user@example.com to admin",
      }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Promote",
      }),
    );

    expect(await screen.findByText("Network error.")).toBeTruthy();
  });

  test("shows an unknown error for a malformed role-change response", async () => {
    rs.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "PATCH") {
        return Promise.resolve(
          new Response(JSON.stringify({ unexpected: true }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({ users: [adminUser, regularUser], total: 2 }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
    });
    renderPage();

    const row = await screen.findByTestId(`admin-user-row-${regularUser.id}`);
    fireEvent.click(
      within(row).getByRole("button", {
        name: "Promote user@example.com to admin",
      }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Promote",
      }),
    );

    expect(await screen.findByText("Role change failed.")).toBeTruthy();
  });
});
