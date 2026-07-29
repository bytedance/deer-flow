import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { GatewayOfflineBanner } from "@/components/workspace/gateway-offline-banner";
import { AuthProvider } from "@/core/auth/AuthProvider";

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
