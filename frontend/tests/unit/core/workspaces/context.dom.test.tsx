import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { useQuery } from "@tanstack/react-query";
import {
  act,
  cleanup,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  useWorkspaceLifetime,
} from "@/core/workspaces/context";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/workspace",
}));
const P = "11111111-1111-1111-1111-111111111111";
const Q = "44444444-4444-4444-4444-444444444444";
const A = "22222222-2222-2222-2222-222222222222";
const B = "33333333-3333-3333-3333-333333333333";
const alice: User = {
  id: "alice",
  email: "alice@example.test",
  system_role: "user",
  needs_setup: false,
};
const bob: User = { ...alice, id: "bob", email: "bob@example.test" };
type Record = {
  path: string;
  workspace: string | null;
  signal?: AbortSignal | null;
  method?: string;
  credentials?: RequestCredentials;
};
function server() {
  const seen: Record[] = [];
  let actor = "alice";
  let corrupt: "actor" | "workspace" | "membership" | "policy" | null = null;
  let delayed = false;
  let release: (() => void) | undefined;
  let changeCookie = false;
  rs.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        window.location.href,
      ).pathname;
      const workspace = new Headers(init?.headers).get("X-Deerflow-Workspace");
      seen.push({
        path,
        workspace,
        signal: init?.signal,
        method: init?.method,
        credentials: init?.credentials,
      });
      if (path === "/api/v1/auth/me")
        return Response.json(actor === "alice" ? alice : bob);
      if (path === "/api/workspaces") {
        const personal = actor === "alice" ? P : Q;
        const rows = [
          {
            id: personal,
            name: "Personal",
            kind: "personal",
            status: "active",
            personal_user_id: actor,
            role: "owner",
            membership_version: 1,
            policy_version: 1,
          },
          {
            id: A,
            name: "Research",
            kind: "team",
            status: "active",
            personal_user_id: null,
            role: "admin",
            membership_version: 7,
            policy_version: 3,
          },
          {
            id: B,
            name: "Reports",
            kind: "team",
            status: "active",
            personal_user_id: null,
            role: "member",
            membership_version: 2,
            policy_version: 4,
          },
        ];
        if (changeCookie) {
          actor = "bob";
          changeCookie = false;
        }
        return Response.json(rows);
      }
      if (path === "/api/workspaces/current") {
        const value = {
          actor_user_id: actor,
          workspace_id: workspace,
          membership_version: workspace === A ? 7 : workspace === B ? 2 : 1,
          policy_version: workspace === A ? 3 : workspace === B ? 4 : 1,
        };
        if (corrupt === "actor") value.actor_user_id = "unexpected-actor";
        if (corrupt === "workspace")
          value.workspace_id = workspace === A ? B : A;
        if (corrupt === "membership") value.membership_version = 0;
        if (corrupt === "policy") value.policy_version += 1;
        const response = Response.json(value);
        if (delayed && workspace === A)
          return new Promise<Response>((resolve) => {
            release = () => resolve(response);
          });
        return response;
      }
      if (path === "/api/private-report")
        return Response.json({ report: `${actor}:${workspace}` });
      if (path === "/api/langgraph/threads/probe")
        return Response.json({ thread_id: "probe", workspace });
      throw new Error(`Unexpected context fixture request: ${path}`);
    },
  );
  return {
    seen,
    setCorrupt: (value: typeof corrupt) => {
      corrupt = value;
    },
    delayA: () => {
      delayed = true;
    },
    getRelease: () => release,
    changeCookieOnList: () => {
      changeCookie = true;
    },
  };
}
function ResourceProbe() {
  const lifetime = useWorkspaceLifetime();
  const query = useQuery({
    queryKey: ["private-report"],
    queryFn: ({ signal }) =>
      lifetime
        ? lifetime.rest.json<{ report: string }>("/api/private-report", {
            signal,
          })
        : Promise.resolve({ report: "unscoped" }),
    retry: false,
  });
  return (
    <div data-testid="private-report">{query.data?.report ?? "loading"}</div>
  );
}
function mounted(content = false, enabled = true) {
  return renderHook(
    () => ({ workspace: useWorkspaceContext(), auth: useAuth() }),
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <StrictMode>
          <AuthProvider initialUser={alice}>
            <QueryClientProvider>
              <WorkspaceProvider enabled={enabled}>
                {children}
                {content && (
                  <WorkspaceReadyBoundary
                    fallback={<div data-testid="blocked" />}
                  >
                    <WorkspaceProvider enabled={false}>
                      <ResourceProbe />
                    </WorkspaceProvider>
                  </WorkspaceReadyBoundary>
                )}
              </WorkspaceProvider>
            </QueryClientProvider>
          </AuthProvider>
        </StrictMode>
      ),
    },
  );
}
function active(view: ReturnType<typeof mounted>) {
  const value = view.result.current.workspace?.state.active;
  if (!value) throw new Error("Expected a confirmed workspace lifetime");
  return value;
}
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
});

