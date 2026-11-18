import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { GatewayOfflineBanner } from "@/components/workspace/gateway-offline-banner";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

// AuthProvider pulls useRouter/usePathname from next/navigation. Hand it a
// no-op router so logout()'s `router.push("/")` stays inert under happy-dom
// instead of trying to drive a real Next.js router.
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
}));

// Force the SPA (non-static) branch of AuthProvider.logout — that is the
// branch that actually performs the POST that issue #3001 is about. The
// static branch would short-circuit into a `router.push("/")` and never
// touch the network, masking the very regression we need to lock down.
rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => false,
}));

// Keep the banner's i18n lookup hermetic — real translations are not
// relevant here, we just need a stable accessible name for the button.
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      workspace: {
        logout: "Log out",
        gatewayUnavailable: "Gateway unavailable.",
        gatewayUnavailableRetrying: "Retrying…",
      },
    },
    changeLocale: rs.fn(),
  }),
}));

afterEach(() => {
  rs.restoreAllMocks();
  cleanup();
});

/**
 * Install a fetch double that keeps the gateway "unavailable" for the
 * banner's `/auth/me` probe (so the banner stays mounted and the recovery
 * button stays actionable) while recording every call so the logout
 * request can be inspected. Returns the captured calls for assertions.
 */
function installFetch(): Array<{ url: string; method: string }> {
  const calls: Array<{ url: string; method: string }> = [];
  rs.spyOn(globalThis, "fetch").mockImplementation(
    (input: RequestInfo | URL, init?: RequestInit) => {
      // `input` may be a Request object whose default stringification would
      // yield "[object Request]" — normalise to the URL string either way.
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      const method = (init?.method ?? "GET").toUpperCase();
      calls.push({ url, method });
      if (url.includes("/auth/logout")) {
        return Promise.resolve(
          new Response(JSON.stringify({ message: "Successfully logged out" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      // `/auth/me` probe — return a transient failure so `classifyProbe`
      // yields "transient" and the banner keeps showing the logout button.
      return Promise.resolve(
        new Response("service unavailable", { status: 503 }),
      );
    },
  );
  return calls;
}

function renderBanner() {
  return render(
    <AuthProvider initialUser={null}>
      <GatewayOfflineBanner gatewayUnavailable />
    </AuthProvider>,
  );
}

describe("GatewayOfflineBanner logout recovery (#3001)", () => {
  it("renders a <button> (not a GET-style link) as the logout affordance", async () => {
    installFetch();
    renderBanner();

    // The recovery control must be a <button>, not an <a>/<Link> whose
    // browser navigation would turn into a GET against the POST-only
    // /auth/logout endpoint — the exact 405 reported in #3001.
    const logout = await screen.findByRole("button", { name: /log out/i });
    expect(logout.tagName).toBe("BUTTON");
    expect(logout.hasAttribute("href")).toBe(false);
  });

  it("issues a POST (never a GET) to /api/v1/auth/logout when clicked", async () => {
    const calls = installFetch();
    renderBanner();

    fireEvent.click(await screen.findByRole("button", { name: /log out/i }));

    const logoutCall = await waitFor(() => {
      const logoutCalls = calls.filter((c) => c.url.includes("/auth/logout"));
      expect(logoutCalls).toHaveLength(1);
      const call = logoutCalls[0];
      if (!call) {
        throw new Error("expected exactly one /auth/logout call");
      }
      return call;
    });

    expect(logoutCall.url).toBe("/api/v1/auth/logout");
    expect(logoutCall.method).toBe("POST");
    // Lock down the regression documented in #3001: a GET against this
    // POST-only endpoint returns 405 and fails to clear the session.
    expect(logoutCall.method).not.toBe("GET");
  });
});

it.each(["switch account", "logout", "unmount"] as const)(
  "ignores a probe body that finishes after %s",
  async (action) => {
    const userA: User = {
      id: "account-a",
      email: "a@example.com",
      system_role: "user",
      needs_setup: false,
    };
    const userB = { ...userA, id: "account-b" };
    let auth!: ReturnType<typeof useAuth>;
    let resolve!: (user: User) => void;
    const body = new Promise<User>((done) => (resolve = done));
    const response = Response.json(userA);
    const json = rs.fn(() => body);
    response.json = json;
    rs.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      input === "/api/v1/auth/logout"
        ? new Response(null, { status: 204 })
        : response,
    );
    function AuthProbe() {
      auth = useAuth();
      return <output>{auth.user?.id ?? "no user"}</output>;
    }
    function Recovery({ showBanner = true }: { showBanner?: boolean }) {
      return (
        <AuthProvider initialUser={null} initialAuthUnknown>
          <AuthProbe />
          {showBanner && <GatewayOfflineBanner gatewayUnavailable />}
        </AuthProvider>
      );
    }
    const view = render(<Recovery />);
    await waitFor(() => expect(json).toHaveBeenCalledOnce());
    await act(async () => {
      if (action === "switch account") auth.applyUser(userB);
      else if (action === "logout") await auth.logout();
      else view.rerender(<Recovery showBanner={false} />);
    });
    await act(async () => resolve(userA));

    expect(auth.user).toEqual(action === "switch account" ? userB : null);
    expect(screen.queryByText(userA.id)).toBeNull();
  },
);

it("applies the active recovery probe without a second auth request", async () => {
  const user: User = {
    id: "recovered-account",
    email: "recovered@example.com",
    system_role: "user",
    needs_setup: false,
  };
  const fetch = rs
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(Response.json(user));
  function AuthProbe() {
    return <output>{useAuth().user?.id}</output>;
  }
  render(
    <AuthProvider initialUser={null} initialAuthUnknown>
      <AuthProbe />
      <GatewayOfflineBanner gatewayUnavailable />
    </AuthProvider>,
  );

  expect(await screen.findByText(user.id)).toBeTruthy();
  expect(fetch).toHaveBeenCalledOnce();
});
