import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";

import AuthCallbackPage from "@/app/(auth)/auth/callback/page";
import { AUTH_REQUEST_TIMEOUT_MS } from "@/core/auth/constants";

const navigation = rs.hoisted(() => ({
  replace: rs.fn(),
  next: "/workspace",
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => ({
    get: (key: string) => (key === "next" ? navigation.next : null),
  }),
}));

beforeEach(() => {
  rs.useFakeTimers();
  navigation.replace.mockReset();
  navigation.next = "/workspace";
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  rs.useRealTimers();
});

describe("AuthCallbackPage lifecycle", () => {
  it("bounds a hung auth check and redirects through the failure path", async () => {
    let signal: AbortSignal | null = null;
    let rejectRequest: ((reason: unknown) => void) | null = null;
    rs.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      signal = init?.signal ?? null;
      return new Promise<Response>((_resolve, reject) => {
        rejectRequest = reject;
      });
    });
    render(<AuthCallbackPage />);

    act(() => {
      rs.advanceTimersByTime(AUTH_REQUEST_TIMEOUT_MS);
    });
    expect((signal as AbortSignal | null)?.aborted).toBe(true);
    (rejectRequest as ((reason: unknown) => void) | null)?.(
      new DOMException("Aborted", "AbortError"),
    );
    await rs.advanceTimersByTimeAsync(1500);
    expect(navigation.replace).toHaveBeenCalledOnce();
    expect(navigation.replace).toHaveBeenCalledWith("/login?error=sso_failed");
  });

  it("aborts the auth request when the callback page unmounts", () => {
    let signal: AbortSignal | null = null;
    rs.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      signal = init?.signal ?? null;
      return new Promise<Response>(() => undefined);
    });

    const view = render(<AuthCallbackPage />);
    expect((signal as AbortSignal | null)?.aborted).toBe(false);

    view.unmount();
    expect((signal as AbortSignal | null)?.aborted).toBe(true);
  });

  it("cancels a pending success redirect when the page unmounts", async () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null));
    const view = render(<AuthCallbackPage />);

    await rs.advanceTimersByTimeAsync(0);
    act(() => undefined);
    expect(screen.getByText("Redirecting...")).toBeTruthy();
    view.unmount();

    act(() => {
      rs.advanceTimersByTime(300);
    });
    expect(navigation.replace).not.toHaveBeenCalled();
  });
});