describe("confirmed tab-local workspace context", () => {
  it("starts at personal scope and switches one mounted tab without retargeting another", async () => {
    const fixture = server();
    const first = mounted();
    const second = mounted();
    expect(first.result.current.workspace).not.toBeNull();
    await waitFor(() =>
      expect(first.result.current.workspace?.state.status).toBe("ready"),
    );
    await waitFor(() =>
      expect(second.result.current.workspace?.state.status).toBe("ready"),
    );
    const original = active(first);
    expect(original.context).toEqual({
      actorUserId: "alice",
      workspaceId: P,
      membershipVersion: 1,
      policyVersion: 1,
    });
    expect(active(second).scope.workspaceId).toBe(P);
    expect(active(second).sdk).not.toBe(original.sdk);
    await act(async () => {
      expect(await first.result.current.workspace?.select(A)).toBe(true);
    });
    expect(original.scope.signal.aborted).toBe(true);
    const team = active(first);
    expect(team.scope.workspaceId).toBe(A);
    expect(team.context).toMatchObject({
      membershipVersion: 7,
      policyVersion: 3,
    });
    expect(team.cacheKey).not.toBe(original.cacheKey);
    expect(active(second).scope.signal.aborted).toBe(false);
    expect(active(second).scope.workspaceId).toBe(P);
    await expect(team.rest.json("/api/private-report")).resolves.toEqual({
      report: `alice:${A}`,
    });
    await expect(team.sdk.threads.get("probe")).resolves.toMatchObject({
      workspace: A,
    });
    await expect(
      active(second).rest.json("/api/private-report"),
    ).resolves.toEqual({ report: `alice:${P}` });
    const count = fixture.seen.length;
    const legacy = mounted(false, false);
    expect(legacy.result.current.workspace).toBeNull();
    expect(fixture.seen).toHaveLength(count);
    expect(
      fixture.seen.every(
        (row) =>
          !row.path.includes("/cancel") && (row.method ?? "GET") === "GET",
      ),
    ).toBe(true);
  });

  it("detaches immediately and ignores an earlier selection response that arrives after the next one", async () => {
    const fixture = server();
    const view = mounted();
    expect(view.result.current.workspace).not.toBeNull();
    await waitFor(() =>
      expect(view.result.current.workspace?.state.status).toBe("ready"),
    );
    const personal = active(view);
    fixture.delayA();
    let stale!: Promise<boolean>;
    act(() => {
      stale = view.result.current.workspace!.select(A);
    });
    expect(personal.scope.signal.aborted).toBe(true);
    expect(view.result.current.workspace?.state.active).toBeNull();
    await waitFor(() => expect(fixture.getRelease()).toBeDefined());
    await act(async () => {
      expect(await view.result.current.workspace?.select(B)).toBe(true);
    });
    expect(active(view).scope.workspaceId).toBe(B);
    const pendingA = fixture.seen.find(
      (row) => row.path.endsWith("/current") && row.workspace === A,
    );
    expect(pendingA?.signal?.aborted).toBe(true);
    await act(async () => {
      fixture.getRelease()!();
      expect(await stale).toBe(false);
    });
    expect(active(view).scope.workspaceId).toBe(B);
    await expect(
      active(view).rest.json("/api/private-report"),
    ).resolves.toEqual({ report: `alice:${B}` });
  });

  it("blocks resources for invalid identity/version metadata and resets on native account change/logout", async () => {
    const fixture = server();
    const view = mounted(true);
    expect(screen.queryByTestId("private-report")).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId("private-report").textContent).toBe(
        `alice:${P}`,
      ),
    );
    await act(async () => {
      await view.result.current.workspace?.select(A);
    });
    await waitFor(() =>
      expect(screen.getByTestId("private-report").textContent).toBe(
        `alice:${A}`,
      ),
    );
    for (const corruption of [
      "actor",
      "workspace",
      "membership",
      "policy",
    ] as const) {
      const old = active(view);
      fixture.setCorrupt(corruption);
      await act(async () => {
        expect(await view.result.current.workspace?.refresh()).toBe(false);
      });
      expect(old.scope.signal.aborted).toBe(true);
      expect(view.result.current.workspace?.state).toMatchObject({
        status: "error",
        active: null,
        workspaces: [],
        error: "invalid_response",
      });
      expect(screen.queryByTestId("private-report")).toBeNull();
      fixture.setCorrupt(null);
      await act(async () => {
        expect(await view.result.current.workspace?.refresh()).toBe(true);
      });
      await waitFor(() =>
        expect(screen.getByTestId("private-report").textContent).toBe(
          `alice:${A}`,
        ),
      );
    }
    const aliceTeam = active(view);
    fixture.changeCookieOnList();
    await act(async () => {
      expect(await view.result.current.workspace?.refresh()).toBe(false);
    });
    expect(aliceTeam.scope.signal.aborted).toBe(true);
    expect(screen.queryByTestId("private-report")).toBeNull();
    expect(view.result.current.workspace?.state.error).toBe("invalid_response");
    act(() => {
      view.result.current.auth.applyUser(bob);
    });
    await waitFor(() =>
      expect(screen.getByTestId("private-report").textContent).toBe(`bob:${Q}`),
    );
    const bobPersonal = active(view);
    expect(bobPersonal.scope.actorUserId).toBe("bob");
    const count = fixture.seen.length;
    act(() => {
      view.result.current.auth.applyUser(null);
    });
    expect(screen.queryByTestId("private-report")).toBeNull();
    await waitFor(() => expect(bobPersonal.scope.signal.aborted).toBe(true));
    expect(view.result.current.workspace?.state.error).toBe(
      "authentication_required",
    );
    expect(fixture.seen).toHaveLength(count);
  });
});
