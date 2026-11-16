import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import {
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { useAgents } from "@/core/agents/hooks";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { useModels } from "@/core/models/hooks";
import { useProjects } from "@/core/projects/hooks";
import { UserPreferencesBoundary } from "@/core/settings/user-preferences-boundary";
import { isStaticWebsiteOnly } from "@/core/static-mode";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/workspace",
}));
rs.mock("@/core/settings/user-preferences", () => ({
  startUserPreferences: () => () => undefined,
}));
rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: rs.fn(() => false),
}));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

const userA: User = {
  id: "user-A",
  email: "a@example.test",
  system_role: "user",
  needs_setup: false,
};
const userB: User = { ...userA, id: "user-B", email: "b@example.test" };
let auth: ReturnType<typeof useAuth>;
let client: QueryClient;
let owner: "A" | "B";
let failReads: boolean;
let holdAReads: boolean;
let pendingReads: Array<() => void>;
let snapshots: Array<{ user: string | undefined; data: string }>;
const clients = new Set<QueryClient>();
const requests = rs.fn();

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => (resolve = done));
  return { promise, resolve };
}

function response(url: string, account: string) {
  if (url.endsWith("/api/projects?status=active")) {
    return Response.json({
      projects: [
        { id: `${account}-project`, name: `${account} private project` },
      ],
    });
  }
  if (url.endsWith("/api/agents")) {
    return Response.json({ agents: [{ name: `${account}-private-agent` }] });
  }
  if (url.endsWith("/api/models")) {
    return Response.json({ models: [{ name: `${account}-private-model` }] });
  }
  throw new Error(`Unexpected request: ${url}`);
}

function AuthProbe() {
  auth = useAuth();
  return <output data-testid="user">{auth.user?.id ?? "signed out"}</output>;
}

function QueryProbe() {
  const { user } = useAuth();
  client = useQueryClient();
  clients.add(client);
  const projects = useProjects("active");
  const agents = useAgents();
  const models = useModels();
  const data = JSON.stringify({
    projects: projects.data,
    agents: agents.agents,
    models: models.models,
  });
  snapshots.push({ user: user?.id, data });
  return <output data-testid="data">{data}</output>;
}

function App({ children = <QueryProbe /> }: { children?: ReactNode }) {
  return (
    <AuthProvider initialUser={userA}>
      <AuthProbe />
      <QueryClientProvider>
        <UserPreferencesBoundary>{children}</UserPreferencesBoundary>
      </QueryClientProvider>
    </AuthProvider>
  );
}

async function expectAccount(account: "A" | "B") {
  await waitFor(() => {
    const text = screen.getByTestId("data").textContent;
    expect(text).toContain(`${account} private project`);
    expect(text).toContain(`${account}-private-agent`);
    expect(text).toContain(`${account}-private-model`);
  });
}

beforeEach(() => {
  rs.mocked(isStaticWebsiteOnly).mockReturnValue(false);
  owner = "A";
  failReads = false;
  holdAReads = false;
  pendingReads = [];
  snapshots = [];
  requests.mockReset();
  rs.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    requests(url, owner);
    if (url.endsWith("/api/v1/auth/me")) {
      return Response.json(owner === "A" ? userA : userB);
    }
    if (failReads) return new Response("unavailable", { status: 503 });
    if (holdAReads && owner === "A") {
      return new Promise<Response>((resolve) => {
        pendingReads.push(() => resolve(response(url, "A")));
      });
    }
    return response(url, owner);
  });
});

afterEach(() => {
  cleanup();
  for (const queryClient of clients) queryClient.clear();
  clients.clear();
  rs.restoreAllMocks();
});

test("a confirmed account switch never renders the previous account, even when new reads fail", async () => {
  render(<App />);
  await expectAccount("A");
  const oldClient = client;
  owner = "B";
  failReads = true;
  await act(async () => auth.refreshUser());

  expect(screen.getByTestId("user").textContent).toBe(userB.id);
  expect(screen.getByTestId("data").textContent).not.toContain("A");
  expect(
    snapshots.filter((snapshot) => snapshot.user === userB.id).length,
  ).toBeGreaterThan(0);
  for (const snapshot of snapshots.filter((item) => item.user === userB.id)) {
    expect(snapshot.data).not.toContain("A");
  }
  expect(client).not.toBe(oldClient);
  expect(oldClient.getQueryCache().getAll()).toEqual([]);
  expect(requests).toHaveBeenCalledWith("/api/models", "B");
});

test("late queries from the previous account cannot replace the new account's data", async () => {
  holdAReads = true;
  render(<App />);
  await waitFor(() => expect(pendingReads).toHaveLength(3));
  owner = "B";
  act(() => auth.applyUser(userB));
  await expectAccount("B");

  await act(async () => {
    for (const resolve of pendingReads) resolve();
  });
  await expectAccount("B");
  for (const snapshot of snapshots.filter((item) => item.user === userB.id)) {
    expect(snapshot.data).not.toContain("A");
  }
});

