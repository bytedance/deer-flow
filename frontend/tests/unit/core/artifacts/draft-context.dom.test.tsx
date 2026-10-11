import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/workspace/chats/a",
}));
rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

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

function Probe() {
  auth = useAuth();
  draftState = useArtifactDrafts("/workspace/chats/a", auth.user?.id ?? null);
  return (
    <output>{draftState.drafts[filepath]?.draftContent ?? "no draft"}</output>
  );
}

function App({
  home = false,
  user = accountA,
}: {
  home?: boolean;
  user?: User;
}) {
  return (
    <ArtifactDraftsProvider>
      {home ? (
        <p>Home</p>
      ) : (
        <AuthProvider initialUser={user}>
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
