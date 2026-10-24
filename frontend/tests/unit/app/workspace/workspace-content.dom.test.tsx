import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { useQueryClient } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useSyncExternalStore, type ReactNode } from "react";

import { WorkspaceContent } from "@/app/workspace/workspace-content";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  useWorkspaceContext,
  useWorkspaceLifetime,
} from "@/core/workspaces/context";

const fixture = rs.hoisted(() => ({
  capability: { enabled: true, available: true } as {
    enabled: boolean;
    available: boolean;
  } | null,
  privateRenders: [] as string[],
  clients: [] as unknown[],
  views: [] as { url: string; workspace: string }[],
  controls: null as ReturnType<typeof useWorkspaceContext>,
  refresh: rs.fn(),
  url: "/workspace/chats/new",
  listeners: new Set<() => void>(),
  replace: rs.fn((href: string) => {
    fixture.url = href;
    for (const listener of fixture.listeners) listener();
  }),
}));
rs.mock("next/headers", () => ({
  cookies: async () => ({ get: () => undefined }),
}));
rs.mock("next/navigation", () => ({
  useRouter: () => ({
    push: rs.fn(),
    replace: fixture.replace,
    refresh: fixture.refresh,
  }),
  usePathname: () =>
    new URL(
      useSyncExternalStore(
        (fn) => {
          fixture.listeners.add(fn);
          return () => {
            fixture.listeners.delete(fn);
          };
        },
        () => fixture.url,
      ),
      "http://localhost",
    ).pathname,
  useSearchParams: () =>
    new URL(
      useSyncExternalStore(
        (fn) => {
          fixture.listeners.add(fn);
          return () => {
            fixture.listeners.delete(fn);
          };
        },
        () => fixture.url,
      ),
      "http://localhost",
    ).searchParams,
}));
rs.mock("@/core/workspaces/server", () => ({
  getServerSideWorkspaceCapability: async () => fixture.capability,
}));
// Keep the actual server content, workspace/session/cache and native sidebar/header.
// Leaf features are mounting probes, not substitutes for backend acceptance.
function PrivateLeaf({ name }: { name: string }) {
  const lifetime = useWorkspaceLifetime();
  const client = useQueryClient();
  fixture.controls = useWorkspaceContext();
  fixture.privateRenders.push(
    name + ":" + (lifetime?.scope.workspaceId ?? "legacy"),
  );
  fixture.clients.push(client);
  fixture.views.push({
    url: fixture.url,
    workspace: lifetime?.scope.workspaceId ?? "legacy",
  });
  return (
    <span data-testid={name}>{lifetime?.scope.workspaceId ?? "legacy"}</span>
  );
}
rs.mock("@/core/settings/user-preferences-boundary", () => ({
  UserPreferencesBoundary: ({ children }: { children: ReactNode }) => children,
}));
rs.mock("@/core/extensions/hooks", () => ({
  ExtensionPageBootstrap: () => <PrivateLeaf name="extension" />,
}));
rs.mock("@/core/threads/activity", () => ({
  useThreadActivity: () => {
    fixture.privateRenders.push("activity");
  },
}));
rs.mock("@/components/workspace/channels/workspace-channels-list", () => ({
  WorkspaceChannelsList: () => <PrivateLeaf name="channels" />,
}));
rs.mock("@/components/workspace/plugin-navigation", () => ({
  PluginNavigation: () => <PrivateLeaf name="plugins" />,
}));
rs.mock("@/components/workspace/projects-section", () => ({
  ProjectsSection: () => <PrivateLeaf name="projects" />,
}));
rs.mock("@/components/workspace/recent-chat-list", () => ({
  RecentChatList: () => <PrivateLeaf name="recent" />,
}));
rs.mock("@/components/workspace/thread-delete-dialog", () => ({
  ThreadDeleteDialogProvider: ({ children }: { children: ReactNode }) =>
    children,
}));
rs.mock("@/components/workspace/workspace-nav-chat-list", () => ({
  WorkspaceNavChatList: () => <PrivateLeaf name="nav" />,
}));
rs.mock("@/components/workspace/workspace-nav-menu", () => ({
  WorkspaceNavMenu: () => <PrivateLeaf name="footer" />,
}));
rs.mock("@/components/workspace/command-palette", () => ({
  CommandPalette: () => <PrivateLeaf name="commands" />,
}));
rs.mock("@/components/workspace/settings", () => ({
  SettingsDialogHost: () => <PrivateLeaf name="settings" />,
}));
rs.mock("@/components/workspace/workspace-settings-deep-link", () => ({
  WorkspaceSettingsDeepLink: () => <PrivateLeaf name="settings-link" />,
}));
rs.mock("@/components/workspace/gateway-offline-banner", () => ({
  GatewayOfflineBanner: () => null,
}));
rs.mock("@/components/workspace/model-load-error-banner", () => ({
  ModelLoadErrorBanner: () => null,
}));
rs.mock("sonner", () => ({ Toaster: () => null }));

