import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";

import { ThreadContext } from "@/components/workspace/messages/context";
import {
  SidecarProvider,
  useSidecar,
} from "@/components/workspace/sidecar/context";
import { SidecarPanel } from "@/components/workspace/sidecar/sidecar-panel";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

// AuthProvider and the panel both reach into next/navigation. Keep it inert
// under happy-dom (banner-test pattern).
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));

// The panel's model list is irrelevant to the delete-button gating; keep the
// react-query machinery out of the way entirely.
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [],
    tokenUsageEnabled: false,
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: rs.fn(),
  }),
}));

function makeUser(permissions: string[] | null | undefined): User {
  return {
    id: "user-1",
    email: "user@example.test",
    system_role: "user",
    needs_setup: false,
    oauth_provider: null,
    ...(permissions === undefined ? {} : { permissions }),
  } as User;
}

/** Sets the provider's sidecarThreadId so the panel switches out of its
 * empty state — the delete button only renders for a live sidecar thread. */
function SidecarThreadProbe() {
  const sidecar = useSidecar();
  useEffect(() => {
    sidecar.setSidecarThreadId("sidecar-thread-1");
  }, [sidecar]);
  return null;
}

/** Replaces the authenticated user in place via the auth context. */
function FlipUserProbe({ to }: { to: User }) {
  const { applyUser } = useAuth();
  useEffect(() => {
    applyUser(to);
  }, [applyUser, to]);
  return null;
}

function buildTree(
  initialUser: User,
  {
    withFlip = false,
    flipTo = makeUser(["threads:read"]),
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    }),
  } = {},
): ReactNode {
  return (
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider initialUser={initialUser}>
          {withFlip && <FlipUserProbe to={flipTo} />}
          <ThreadContext.Provider
            value={{ thread: { messages: [] } as never, isMock: true }}
          >
            <SidecarProvider
              parentThreadId="parent-1"
              isMock
              context={{ thread_id: "parent-1" } as never}
            >
              <SidecarThreadProbe />
              <SidecarPanel />
            </SidecarProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}

afterEach(() => {
  rs.restoreAllMocks();
  cleanup();
});

describe("SidecarPanel delete-button permission gating", () => {
  it("renders the delete button for a role holding threads:delete", async () => {
    render(buildTree(makeUser(["threads:read", "threads:delete"])));
    expect(await screen.findByTestId("sidecar-delete-button")).not.toBeNull();
  });

  it("keeps the delete button for an unresolved permission list (pre-Phase-4 backend)", async () => {
    render(buildTree(makeUser(undefined)));
    expect(await screen.findByTestId("sidecar-delete-button")).not.toBeNull();
  });

  it("hides the delete button once the resolved list denies threads:delete", async () => {
    // Anchor on presence first, then flip only the permission list in place —
    // the disappearance is then provably caused by the gating, not by the
    // sidecar thread never mounting. The shared queryClient keeps the rerender
    // a true in-place update rather than a provider remount.
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const { rerender } = render(
      buildTree(makeUser(["threads:delete"]), { queryClient }),
    );
    expect(await screen.findByTestId("sidecar-delete-button")).not.toBeNull();

    rerender(
      buildTree(makeUser(["threads:delete"]), {
        withFlip: true,
        flipTo: makeUser(["threads:read"]),
        queryClient,
      }),
    );

    await waitFor(() => {
      expect(screen.queryByTestId("sidecar-delete-button")).toBeNull();
    });
  });
});
