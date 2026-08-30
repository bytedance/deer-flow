import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { PatSettingsPage } from "@/components/workspace/settings/pat-settings-page";

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function QueryWrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }
  return { queryClient, ...render(ui, { wrapper: QueryWrapper }) };
}

const patsMockState = rs.hoisted(() => ({
  pats: [] as Array<Record<string, unknown>>,
  error: null as unknown,
  createPending: false,
  createMutate: async (_request: unknown) => ({}),
  patsHookCalls: 0,
  createHookCalls: 0,
  revokeHookCalls: 0,
  revokePending: false,
  revokeMutate: async (_patId: string) => undefined,
}));

const staticModeMockState = rs.hoisted(() => ({ enabled: false }));

const toastMockState = rs.hoisted(() => ({
  error: rs.fn(),
  success: rs.fn(),
}));

function activePat() {
  return {
    id: "pat-1",
    name: "ci-runner",
    scopes: ["threads:read"],
    expires_at: null,
    last_used_at: null,
    created_at: "2026-08-27T10:30:00+00:00",
    revoked_at: null,
  };
}

function expectBeforeUnloadWarning() {
  const event = new Event("beforeunload", {
    cancelable: true,
  }) as BeforeUnloadEvent;
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  expect(event.returnValue).toBe(true);
}

// The page checks `error instanceof PatStoreUnavailableError` against the
// class exported from "@/core/pats" — define it once here so both the mock
// and the test feed the same class identity.
const PatStoreUnavailableError = rs.hoisted(() => {
  return class PatStoreUnavailableError extends Error {
    constructor() {
      super("pat store unavailable");
      this.name = "PatStoreUnavailableError";
    }
  };
});

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "test-user" } }),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: {
        loading: "Loading",
        cancel: "Cancel",
        notAvailableInDemoMode: "Not available in demo mode",
      },
      settings: {
        tokens: {
          title: "API Tokens",
          description: "Manage personal access tokens.",
          createButton: "Create token",
          createTitle: "Create API token",
          createDescription: "Grant only needed access.",
          nameLabel: "Name",
          namePlaceholder: "e.g. ci-runner",
          scopesLabel: "Scopes",
          scopes: {
            "threads:read": {
              name: "Read threads",
              description: "List and read.",
            },
            "threads:write": {
              name: "Write threads",
              description: "Create and update.",
            },
            "threads:delete": {
              name: "Delete threads",
              description: "Delete owned.",
            },
            "runs:create": {
              name: "Start runs",
              description: "Start agent runs.",
            },
            "runs:read": { name: "Read runs", description: "Read results." },
            "runs:cancel": { name: "Cancel runs", description: "Cancel runs." },
          },
          expiryLabel: "Expires",
          expiryDays: "{days} days",
          expiryNever: "Never expires",
          createSubmit: "Create token",
          resultTitle: "Token created",
          resultDescription: "Copy the token now.",
          copy: "Copy",
          copied: "Copied",
          copyFailed: "Copy failed",
          done: "Done",
          warning: "Shown only once.",
          emptyTitle: "No API tokens yet",
          emptyDescription: "Create one for scripts or CI.",
          revokedBadge: "Revoked",
          expiredBadge: "Expired",
          neverExpires: "Never expires",
          expires: "Expires",
          created: "Created",
          lastUsed: "Last used",
          neverUsed: "Never used",
          revoke: "Revoke",
          revokeTitle: 'Revoke "{name}"?',
          revokeDescription: "Immediate and irreversible.",
          revokeConfirm: "Revoke token",
          revoked: "Token revoked",
          unavailableTitle: "API tokens are unavailable",
          unavailableDescription: "A database backend is required.",
          loadError: "Failed to load API tokens",
        },
      },
    },
  }),
}));

rs.mock("sonner", () => ({
  toast: toastMockState,
}));

rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => staticModeMockState.enabled,
}));

rs.mock("@/core/pats", () => ({
  PatStoreUnavailableError,
  patQueryKey: (userId: string | null) => ["pats", userId ?? "anonymous"],
  PAT_SCOPES: [
    "threads:read",
    "threads:write",
    "threads:delete",
    "runs:create",
    "runs:read",
    "runs:cancel",
  ],
  usePats: () => {
    patsMockState.patsHookCalls += 1;
    return {
      pats: patsMockState.pats,
      isLoading: false,
      error: patsMockState.error,
    };
  },
  useCreatePat: () => {
    patsMockState.createHookCalls += 1;
    return {
      isPending: patsMockState.createPending,
      mutateAsync: patsMockState.createMutate,
      reset: rs.fn(),
    };
  },
  useRevokePat: () => {
    patsMockState.revokeHookCalls += 1;
    return {
      isPending: patsMockState.revokePending,
      mutateAsync: patsMockState.revokeMutate,
    };
  },
}));

