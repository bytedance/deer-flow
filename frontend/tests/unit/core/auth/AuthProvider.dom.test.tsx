import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import { act, cleanup, render } from "@testing-library/react";
import type React from "react";

import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

// refreshUser's 401 handling runs through next/navigation; capture the push
// target instead of a real router.
const push = rs.fn();
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/workspace",
}));

const initialUser: User = {
  id: "u-1",
  email: "admin@example.com",
  system_role: "admin",
  needs_setup: false,
  oauth_provider: null,
};

let ctx: ReturnType<typeof useAuth> | null = null;

function Probe() {
  ctx = useAuth();
  return null;
}

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

beforeEach(() => {
  window.history.replaceState({}, "", "/workspace");
});
afterEach(() => {
  cleanup();
  push.mockReset();
  ctx = null;
});

function mount() {
  render(
    <AuthProvider initialUser={initialUser}>
      <Probe />
    </AuthProvider>,
  );
}

test("an account_disabled 401 ends the session and states the reason", async () => {
  mount();
  globalThis.fetch = rs.fn(async () =>
    jsonResponse(
      {
        detail: { code: "account_disabled", message: "Account disabled" },
      },
      401,
    ),
  ) as unknown as typeof globalThis.fetch;

  await act(async () => {
    await ctx!.refreshUser();
  });

  expect(ctx!.user).toBeNull();
  // No `next` param: a disabled account cannot sign back in.
  expect(push).toHaveBeenCalledWith("/login?error=account_disabled");
});

test("every other 401 keeps the return-to-workspace redirect", async () => {
  mount();
  globalThis.fetch = rs.fn(async () =>
    jsonResponse(
      { detail: { code: "token_expired", message: "Token expired" } },
      401,
    ),
  ) as unknown as typeof globalThis.fetch;

  await act(async () => {
    await ctx!.refreshUser();
  });

  expect(ctx!.user).toBeNull();
  expect(push).toHaveBeenCalledWith("/login?next=%2Fworkspace");
});
