import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  return render(ui, { wrapper: QueryWrapper });
}

const patsMockState = rs.hoisted(() => ({
  pats: [] as Array<Record<string, unknown>>,
  error: null as unknown,
  createPending: false,
  createMutate: async () => ({}),
}));

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

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: { loading: "Loading", cancel: "Cancel" },
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
          neverExpires: "Never expires",
          expires: "Expires",
          created: "Created",
          lastUsed: "Last used",
          neverUsed: "Never used",
          revoke: "Revoke",
          revokeTitle: "Revoke this token?",
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

rs.mock("@/core/pats", () => ({
  PatStoreUnavailableError,
  PAT_SCOPES: [
    "threads:read",
    "threads:write",
    "threads:delete",
    "runs:create",
    "runs:read",
    "runs:cancel",
  ],
  usePats: () => ({
    pats: patsMockState.pats,
    isLoading: false,
    error: patsMockState.error,
  }),
  useCreatePat: () => ({
    isPending: patsMockState.createPending,
    mutateAsync: patsMockState.createMutate,
    reset: rs.fn(),
  }),
  useRevokePat: () => ({
    isPending: false,
    mutate: rs.fn(),
    mutateAsync: rs.fn(),
  }),
}));

afterEach(() => {
  patsMockState.pats = [];
  patsMockState.error = null;
  patsMockState.createPending = false;
  patsMockState.createMutate = async () => ({});
  cleanup();
});

describe("PatSettingsPage", () => {
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
      {
        id: "pat-1",
        name: "ci-runner",
        scopes: ["threads:read"],
        expires_at: null,
        last_used_at: null,
        created_at: "2026-08-27T10:30:00+00:00",
        revoked_at: null,
      },
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

  it("disables create until a name and at least one scope are chosen", () => {
    renderWithQueryClient(<PatSettingsPage />);

    fireEvent.click(screen.getByText("Create token"));

    const dialog = screen.getByRole("dialog");
    const submit = dialog.querySelectorAll("button").length; // sanity: dialog open
    expect(submit).toBeGreaterThan(0);

    // No name -> disabled (default scopes are preselected).
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
  });

  it("shows the show-once token after creation and resets on Done", async () => {
    patsMockState.createMutate = async () => ({
      id: "pat-9",
      name: "ci",
      scopes: ["threads:read"],
      expires_at: null,
      created_at: "2026-08-29T00:00:00+00:00",
      token: "dfp_testshowonce",
    });

    renderWithQueryClient(<PatSettingsPage />);
    fireEvent.click(screen.getByText("Create token"));
    fireEvent.change(screen.getByPlaceholderText("e.g. ci-runner"), {
      target: { value: "ci" },
    });
    const submit = screen
      .getAllByText("Create token")
      .find((element) => element.closest("[role=dialog]") !== null);
    fireEvent.click(submit!);

    expect(await screen.findByText("dfp_testshowonce")).toBeDefined();
    expect(screen.getByText("Shown only once.")).toBeDefined();
    // No close affordance in the result state either.
    expect(screen.queryByText("Close")).toBeNull();

    fireEvent.click(screen.getByText("Done"));
    expect(screen.queryByRole("dialog")).toBeNull();
    // Reopening starts from a fresh form, not the old token.
    fireEvent.click(screen.getByText("Create token"));
    expect(screen.queryByText("dfp_testshowonce")).toBeNull();
  });

  it("exposes each scope switch under an accessible name and toggles it", () => {
    renderWithQueryClient(<PatSettingsPage />);
    fireEvent.click(screen.getByText("Create token"));

    // Label-text click forwarding is browser activation behavior that
    // happy-dom does not implement, so drive the switches through their
    // aria-labels instead; turning off the three default-on scopes must
    // disable submit (the other three start off — clicking them would
    // re-enable it).
    fireEvent.change(screen.getByPlaceholderText("e.g. ci-runner"), {
      target: { value: "ci" },
    });
    for (const name of ["Read threads", "Start runs", "Read runs"]) {
      fireEvent.click(screen.getByRole("switch", { name }));
    }

    const createButton = screen
      .getAllByText("Create token")
      .find((element) => element.closest("[role=dialog]") !== null);
    expect(
      (createButton as HTMLButtonElement).closest("button")?.disabled,
    ).toBe(true);
  });
});
