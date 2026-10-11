import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/workspace/chats/a",
}));
rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));
rs.mock("@/components/workspace/gateway-offline-banner", () => ({
  GatewayOfflineBanner: () => null,
}));

import { GatewayOfflineFallback } from "@/components/workspace/gateway-offline-fallback";
import {
  ArtifactDraftsProvider,
  useArtifactDrafts,
} from "@/core/artifacts/draft-context";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

const accountA: User = {
  id: "account-a",
  email: "a@example.com",
  system_role: "admin",
  needs_setup: false,
  oauth_provider: null,
};
const accountB: User = { ...accountA, id: "account-b", email: "b@example.com" };
const filepath = "/mnt/user-data/outputs/report.txt";
const dirtyDraft = {
  filepath,
  baselineContent: "original",
  baselineSha256: "a".repeat(64),
  draftContent: "account A private edit",
  conflict: false,
};
let auth: ReturnType<typeof useAuth>;
let draftState: ReturnType<typeof useArtifactDrafts>;
let authConsumerRenders = 0;

function AuthOnlyProbe() {
  useAuth();
  authConsumerRenders++;
  return null;
}

function Probe() {
  auth = useAuth();
  draftState = useArtifactDrafts("/workspace/chats/a", auth.user?.id ?? null);
  return (
    <output>{draftState.drafts[filepath]?.draftContent ?? "no draft"}</output>
  );
}

function App({
  home = false,
  offline = false,
  user = accountA,
}: {
  home?: boolean;
  offline?: boolean;
  user?: User;
}) {
  return (
    <ArtifactDraftsProvider>
      {home ? (
        <p>Home</p>
      ) : offline ? (
        <GatewayOfflineFallback>
          <Probe />
        </GatewayOfflineFallback>
      ) : (
        <AuthProvider initialUser={user}>
          <AuthOnlyProbe />
          <Probe />
        </AuthProvider>
      )}
    </ArtifactDraftsProvider>
  );
}

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("artifact drafts with real authentication", () => {
  it("keeps the authenticated draft and unload warning during gateway-offline navigation", () => {
    const view = render(<App />);
    act(() => draftState.setDrafts({ [filepath]: dirtyDraft }));
    view.rerender(<App offline />);
    // Unknown auth must not expose the previous account's file contents.
    expect(screen.getByText("no draft")).toBeTruthy();
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    act(() => auth.applyUser(accountA));
    expect(screen.getByText("account A private edit")).toBeTruthy();
    view.rerender(<App />);
    expect(screen.getByText("account A private edit")).toBeTruthy();
  });

  it("does not rerender unrelated auth consumers on draft edits", () => {
    render(<App />);
    const initialRenders = authConsumerRenders;
    for (const draftContent of ["a", "ab", "abc"]) {
      act(() =>
        draftState.setDrafts({ [filepath]: { ...dirtyDraft, draftContent } }),
      );
      expect(screen.getByText(draftContent)).toBeTruthy();
    }
    expect(authConsumerRenders).toBe(initialRenders);
  });

  it("retains drafts after a failed auth probe and clears them on a definite 401", async () => {
    render(<App />);
    act(() => draftState.setDrafts({ [filepath]: dirtyDraft }));
    const fetch = rs
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new Error("Gateway unavailable"));
    rs.spyOn(console, "error").mockImplementation(rs.fn());
    await act(async () => auth.refreshUser());
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
    fetch.mockResolvedValue(
      new Response(JSON.stringify({ detail: "expired" }), { status: 401 }),
    );
    await act(async () => auth.refreshUser());
    const signedOut = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(signedOut);
    expect(signedOut.defaultPrevented).toBe(false);
    act(() => auth.applyUser(accountA));
    expect(screen.getByText("no draft")).toBeTruthy();
  });

  it("clears retained drafts on a confirmed anonymous verdict after an outage", () => {
    const view = render(<App />);
    act(() => draftState.setDrafts({ [filepath]: dirtyDraft }));
    view.rerender(<App offline />);
    act(() => auth.applyUser(null));
    view.rerender(<App />);
    expect(screen.getByText("no draft")).toBeTruthy();
  });

  it.each([
    ["HTTP 503", 503, "{}"],
    ["malformed success JSON", 200, "invalid JSON"],
  ])(
    "retains drafts when an offline auth probe returns %s",
    async (_name, status, body) => {
      const view = render(<App />);
      act(() => draftState.setDrafts({ [filepath]: dirtyDraft }));
      view.rerender(<App offline />);
      rs.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(body, { status }),
      );
      rs.spyOn(console, "error").mockImplementation(rs.fn());
      await act(async () => auth.refreshUser());
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
      act(() => auth.applyUser(accountA));
      expect(screen.getByText("account A private edit")).toBeTruthy();
    },
  );

  it("clears the previous account's drafts when an outage resolves as another user", () => {
    const view = render(<App />);
    act(() => draftState.setDrafts({ [filepath]: dirtyDraft }));
    view.rerender(<App offline />);
    act(() => auth.applyUser(accountB));
    expect(screen.getByText("no draft")).toBeTruthy();
    view.rerender(<App />);
    expect(screen.getByText("no draft")).toBeTruthy();
  });

  it("still clears the retained draft when logging out during an outage", async () => {
    const view = render(<App />);
    act(() => draftState.setDrafts({ [filepath]: dirtyDraft }));
    view.rerender(<App offline />);
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );
    await act(async () => auth.logout());
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    view.rerender(<App />);
    expect(screen.getByText("no draft")).toBeTruthy();
  });

  it("retains drafts when the auth layout unmounts for home and returns", () => {
    const view = render(<App />);
    act(() => draftState.setDrafts({ [filepath]: dirtyDraft }));
    view.rerender(<App home />);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    view.rerender(<App />);
    expect(screen.getByText("account A private edit")).toBeTruthy();
  });

  it("clears drafts when another account enters from home", () => {
    const view = render(<App />);
    act(() => draftState.setDrafts({ [filepath]: dirtyDraft }));
    view.rerender(<App home />);
    view.rerender(<App user={accountB} />);
    expect(screen.getByText("no draft")).toBeTruthy();
    act(() => auth.applyUser(accountA));
    expect(screen.getByText("no draft")).toBeTruthy();
  });

  it("ignores a previous owner's late save/refetch callback", () => {
    render(<App />);
    act(() => draftState.setDrafts({ [filepath]: dirtyDraft }));
    const oldSetDrafts = draftState.setDrafts;
    act(() => auth.applyUser(accountB));
    act(() => oldSetDrafts({ [filepath]: dirtyDraft }));
    expect(screen.getByText("no draft")).toBeTruthy();
    act(() => auth.applyUser(accountA));
    act(() => oldSetDrafts({ [filepath]: dirtyDraft }));
    expect(screen.getByText("no draft")).toBeTruthy();
  });

  it("clears draft content and the warning immediately on logout", async () => {
    render(<App />);
    act(() => draftState.setDrafts({ [filepath]: dirtyDraft }));
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );
    await act(async () => auth.logout());
    expect(screen.getByText("no draft")).toBeTruthy();
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    act(() => auth.applyUser(accountA));
    expect(screen.getByText("no draft")).toBeTruthy();
  });
});
