import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/showcase/demo",
}));
rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));
rs.mock("@/core/i18n/server", () => ({
  detectLocaleServer: async () => "en",
}));
// Keep the actual layout and AuthProvider; unrelated UI wrappers are inert.
rs.mock("@/core/i18n/context", () => ({
  I18nProvider: ({ children }: { children: ReactNode }) => children,
}));
rs.mock("@/components/query-client-provider", () => ({
  QueryClientProvider: ({ children }: { children: ReactNode }) => children,
}));
rs.mock("@/components/ui/sidebar", () => ({
  SidebarProvider: ({ children }: { children: ReactNode }) => children,
  SidebarInset: ({ children }: { children: ReactNode }) => children,
}));
rs.mock("@/components/workspace/chats/chat-providers", () => ({
  ChatProviders: ({ children }: { children: ReactNode }) => children,
}));
rs.mock("sonner", () => ({ Toaster: () => null }));

import PublicShowcaseLayout from "@/app/showcase/[thread_id]/layout";
import {
  ArtifactDraftsProvider,
  useArtifactDrafts,
} from "@/core/artifacts/draft-context";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

const user: User = {
  id: "account-a",
  email: "a@example.com",
  system_role: "admin",
  needs_setup: false,
  oauth_provider: null,
};
const filepath = "/mnt/user-data/outputs/report.txt";
let auth: ReturnType<typeof useAuth>;
let draftState: ReturnType<typeof useArtifactDrafts>;

function Probe() {
  auth = useAuth();
  draftState = useArtifactDrafts("/workspace/chats/a", auth.user?.id ?? null);
  return (
    <output>{draftState.drafts[filepath]?.draftContent ?? "no draft"}</output>
  );
}

function Workspace() {
  return (
    <AuthProvider initialUser={user}>
      <Probe />
    </AuthProvider>
  );
}

function App({ children }: { children: ReactNode }) {
  return <ArtifactDraftsProvider>{children}</ArtifactDraftsProvider>;
}

function createDraft() {
  act(() =>
    draftState.setDrafts({
      [filepath]: {
        filepath,
        baselineContent: "original",
        baselineSha256: "a".repeat(64),
        draftContent: "private workspace edit",
        conflict: false,
      },
    }),
  );
}

function unloadIsPrevented() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("showcase layout draft ownership", () => {
  it("retains hidden workspace drafts and the unload warning through home and showcase", async () => {
    const showcase = await PublicShowcaseLayout({ children: <Probe /> });
    const view = render(
      <App>
        <Workspace />
      </App>,
    );
    createDraft();
    view.rerender(
      <App>
        <p>Home</p>
      </App>,
    );
    expect(unloadIsPrevented()).toBe(true);
    view.rerender(<App>{showcase}</App>);
    expect(screen.getByText("no draft")).toBeTruthy();
    expect(unloadIsPrevented()).toBe(true);
    view.rerender(
      <App>
        <Workspace />
      </App>,
    );
    expect(screen.getByText("private workspace edit")).toBeTruthy();
    expect(unloadIsPrevented()).toBe(true);
  });

  it.each(["anonymous verdict", "logout"])(
    "still clears retained drafts on a confirmed %s from showcase",
    async (verdict) => {
      const showcase = await PublicShowcaseLayout({ children: <Probe /> });
      const view = render(
        <App>
          <Workspace />
        </App>,
      );
      createDraft();
      view.rerender(<App>{showcase}</App>);
      expect(unloadIsPrevented()).toBe(true);
      if (verdict === "logout") {
        rs.spyOn(globalThis, "fetch").mockResolvedValue(
          new Response(null, { status: 204 }),
        );
        await act(async () => auth.logout());
      } else {
        act(() => auth.applyUser(null));
      }
      expect(unloadIsPrevented()).toBe(false);
      view.rerender(
        <App>
          <Workspace />
        </App>,
      );
      expect(screen.getByText("no draft")).toBeTruthy();
    },
  );
});