afterEach(() => {
  patsMockState.pats = [];
  patsMockState.error = null;
  patsMockState.createPending = false;
  patsMockState.createMutate = async () => ({});
  patsMockState.patsHookCalls = 0;
  patsMockState.createHookCalls = 0;
  patsMockState.revokeHookCalls = 0;
  patsMockState.revokePending = false;
  patsMockState.revokeMutate = async () => undefined;
  staticModeMockState.enabled = false;
  toastMockState.error.mockReset();
  toastMockState.success.mockReset();
  cleanup();
});

describe("PatSettingsPage", () => {
  it("renders a read-only unavailable state without PAT requests in static mode", () => {
    staticModeMockState.enabled = true;

    renderWithQueryClient(<PatSettingsPage />);

    expect(screen.getByText("Not available in demo mode")).toBeDefined();
    expect(screen.queryByText("Create token")).toBeNull();
    expect(patsMockState.patsHookCalls).toBe(0);
    expect(patsMockState.createHookCalls).toBe(0);
    expect(patsMockState.revokeHookCalls).toBe(0);
  });

  it("shows the empty state when no tokens exist", () => {
    renderWithQueryClient(<PatSettingsPage />);

    expect(screen.getByText("No API tokens yet")).toBeDefined();
    expect(screen.getByText("Create token")).toBeDefined();
  });

  it("shows the database-required banner when the store is unavailable", () => {
    patsMockState.error = new PatStoreUnavailableError();

    renderWithQueryClient(<PatSettingsPage />);

    expect(screen.getByText("API tokens are unavailable")).toBeDefined();
    // No create button in this mode.
    expect(screen.queryByText("Create token")).toBeNull();
  });

  it("renders token rows with scope badges and revoked state", () => {
    patsMockState.pats = [
      activePat(),
      {
        id: "pat-2",
        name: "old-bot",
        scopes: ["runs:read"],
        expires_at: "2027-01-01T00:00:00+00:00",
        last_used_at: "2026-08-28T00:00:00+00:00",
        created_at: "2026-01-01T00:00:00+00:00",
        revoked_at: "2026-08-28T01:00:00+00:00",
      },
    ];

    renderWithQueryClient(<PatSettingsPage />);

    expect(screen.getByText("ci-runner")).toBeDefined();
    expect(screen.getByText("old-bot")).toBeDefined();
    expect(screen.getByText("Revoked")).toBeDefined();
    // Revoked tokens have no revoke button; active ones do.
    expect(screen.getAllByLabelText("Revoke")).toHaveLength(1);
  });

  it("starts with no permissions and requires an explicit scope choice", () => {
    renderWithQueryClient(<PatSettingsPage />);

    fireEvent.click(screen.getByText("Create token"));

    const dialog = screen.getByRole("dialog");
    const submit = dialog.querySelectorAll("button").length; // sanity: dialog open
    expect(submit).toBeGreaterThan(0);

    // No name and no permission grant -> disabled.
    const createButton = screen
      .getAllByText("Create token")
      .find((element) => element.closest("[role=dialog]") !== null);
    expect(createButton).toBeDefined();
    expect(
      (createButton as HTMLButtonElement).closest("button")?.disabled,
    ).toBe(true);

    const nameInput = screen.getByPlaceholderText("e.g. ci-runner");
    fireEvent.change(nameInput, { target: { value: "ci" } });
    expect(
      (createButton as HTMLButtonElement).closest("button")?.disabled,
    ).toBe(true);

    for (const scope of [
      "Read threads",
      "Write threads",
      "Delete threads",
      "Start runs",
      "Read runs",
      "Cancel runs",
    ]) {
      expect(
        screen
          .getByRole("switch", { name: scope })
          .getAttribute("aria-checked"),
      ).toBe("false");
    }

    fireEvent.click(screen.getByText("Read threads"));
    expect(
      (createButton as HTMLButtonElement).closest("button")?.disabled,
    ).toBe(false);
  });

  it("hides dismissal affordances while the create request is pending", () => {
    patsMockState.createPending = true;

    renderWithQueryClient(<PatSettingsPage />);
    fireEvent.click(screen.getByText("Create token"));

    // The response carries the only copy of the token, so the built-in
    // close button must be gone while the request is in flight.
    expect(screen.queryByText("Close")).toBeNull();
    // Escape routes through the same guarded onOpenChange and must not
    // close the dialog either.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeDefined();

    expectBeforeUnloadWarning();
  });

  it("shows the show-once token after creation and resets on Done", async () => {
    const createMutate = rs.fn(async (_request: unknown) => ({
      id: "pat-9",
      name: "ci",
      scopes: ["threads:read"],
      expires_at: null,
      created_at: "2026-08-29T00:00:00+00:00",
      token: "dfp_testshowonce",
    }));
    patsMockState.createMutate = createMutate;

    renderWithQueryClient(<PatSettingsPage />);
    fireEvent.click(screen.getByText("Create token"));
    fireEvent.change(screen.getByPlaceholderText("e.g. ci-runner"), {
      target: { value: "ci" },
    });
    fireEvent.click(screen.getByText("Read threads"));
    const submit = screen
      .getAllByText("Create token")
      .find((element) => element.closest("[role=dialog]") !== null);
    fireEvent.click(submit!);

    expect(await screen.findByText("dfp_testshowonce")).toBeDefined();
    expect(createMutate).toHaveBeenCalledWith({
      name: "ci",
      scopes: ["threads:read"],
      expires_in_days: 90,
    });
    expect(screen.getByText("Shown only once.")).toBeDefined();
    // No close affordance in the result state either.
    expect(screen.queryByText("Close")).toBeNull();

    expectBeforeUnloadWarning();

    fireEvent.click(screen.getByText("Done"));
    expect(screen.queryByRole("dialog")).toBeNull();
    // Reopening starts from a fresh form, not the old token.
    fireEvent.click(screen.getByText("Create token"));
    expect(screen.queryByText("dfp_testshowonce")).toBeNull();
  });

  it("exposes each scope switch under an accessible name without double toggling", () => {
    renderWithQueryClient(<PatSettingsPage />);
    fireEvent.click(screen.getByText("Create token"));

    // The label toggles explicitly (Safari never implemented label->button
    // forwarding), so text clicks work everywhere without firing twice.
    fireEvent.change(screen.getByPlaceholderText("e.g. ci-runner"), {
      target: { value: "ci" },
    });
    fireEvent.click(screen.getByText("Read threads"));

    const createButton = screen
      .getAllByText("Create token")
      .find((element) => element.closest("[role=dialog]") !== null);
    expect(
      (createButton as HTMLButtonElement).closest("button")?.disabled,
    ).toBe(false);

    fireEvent.click(screen.getByText("Read threads"));
    expect(
      (createButton as HTMLButtonElement).closest("button")?.disabled,
    ).toBe(true);
  });

  it("names the token and keeps the confirmation open until revoke succeeds", async () => {
    patsMockState.pats = [activePat()];
    let finishRevoke!: () => void;
    const revokeMutate = rs.fn(
      () =>
        new Promise<undefined>((resolve) => {
          finishRevoke = () => resolve(undefined);
        }),
    );
    patsMockState.revokeMutate = revokeMutate;

    renderWithQueryClient(<PatSettingsPage />);
    fireEvent.click(screen.getByLabelText("Revoke"));

    expect(screen.getByText('Revoke "ci-runner"?')).toBeDefined();
    fireEvent.click(screen.getByText("Revoke token"));
    expect(revokeMutate).toHaveBeenCalledWith("pat-1");
    expect(screen.getByRole("dialog")).toBeDefined();

    finishRevoke();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(toastMockState.success).toHaveBeenCalledWith("Token revoked");
  });

  it("does not dismiss a revoke confirmation while the request is pending", () => {
    patsMockState.pats = [activePat()];
    const view = renderWithQueryClient(<PatSettingsPage />);
    fireEvent.click(screen.getByLabelText("Revoke"));

    patsMockState.revokePending = true;
    view.rerender(<PatSettingsPage />);
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("closes and refreshes after revoke discovers an unavailable store", async () => {
    patsMockState.pats = [activePat()];
    patsMockState.revokeMutate = async () => {
      throw new PatStoreUnavailableError();
    };
    const view = renderWithQueryClient(<PatSettingsPage />);
    const invalidateQueries = rs.spyOn(view.queryClient, "invalidateQueries");

    fireEvent.click(screen.getByLabelText("Revoke"));
    fireEvent.click(screen.getByText("Revoke token"));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(toastMockState.error).toHaveBeenCalledWith(
      "API tokens are unavailable",
    );
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["pats", "test-user"],
    });
  });

  it("keeps the confirmation open and shows ordinary revoke errors", async () => {
    patsMockState.pats = [activePat()];
    patsMockState.revokeMutate = async () => {
      throw new Error("Token not found");
    };

    renderWithQueryClient(<PatSettingsPage />);
    fireEvent.click(screen.getByLabelText("Revoke"));
    fireEvent.click(screen.getByText("Revoke token"));

    await waitFor(() => {
      expect(toastMockState.error).toHaveBeenCalledWith("Token not found");
    });
    expect(screen.getByRole("dialog")).toBeDefined();
  });
  it("flags expired tokens and keeps create available on a transient list error", () => {
    patsMockState.pats = [
      {
        id: "pat-1",
        name: "old-ci",
        scopes: ["threads:read"],
        expires_at: "2020-01-01T00:00:00+00:00",
        last_used_at: null,
        created_at: "2019-01-01T00:00:00+00:00",
        revoked_at: null,
      },
    ];
    renderWithQueryClient(<PatSettingsPage />);

    // Expired (but not revoked) tokens carry the Expired badge.
    expect(screen.getByText("Expired")).toBeDefined();
    expect(screen.queryByText("Revoked")).toBeNull();

    // A non-503 list error shows the error line but keeps the create
    // affordance — only the memory-backend 503 removes it.
    patsMockState.pats = [];
    patsMockState.error = new Error("boom");
    cleanup();
    renderWithQueryClient(<PatSettingsPage />);
    expect(screen.getByText("boom")).toBeDefined();
    expect(screen.getByText("Create token")).toBeDefined();
    cleanup();
  });
});
