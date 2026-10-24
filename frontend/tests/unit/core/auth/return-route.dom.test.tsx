import { afterEach, expect, it, rs } from "@rstest/core";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { AuthProvider, useRequireAuth } from "@/core/auth/AuthProvider";
import { buildLoginUrl } from "@/core/auth/types";

const push = rs.hoisted(() => rs.fn());
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => window.location.pathname,
}));
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
  push.mockReset();
});
it("retains workspace, resource query and anchor through native session refresh and login guards", async () => {
  const target =
    "/workspace/chats/private?workspace_id=22222222-2222-2222-2222-222222222222&tab=files#source";
  window.history.replaceState(null, "", target);
  rs.stubGlobal("fetch", async () =>
    Response.json({ detail: "expired" }, { status: 401 }),
  );
  const view = renderHook(useRequireAuth, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <AuthProvider
        initialUser={{
          id: "alice",
          email: "alice@example.test",
          system_role: "user",
          needs_setup: false,
        }}
      >
        {children}
      </AuthProvider>
    ),
  });
  await act(async () => {
    await view.result.current.refreshUser();
  });
  await waitFor(() => expect(push).toHaveBeenCalled());
  expect(view.result.current.user).toBeNull();
  expect(
    push.mock.calls.every(([href]) => href === buildLoginUrl(target)),
  ).toBe(true);
});
