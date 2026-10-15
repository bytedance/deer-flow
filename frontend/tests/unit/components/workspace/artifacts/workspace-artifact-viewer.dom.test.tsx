import { afterEach, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, waitFor } from "@testing-library/react";

import ArtifactViewerPage from "@/app/artifacts/view/page";
import { QueryClientProvider } from "@/components/query-client-provider";
import {
  buildArtifactViewerURL,
  parseArtifactViewerQuery,
} from "@/core/artifacts/viewer";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

const mocks = rs.hoisted(() => ({
  authenticated: true,
  user: {
    id: "alice",
    email: "alice@example.test",
    system_role: "user",
    needs_setup: false,
  },
}));
rs.mock("@/core/auth/server", () => ({
  getServerSideUser: async () =>
    mocks.authenticated
      ? { tag: "authenticated", user: mocks.user }
      : { tag: "unauthenticated" },
}));
rs.mock("@/core/i18n/server", () => ({ getI18n: async () => ({ t: enUS }) }));
rs.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "access_token" ? { value: "fixture-session" } : undefined,
  }),
}));
rs.mock("next/navigation", () => ({
  usePathname: () => "/artifacts/view",
  useRouter: () => ({ push: rs.fn(), replace: rs.fn() }),
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
}));
const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
const FILE = "/mnt/user-data/outputs/report.md";
function fixture(
  options: {
    features?: unknown;
    status?: number;
    deny?: boolean;
    current?: (response: Response) => Response;
  } = {},
) {
  const seen: {
    path: string;
    workspace: string | null;
    cookie: string | null;
    actor: string;
  }[] = [];
  rs.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        location.href,
      );
      const headers = new Headers(init?.headers);
      const workspace = headers.get("X-Deerflow-Workspace");
      seen.push({
        path: url.pathname,
        workspace,
        cookie: headers.get("Cookie"),
        actor: mocks.user.id,
      });
      if (url.pathname === "/api/features")
        return Response.json(
          options.features === undefined
            ? { workspaces: { enabled: true, available: true } }
            : options.features,
          { status: options.status ?? 200 },
        );
      if (url.pathname === "/api/workspaces")
        return Response.json(
          [P, T].map((id) => ({
            id,
            name: id,
            kind: id === P ? "personal" : "team",
            personal_user_id: id === P ? mocks.user.id : null,
            status: "active",
            role: "owner",
            membership_version: 1,
            policy_version: 1,
          })),
        );
      if (url.pathname === "/api/workspaces/current") {
        const response = options.deny
          ? Response.json({ detail: "not found" }, { status: 404 })
          : Response.json({
              actor_user_id: mocks.user.id,
              workspace_id: workspace,
              membership_version: 1,
              policy_version: 1,
            });
        return options.current?.(response) ?? response;
      }
      if (url.pathname.includes("/artifacts/"))
        return new Response(
          `# ${mocks.user.id === "alice" ? "Report" : "Bob"}-${workspace}`,
          { headers: { ETag: `"${"a".repeat(64)}"` } },
        );
      throw new Error(`Unexpected artifact window request ${url.pathname}`);
    },
  );
  return seen;
}
async function open(
  workspaceId?: string,
  extra: Record<string, string | string[]> = {},
) {
  const params: Record<string, string> = { path: FILE, thread_id: "thread-1" };
  if (workspaceId !== undefined) params.workspace_id = workspaceId;
  const page = await ArtifactViewerPage({
    searchParams: Promise.resolve({ ...params, ...extra }),
  });
  return render(
    <QueryClientProvider>
      <I18nContext.Provider
        value={{ locale: "en-US", t: enUS, setLocale: () => undefined }}
      >
        {page}
      </I18nContext.Provider>
    </QueryClientProvider>,
  );
}
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
  rs.restoreAllMocks();
  mocks.authenticated = true;
  mocks.user = {
    id: "alice",
    email: "alice@example.test",
    system_role: "user",
    needs_setup: false,
  };
});
it("opens the original standalone renderer in each server-confirmed workspace and keeps scope on its native links", async () => {
  const seen = fixture();
  for (const workspaceId of [P, T]) {
    const view = await open(workspaceId);
    await waitFor(() =>
      expect(view.getByRole("heading", { level: 1 }).textContent).toBe(
        `Report-${workspaceId}`,
      ),
    );
    for (const name of ["View source", "Download"]) {
      const anchor = view.getByRole("link", { name });
      expect(
        new URL(anchor.getAttribute("href")!, location.href).searchParams.get(
          "workspace_id",
        ),
      ).toBe(workspaceId);
    }
    const url = buildArtifactViewerURL({
      filepath: FILE,
      threadId: "thread-1",
      isMock: false,
      workspaceId,
    });
    expect(
      parseArtifactViewerQuery(
        Object.fromEntries(new URL(url, location.href).searchParams),
      )?.workspaceId,
    ).toBe(workspaceId);
    view.unmount();
  }
  expect(
    seen
      .filter((row) => row.path.includes("/artifacts/"))
      .map((row) => row.workspace),
  ).toEqual([P, T]);
  expect(
    seen
      .filter((row) => row.path === "/api/workspaces/current")
      .map((row) => row.workspace),
  ).toEqual([P, T]);
  expect(
    seen
      .filter((row) => row.path === "/api/features")
      .every((row) => row.cookie === "access_token=fixture-session"),
  ).toBe(true);
});

