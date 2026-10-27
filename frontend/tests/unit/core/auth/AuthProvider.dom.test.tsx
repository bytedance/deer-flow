import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import { act, cleanup, render, renderHook } from "@testing-library/react";
import type React from "react";

import {
  AuthProvider,
  useAuth,
  useRequireAuth,
} from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

// refreshUser's 401 handling runs through next/navigation; capture the push
// target instead of a real router.
const push = rs.fn();
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => window.location.pathname,
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

test("a 401 returns to the page it happened on, query string included", async () => {
  window.history.replaceState({}, "", "/workspace/scheduled-tasks?task_id=t-1");
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

  expect(push).toHaveBeenCalledWith(
    "/login?next=%2Fworkspace%2Fscheduled-tasks%3Ftask_id%3Dt-1",
  );
});

test("useRequireAuth returns to the page it guards, query string included", () => {
  window.history.replaceState({}, "", "/workspace/scheduled-tasks?task_id=t-1");

  renderHook(() => useRequireAuth(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <AuthProvider initialUser={null}>{children}</AuthProvider>
    ),
  });

  expect(push).toHaveBeenCalledWith(
    "/login?next=%2Fworkspace%2Fscheduled-tasks%3Ftask_id%3Dt-1",
  );
});

test.each(["applyUser", "logout"] as const)(
  "%s supersedes an older successful auth refresh",
  async (action) => {
    mount();
    let resolve!: (response: Response) => void;
    const pending = new Promise<Response>((done) => (resolve = done));
    globalThis.fetch = rs.fn((input) =>
      input === "/api/v1/auth/me"
        ? pending
        : Promise.resolve(new Response(null, { status: 204 })),
    ) as typeof globalThis.fetch;
    let completion!: Promise<void>;
    act(() => {
      completion = ctx!.refreshUser();
    });
    const nextUser = { ...initialUser, id: "u-2" };
    await act(async () => {
      if (action === "logout") await ctx!.logout();
      else ctx!.applyUser(nextUser);
    });
    await act(async () => {
      resolve(jsonResponse(initialUser));
      await completion;
    });

    expect(ctx!.user).toEqual(action === "logout" ? null : nextUser);
    expect(ctx!.isLoading).toBe(false);
  },
);

test("a stale disabled-session response cannot clear a newer account or redirect it", async () => {
  mount();
  let resolve!: (response: Response) => void;
  globalThis.fetch = rs.fn(
    () => new Promise<Response>((done) => (resolve = done)),
  );
  let completion!: Promise<void>;
  act(() => {
    completion = ctx!.refreshUser();
  });
  const nextUser = { ...initialUser, id: "u-2" };
  act(() => ctx!.applyUser(nextUser));
  await act(async () => {
    resolve(jsonResponse({ detail: { code: "account_disabled" } }, 401));
    await completion;
  });

  expect(ctx!.user).toEqual(nextUser);
  expect(push).not.toHaveBeenCalled();
});

test("a response whose body completes after an account switch cannot restore the old account", async () => {
  mount();
  let resolve!: (user: User) => void;
  const body = new Promise<User>((done) => (resolve = done));
  const response = jsonResponse(initialUser);
  response.json = () => body;
  globalThis.fetch = rs.fn(async () => response);
  let completion!: Promise<void>;
  await act(async () => {
    completion = ctx!.refreshUser();
  });
  const nextUser = { ...initialUser, id: "u-2" };
  act(() => ctx!.applyUser(nextUser));
  await act(async () => {
    resolve(initialUser);
    await completion;
  });

  expect(ctx!.user).toEqual(nextUser);
});