const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
const alice = {
  id: "alice",
  email: "alice@example.test",
  system_role: "user" as const,
  needs_setup: false,
};
async function mount() {
  const content = await WorkspaceContent({
    children: <PrivateLeaf name="page" />,
  });
  return render(
    <AuthProvider initialUser={alice}>
      <I18nContext.Provider
        value={{ locale: "en-US", t: enUS, setLocale: () => undefined }}
      >
        {content}
      </I18nContext.Provider>
    </AuthProvider>,
  );
}
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
  fixture.privateRenders.length = 0;
  fixture.clients.length = 0;
  fixture.views.length = 0;
  fixture.controls = null;
  fixture.capability = { enabled: true, available: true };
  fixture.url = "/workspace/chats/new";
  fixture.replace.mockClear();
});

describe("native workspace content bootstrap", () => {
  it("keeps controls mounted, confirms scope before private features and shares one fresh cache across sidebar and page", async () => {
    fixture.url = `/workspace/chats/old-team-chat?workspace_id=${T}`;
    let release!: () => void;
    let started = false;
    let metadataReads = 0;
    let held = true;
    rs.stubGlobal(
      "fetch",
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url,
          "http://localhost",
        ).pathname;
        const workspace = new Headers(init?.headers).get(
          "X-Deerflow-Workspace",
        );
        if (path === "/api/v1/auth/me") return Response.json(alice);
        if (path === "/api/workspaces")
          return Response.json([
            {
              id: P,
              name: "Personal",
              kind: "personal",
              status: "active",
              personal_user_id: "alice",
              role: "owner",
              membership_version: 1,
              policy_version: 1,
            },
            {
              id: T,
              name: "Team",
              kind: "team",
              status: "active",
              personal_user_id: null,
              role: "member",
              membership_version: 1,
              policy_version: 1,
            },
          ]);
        if (path === "/api/workspaces/current") {
          metadataReads += 1;
          if (held) {
            started = true;
            await new Promise<void>((resolve, reject) => {
              release = resolve;
              init?.signal?.addEventListener(
                "abort",
                () => reject(new Error("Metadata read aborted")),
                { once: true },
              );
            });
          }
          return Response.json({
            workspace_id: workspace,
            actor_user_id: "alice",
            membership_version: 1,
            policy_version: 1,
          });
        }
        throw new Error("Unexpected root fixture request: " + path);
      },
    );
    await mount();
    expect(fixture.privateRenders).toEqual([]);
    expect(
      screen.getByRole("button", {
        name: "Switch workspace: Switching workspace…",
      }),
    ).toBeTruthy();
    await waitFor(() => expect(started).toBe(true));
    await act(async () => {
      held = false;
      release();
    });
    await waitFor(() => expect(screen.getByTestId("page").textContent).toBe(T));
    expect(screen.getByTestId("recent").textContent).toBe(T);
    expect(
      screen
        .getByRole("link", { name: enUS.sidebar.newChat })
        .getAttribute("href"),
    ).toBe(`/workspace/chats/new?workspace_id=${T}`);
    expect(fixture.privateRenders).toContain("activity");
    expect(new Set(fixture.clients).size).toBe(1);
    const original = fixture.clients[0];
    fixture.clients.length = 0;
    fixture.privateRenders.length = 0;
    held = true;
    started = false;
    let selection!: Promise<boolean>;
    act(() => {
      selection = fixture.controls!.select(P);
    });
    expect(fixture.replace).toHaveBeenCalledWith(
      `/workspace/chats/new?workspace_id=${P}`,
    );
    expect(screen.queryByTestId("page")).toBeNull();
    expect(screen.queryByTestId("recent")).toBeNull();
    expect(fixture.privateRenders).toEqual([]);
    expect(
      screen.getByRole("button", {
        name: "Switch workspace: Switching workspace…",
      }),
    ).toBeTruthy();
    await waitFor(() => expect(started).toBe(true));
    await act(async () => {
      held = false;
      release();
      await selection;
    });
    await waitFor(() => expect(screen.getByTestId("page").textContent).toBe(P));
    expect(screen.getByTestId("recent").textContent).toBe(P);
    expect(new Set(fixture.clients).size).toBe(1);
    expect(fixture.clients[0]).not.toBe(original);
    const personalCache = fixture.clients[0];
    const reads = metadataReads;
    act(() => {
      fixture.replace(`/workspace/chats/created?workspace_id=${P}&tab=files`);
    });
    expect(screen.getByTestId("page").textContent).toBe(P);
    expect(metadataReads).toBe(reads);
    expect(fixture.clients.at(-1)).toBe(personalCache);
    act(() => {
      fixture.replace(`/workspace/chats/old-team-chat?workspace_id=${T}`);
    });
    await waitFor(() => expect(screen.getByTestId("page").textContent).toBe(T));
    expect(fixture.clients.at(-1)).not.toBe(personalCache);
    const invalid = `/workspace/chats/old-team-chat?workspace_id=${T}&workspace_id=${P}`;
    act(() => {
      fixture.replace(invalid);
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: enUS.workspace.spaceSwitcher.personalAction,
        }),
      ).toBeTruthy(),
    );
    expect(screen.queryByTestId("page")).toBeNull();
    expect(
      screen
        .getByRole("link", { name: enUS.login.signIn })
        .getAttribute("href"),
    ).toBe(`/login?next=${encodeURIComponent(invalid)}`);
    fireEvent.click(
      screen.getByRole("button", {
        name: enUS.workspace.spaceSwitcher.personalAction,
      }),
    );
    await waitFor(() => expect(screen.getByTestId("page").textContent).toBe(P));
    expect(fixture.url).toBe(`/workspace/chats/new?workspace_id=${P}`);
    expect(
      fixture.views.every(
        (view) =>
          new URL(view.url, "http://localhost").searchParams.get(
            "workspace_id",
          ) === view.workspace,
      ),
    ).toBe(true);
  });

  it("blocks unknown or unavailable capabilities, while an explicitly disabled legacy installation remains usable", async () => {
    const fetch = rs.fn();
    rs.stubGlobal("fetch", fetch);
    for (const capability of [null, { enabled: true, available: false }]) {
      fixture.capability = capability;
      const view = await mount();
      expect(fixture.privateRenders).toEqual([]);
      expect(screen.queryByTestId("page")).toBeNull();
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(fetch).not.toHaveBeenCalled();
      view.unmount();
    }
    fixture.capability = { enabled: false, available: false };
    fixture.url = `/workspace/chats/private?workspace_id=${T}`;
    const scoped = await mount();
    expect(screen.queryByTestId("page")).toBeNull();
    expect(screen.getByRole("alert")).toBeTruthy();
    scoped.unmount();
    fixture.url = "/workspace/chats/new";
    await mount();
    expect(screen.getByTestId("page").textContent).toBe("legacy");
    expect(
      screen.queryByRole("button", { name: /Switch workspace:/ }),
    ).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
});