it("never falls back to unscoped reads when capability, membership or target confirmation fails", async () => {
  for (const options of [
    { features: { workspaces: { enabled: true, available: false } } },
    { features: null },
    { features: {} },
    { deny: true },
  ]) {
    const seen = fixture(options);
    const view = await open(T);
    await waitFor(() =>
      expect(view.getByRole("alert").textContent).toBe(
        enUS.artifactPreview.unavailable,
      ),
    );
    expect(seen.some((row) => row.path.includes("/artifacts/"))).toBe(false);
    expect(view.queryByRole("link")).toBeNull();
    view.unmount();
  }
  const invalidTargets: Record<string, string | string[]>[] = [
    { workspace_id: "not-a-workspace" },
    { workspace_id: [T, P] },
    { mock: "true" },
  ];
  for (const extra of invalidTargets) {
    const seen = fixture();
    const view = await open(T, extra);
    expect(view.getByText(enUS.artifactPreview.missingTarget)).toBeTruthy();
    expect(seen).toEqual([]);
    view.unmount();
  }
  // Auth-disabled development cannot activate workspace mode on the Gateway.
  rs.stubEnv("DEER_FLOW_AUTH_DISABLED", "1");
  rs.stubEnv("DEER_FLOW_ENV", "test");
  rs.stubEnv("ENVIRONMENT", "test");
  try {
    const devSeen = fixture();
    const devView = await open();
    await waitFor(() =>
      expect(devView.getByRole("heading", { level: 1 }).textContent).toBe(
        "Report-null",
      ),
    );
    expect(
      devSeen.some(
        (row) => row.path === "/api/features" || row.path === "/api/workspaces",
      ),
    ).toBe(false);
    devView.unmount();
  } finally {
    rs.unstubAllEnvs();
  }
  // An older server still uses its native standalone route for unscoped links.
  const seen = fixture({ features: {} });
  const view = await open();
  await waitFor(() =>
    expect(view.getByRole("heading", { level: 1 }).textContent).toBe(
      "Report-null",
    ),
  );
  expect(seen.some((row) => row.path === "/api/workspaces")).toBe(false);
  view.unmount();
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
it("preserves the workspace login return and detaches an old actor's pending window before its body arrives", async () => {
  mocks.authenticated = false;
  let redirect = "";
  try {
    await ArtifactViewerPage({
      searchParams: Promise.resolve({
        path: FILE,
        thread_id: "thread-1",
        workspace_id: T,
      }),
    });
  } catch (error) {
    if (!(error instanceof Error)) throw error;
    redirect = error.message;
  }
  expect(redirect.startsWith("REDIRECT:/login?")).toBe(true);
  const login = new URL(redirect.slice("REDIRECT:".length), location.href);
  const next = login.searchParams.get("next");
  expect(next).not.toBeNull();
  expect(new URL(next!, location.href).searchParams.get("workspace_id")).toBe(
    T,
  );
  mocks.authenticated = true;
  const gate = deferred<void>();
  const entered = deferred<void>();
  const decoded = deferred<void>();
  let held = false;
  const seen = fixture({
    current: (response) => {
      if (held) return response;
      held = true;
      const decode = response.json.bind(response);
      rs.spyOn(response, "json").mockImplementation(async () => {
        entered.resolve();
        await gate.promise;
        const value: unknown = await decode();
        decoded.resolve();
        return value;
      });
      return response;
    },
  });
  const tree = (page: React.ReactNode) => (
    <QueryClientProvider>
      <I18nContext.Provider
        value={{ locale: "en-US", t: enUS, setLocale: () => undefined }}
      >
        {page}
      </I18nContext.Provider>
    </QueryClientProvider>
  );
  const params = { path: FILE, thread_id: "thread-1", workspace_id: T };
  const view = render(
    tree(await ArtifactViewerPage({ searchParams: Promise.resolve(params) })),
  );
  await entered.promise;
  expect(view.queryByRole("link")).toBeNull();
  mocks.user = {
    id: "bob",
    email: "bob@example.test",
    system_role: "user",
    needs_setup: false,
  };
  view.rerender(
    tree(await ArtifactViewerPage({ searchParams: Promise.resolve(params) })),
  );
  await waitFor(() =>
    expect(view.getByRole("heading", { level: 1 }).textContent).toBe(
      `Bob-${T}`,
    ),
  );
  await act(async () => {
    gate.resolve();
    await decoded.promise;
  });
  expect(view.getByRole("heading", { level: 1 }).textContent).toBe(`Bob-${T}`);
  expect(
    seen
      .filter((row) => row.path.includes("/artifacts/"))
      .map((row) => [row.actor, row.workspace]),
  ).toEqual([["bob", T]]);
});
