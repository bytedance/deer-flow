/* @vitest-environment jsdom */

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth, type User } from "@/core/auth/AuthProvider";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  pathname: "/workspace",
  setCurrentTenantId: vi.fn(),
  clearQueryClient: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/core/tenant/store", () => ({
  setCurrentTenantId: mocks.setCurrentTenantId,
}));

vi.mock("@/components/query-client-provider", () => ({
  queryClient: {
    clear: mocks.clearQueryClient,
  },
}));

const INITIAL_USER: User = {
  id: "user-1",
  email: "alice@example.com",
  system_role: "user",
  tenant_id: "tenant-a",
  user_name: "alice",
  real_name: "Alice",
};

function AuthProbe() {
  const { user } = useAuth();
  const label = user?.real_name || user?.user_name || user?.email || "none";
  return React.createElement("div", null, label);
}

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", {
    value: state,
    writable: true,
    configurable: true,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

async function flushEffects() {
  await Promise.resolve();
  await Promise.resolve();
}

describe("AuthProvider visibility refresh", () => {
  let container: HTMLDivElement;
  let root: Root;
  let originalVisibilityState: DocumentVisibilityState;

  beforeEach(() => {
    mocks.push.mockReset();
    mocks.setCurrentTenantId.mockReset();
    mocks.clearQueryClient.mockReset();
    originalVisibilityState = document.visibilityState;
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      writable: true,
      configurable: true,
    });
    document.cookie = "";
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    container.remove();
    Object.defineProperty(document, "visibilityState", {
      value: originalVisibilityState,
      writable: true,
      configurable: true,
    });
    vi.unstubAllGlobals();
  });

  it("keeps the current user when the visibility refresh hits a network error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValueOnce(new Error("temporary network error")),
    );

    await React.act(async () => {
      root.render(
        React.createElement(
          AuthProvider,
          {
            initialUser: INITIAL_USER,
            children: React.createElement(AuthProbe),
          },
        ),
      );
      await flushEffects();
    });

    expect(container.textContent).toBe("Alice");

    await React.act(async () => {
      setVisibility("hidden");
      await flushEffects();
    });

    await React.act(async () => {
      setVisibility("visible");
      await flushEffects();
    });

    expect(container.textContent).toBe("Alice");
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("clears the user and redirects when the session is truly unauthorized", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({}),
      } as Response),
    );

    await React.act(async () => {
      root.render(
        React.createElement(
          AuthProvider,
          {
            initialUser: INITIAL_USER,
            children: React.createElement(AuthProbe),
          },
        ),
      );
      await flushEffects();
    });

    expect(container.textContent).toBe("Alice");

    await React.act(async () => {
      setVisibility("hidden");
      await flushEffects();
    });

    await React.act(async () => {
      setVisibility("visible");
      await flushEffects();
    });

    expect(container.textContent).toBe("none");
    expect(mocks.push).toHaveBeenCalledWith("/login?next=%2Fworkspace");
  });
});
