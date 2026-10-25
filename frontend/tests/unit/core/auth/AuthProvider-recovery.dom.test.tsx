import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";
import { useContext } from "react";

import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import { AuthQueryScopeContext } from "@/core/auth/query-scope";
import type { User } from "@/core/auth/types";
import { isStaticWebsiteOnly } from "@/core/static-mode";

const push = rs.fn();
const router = { push };
rs.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/workspace/chats/example",
}));
rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: rs.fn(() => false),
}));

const user: User = {
  id: "account-a",
  email: "a@example.com",
  system_role: "user",
  needs_setup: false,
  oauth_provider: null,
};
let auth: ReturnType<typeof useAuth>;
let owner: string | null | undefined;

function Probe() {
  auth = useAuth();
  owner = useContext(AuthQueryScopeContext);
  return <output>{auth.user?.email ?? "No confirmed user"}</output>;
}

function mount(initialUser: User | null = user, initialAuthUnknown = false) {
  return render(
    <AuthProvider
      initialUser={initialUser}
      initialAuthUnknown={initialAuthUnknown}
    >
      <Probe />
    </AuthProvider>,
  );
}

function userResponse(next: User = user) {
  return new Response(JSON.stringify(next), {
    headers: { "Content-Type": "application/json" },
  });
}

async function wake(event: "online" | "visibilitychange") {
  await act(async () => {
    if (event === "online") window.dispatchEvent(new Event(event));
    else document.dispatchEvent(new Event(event));
  });
}

beforeEach(() => {
  rs.mocked(isStaticWebsiteOnly).mockReturnValue(false);
  rs.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  rs.spyOn(Date, "now").mockReturnValue(100_000);
  rs.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  push.mockReset();
});

test.each(["online", "visibilitychange"] as const)(
  "%s recovers unknown auth after a failed visible-tab refresh",
  async (event) => {
    const fetch = rs
      .spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(userResponse());
    mount();

    await wake("visibilitychange");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(auth.user).toBeNull();
    expect(owner).toBeUndefined();
    expect(push).not.toHaveBeenCalled();

    // Reconnect must not wait for the failed visibility check's throttle.
    rs.mocked(Date.now).mockReturnValue(event === "online" ? 100_001 : 160_001);
    await wake(event);

    expect(screen.getByText("a@example.com")).toBeTruthy();
    expect(owner).toBe("account-a");
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(push).not.toHaveBeenCalled();
  },
);

test("reconnect events do not overlap an in-flight unknown-auth check", async () => {
  let resolve!: (response: Response) => void;
  const fetch = rs
    .spyOn(globalThis, "fetch")
    .mockImplementation(
      () => new Promise<Response>((done) => (resolve = done)),
    );
  mount(null, true);

  await act(async () => {
    window.dispatchEvent(new Event("online"));
    window.dispatchEvent(new Event("online"));
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(auth.user).toBeNull();
  expect(owner).toBeUndefined();

  await act(async () => resolve(userResponse()));
  expect(screen.getByText("a@example.com")).toBeTruthy();
  expect(owner).toBe("account-a");
});

test("unknown-auth recovery retains the visible-tab throttle", async () => {
  const fetch = rs
    .spyOn(globalThis, "fetch")
    .mockRejectedValue(new TypeError("Failed to fetch"));
  mount();
  await wake("visibilitychange");
  rs.mocked(Date.now).mockReturnValue(100_001);
  await wake("visibilitychange");
  expect(fetch).toHaveBeenCalledTimes(1);
});

test.each([false, true])(
  "confirmed anonymous sessions do not restart checks (explicit logout: %s)",
  async (logout) => {
    const fetch = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));
    mount(logout ? user : null);
    if (logout) await act(async () => auth.logout());
    fetch.mockClear();
    await wake("online");
    await wake("visibilitychange");
    expect(fetch).not.toHaveBeenCalled();
    expect(owner).toBeNull();
  },
);

test("a recovered 401 remains a confirmed logout", async () => {
  const fetch = rs
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(
      new Response(JSON.stringify({ detail: "expired" }), { status: 401 }),
    );
  mount(null, true);
  await wake("online");
  expect(owner).toBeNull();
  expect(push).toHaveBeenCalledTimes(1);
  expect(push).toHaveBeenCalledWith(expect.stringContaining("/login?next="));
  await wake("online");
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("hidden tabs wait until visible before recovering unknown auth", async () => {
  const fetch = rs.spyOn(globalThis, "fetch").mockResolvedValue(userResponse());
  const visibility = rs.spyOn(document, "visibilityState", "get");
  visibility.mockReturnValue("hidden");
  mount(null, true);
  await wake("online");
  await wake("visibilitychange");
  expect(fetch).not.toHaveBeenCalled();
  visibility.mockReturnValue("visible");
  await wake("visibilitychange");
  expect(screen.getByText("a@example.com")).toBeTruthy();
});

test("static demos do not probe even when auth starts unknown", async () => {
  rs.mocked(isStaticWebsiteOnly).mockReturnValue(true);
  const fetch = rs.spyOn(globalThis, "fetch");
  mount(null, true);
  await wake("online");
  await wake("visibilitychange");
  expect(fetch).not.toHaveBeenCalled();
});

test("unmount removes automatic auth wakeups", async () => {
  const fetch = rs.spyOn(globalThis, "fetch");
  const view = mount(null, true);
  view.unmount();
  await wake("online");
  await wake("visibilitychange");
  expect(fetch).not.toHaveBeenCalled();
});