test("late mutation callbacks retain only the previous account's client", async () => {
  const pending = deferred<void>();
  const callback = rs.fn();
  let mutate!: () => Promise<void>;
  function MutationProbe() {
    const queryClient = useQueryClient();
    const mutation = useMutation({
      mutationFn: () => pending.promise,
      onSuccess: () => {
        callback();
        queryClient.setQueryData(
          ["projects", { status: "active" }],
          [{ id: "A-late-project", name: "A late mutation" }],
        );
      },
    });
    mutate = () => mutation.mutateAsync();
    return <QueryProbe />;
  }
  render(
    <App>
      <MutationProbe />
    </App>,
  );
  await expectAccount("A");
  let completion!: Promise<void>;
  act(() => {
    completion = mutate();
  });
  owner = "B";
  act(() => auth.applyUser(userB));
  await expectAccount("B");
  await act(async () => {
    pending.resolve();
    await completion;
  });

  expect(callback).toHaveBeenCalledOnce();
  await expectAccount("B");
  expect(screen.getByTestId("data").textContent).not.toContain("A");
});

test("logout clears query consumers immediately, before the server confirms logout", async () => {
  render(<App />);
  await expectAccount("A");
  const oldClient = client;
  const pending = deferred<Response>();
  rs.mocked(globalThis.fetch).mockReturnValue(pending.promise);
  let completion!: Promise<void>;
  act(() => {
    completion = auth.logout();
  });

  expect(screen.getByTestId("user").textContent).toBe("signed out");
  expect(screen.queryByTestId("data")).toBeNull();
  expect(oldClient.getQueryCache().getAll()).toEqual([]);
  expect(globalThis.fetch).toHaveBeenLastCalledWith("/api/v1/auth/logout", {
    method: "POST",
    credentials: "include",
  });
  await act(async () => {
    pending.resolve(new Response(null, { status: 204 }));
    await completion;
  });
});

test.each(["token_expired", "account_disabled"])(
  "a confirmed %s session clears the old query cache",
  async (code) => {
    render(<App />);
    await expectAccount("A");
    const oldClient = client;
    rs.mocked(globalThis.fetch).mockResolvedValue(
      Response.json({ detail: { code, message: code } }, { status: 401 }),
    );
    await act(async () => auth.refreshUser());

    expect(screen.getByTestId("user").textContent).toBe("signed out");
    expect(screen.queryByTestId("data")).toBeNull();
    expect(oldClient.getQueryCache().getAll()).toEqual([]);
  },
);

test("static demo auth still mounts query consumers and logout clears them", async () => {
  rs.mocked(isStaticWebsiteOnly).mockReturnValue(true);
  render(<App />);
  await waitFor(() => expect(screen.getByTestId("data")).toBeTruthy());
  expect(
    requests.mock.calls.some(([url]) => url === "/api/projects?status=active"),
  ).toBe(false);
  await act(async () => auth.logout());

  expect(screen.queryByTestId("data")).toBeNull();
  expect(
    requests.mock.calls.some(([url]) => url === "/api/v1/auth/logout"),
  ).toBe(false);
});

test("refreshing the same account preserves the client and session-fresh model data", async () => {
  render(<App />);
  await expectAccount("A");
  const oldClient = client;
  await act(async () => auth.refreshUser());

  expect(client).toBe(oldClient);
  expect(
    requests.mock.calls.filter(([url]) => url === "/api/models"),
  ).toHaveLength(1);
  await expectAccount("A");
});

test("StrictMode effect replay preserves active observers and cache invalidation", async () => {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  await expectAccount("A");
  expect(client.getQueryCache().getAll()).toHaveLength(3);
  owner = "B";
  await act(async () => {
    await client.invalidateQueries();
  });
  await expectAccount("B");
  expect(client.getQueryCache().getAll()).toHaveLength(3);
});

test("providers without auth and with unknown auth have independent mount-local caches", () => {
  function ClientProbe() {
    client = useQueryClient();
    clients.add(client);
    return <output>public content</output>;
  }
  const first = render(
    <QueryClientProvider>
      <ClientProbe />
    </QueryClientProvider>,
  );
  const firstClient = client;
  firstClient.setQueryData(["models"], "private data");
  first.unmount();
  render(
    <AuthProvider initialUser={null} initialAuthUnknown>
      <QueryClientProvider>
        <ClientProbe />
      </QueryClientProvider>
    </AuthProvider>,
  );

  expect(screen.getByText("public content")).toBeTruthy();
  expect(client).not.toBe(firstClient);
  expect(client.getQueryData(["models"])).toBeUndefined();
});
