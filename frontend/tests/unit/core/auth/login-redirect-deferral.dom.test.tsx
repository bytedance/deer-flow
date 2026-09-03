import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AuthProvider, useAuth, useDeferLoginRedirect } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

const routerMock = rs.hoisted(() => ({ push: rs.fn() }));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerMock.push, replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
}));

rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => false,
}));

let meStatus = 200;

const user = {
  id: "user-a",
  email: "a@example.com",
  system_role: "user",
  session_generation: 1756700000,
} as unknown as User;

function Probe({ defer }: { defer: boolean }) {
  const { refreshUser } = useAuth();
  useDeferLoginRedirect(defer);
  return <button onClick={() => void refreshUser()}>refresh</button>;
}

function renderProbe(defer: boolean) {
  return render(
    <AuthProvider initialUser={user}>
      <Probe defer={defer} />
    </AuthProvider>,
  );
}

beforeEach(() => {
  meStatus = 200;
  routerMock.push.mockReset();
  rs.stubGlobal(
    "fetch",
    rs.fn(async () => new Response(null, { status: meStatus })),
  );
});

afterEach(() => {
  rs.unstubAllGlobals();
  cleanup();
});

describe("login redirect deferral", () => {
  it("redirects to login immediately when no deferral is active", async () => {
    meStatus = 401;
    renderProbe(false);

    await act(async () => {
      fireEvent.click(document.querySelector("button")!);
    });

    await waitFor(() => {
      expect(routerMock.push).toHaveBeenCalledWith("/login?next=%2Fworkspace");
    });
  });

  it("holds the 401 redirect while a deferral is active, then fires it", async () => {
    meStatus = 401;
    const { rerender } = renderProbe(true);

    await act(async () => {
      fireEvent.click(document.querySelector("button")!);
    });
    // The deferring flow (the show-once dialog) stays mounted — the
    // redirect has not fired and none is scheduled outside the effect.
    expect(routerMock.push).not.toHaveBeenCalled();

    rerender(
      <AuthProvider initialUser={user}>
        <Probe defer={false} />
      </AuthProvider>,
    );
    await waitFor(() => {
      expect(routerMock.push).toHaveBeenCalledWith("/login?next=%2Fworkspace");
    });
  });

  it("counts deferrals: two active deferrers do not cancel each other", async () => {
    meStatus = 401;
    function TwoProbes({ first, second }: { first: boolean; second: boolean }) {
      return (
        <AuthProvider initialUser={user}>
          <Probe defer={first} />
          <Probe defer={second} />
        </AuthProvider>
      );
    }
    const { rerender } = render(<TwoProbes first second />);

    await act(async () => {
      fireEvent.click(document.querySelector("button")!);
    });
    expect(routerMock.push).not.toHaveBeenCalled();

    rerender(<TwoProbes first={false} second />);
    await act(async () => {
      fireEvent.click(document.querySelectorAll("button")[0]!);
    });
    expect(routerMock.push).not.toHaveBeenCalled();

    rerender(<TwoProbes first={false} second={false} />);
    await waitFor(() => {
      expect(routerMock.push).toHaveBeenCalledWith("/login?next=%2Fworkspace");
    });
  });

  it("arms imperatively without waiting for a render or effect", async () => {
    // The render-driven channel registers one commit late; a 401 that lands
    // inside the synchronous submission window must still observe the
    // deferral. arm() registers it in the same breath and hands back its
    // release; the held redirect fires only after release().
    meStatus = 401;
    let arm!: () => () => void;
    function ArmProbe({ expose }: { expose: (arm: () => () => void) => void }) {
      const { refreshUser } = useAuth();
      const armFn = useDeferLoginRedirect(false);
      return (
        <>
          <button onClick={() => expose(armFn)}>expose</button>
          <button onClick={() => void refreshUser()}>refresh</button>
        </>
      );
    }
    render(
      <AuthProvider initialUser={user}>
        <ArmProbe expose={(fn) => (arm = fn)} />
      </AuthProvider>,
    );

    let release!: () => void;
    await act(async () => {
      fireEvent.click(screen.getAllByRole("button")[0]!);
      // arm() sets provider state: keep it inside the act boundary so the
      // deferral count is flushed before the refresh click below.
      release = arm();
    });

    await act(async () => {
      fireEvent.click(screen.getAllByRole("button")[1]!);
    });
    expect(routerMock.push).not.toHaveBeenCalled();

    await act(async () => {
      release();
    });
    await waitFor(() => {
      expect(routerMock.push).toHaveBeenCalledWith("/login?next=%2Fworkspace");
    });
  });
});
