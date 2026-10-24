import { afterEach, expect, it, rs } from "@rstest/core";

import { createWorkspaceRESTClient } from "@/core/api/fetcher";
import { compactThreadContext, createThread } from "@/core/threads/api";

const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
function fixture() {
  rs.stubGlobal("window", {
    location: {
      origin: "http://localhost:2026",
      pathname: "/workspace",
      search: "",
    },
  });
  rs.stubGlobal("document", { cookie: "csrf_token=create-compact" });
  const seen: {
    path: string;
    workspace: string | null;
    body: unknown;
    csrf: string | null;
    signal?: AbortSignal | null;
  }[] = [];
  let hold = false;
  let entered: (() => void) | undefined;
  let decoderEntered = Promise.resolve();
  let release: (() => void) | undefined;
  rs.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        "http://localhost:2026",
      );
      const headers = new Headers(init?.headers);
      seen.push({
        path: url.pathname,
        workspace: headers.get("X-Deerflow-Workspace"),
        csrf: headers.get("X-CSRF-Token"),
        signal: init?.signal,
        body:
          typeof init?.body === "string"
            ? (JSON.parse(init.body) as unknown)
            : null,
      });
      const body = url.pathname.endsWith("/compact")
        ? { thread_id: "thread/1", compacted: true }
        : {
            thread_id: "thread/1",
            metadata: { deerflow_project_id: "project" },
          };
      const response = Response.json(body);
      if (hold)
        response.json = () =>
          new Promise((resolve) => {
            release = () => resolve(body);
            entered!();
          });
      return response;
    },
  );
  return {
    seen,
    hold: () => {
      hold = true;
      decoderEntered = new Promise<void>((resolve) => {
        entered = resolve;
      });
    },
    waitForDecoder: () => decoderEntered,
    release: () => {
      expect(release).toBeDefined();
      release!();
    },
  };
}
function client(workspaceId: string, controller = new AbortController()) {
  return createWorkspaceRESTClient({
    actorUserId: "alice",
    workspaceId,
    signal: controller.signal,
  });
}
afterEach(() => {
  rs.unstubAllGlobals();
});

it("creates a project thread and compacts through each fixed workspace client with native bodies and CSRF", async () => {
  const server = fixture();
  for (const workspace of [P, T]) {
    const rest = client(workspace);
    await expect(
      createThread("thread/1", "project", { rest }),
    ).resolves.toMatchObject({ thread_id: "thread/1" });
    await expect(
      compactThreadContext("thread/1", {
        rest,
        agentName: "research",
        modelName: "deepseek",
      }),
    ).resolves.toMatchObject({ compacted: true });
  }
  expect(server.seen.map((row) => row.workspace)).toEqual([P, P, T, T]);
  expect(server.seen.every((row) => row.csrf === "create-compact")).toBe(true);
  expect(server.seen[0]).toMatchObject({
    path: "/api/threads",
    body: { thread_id: "thread/1", project_id: "project" },
  });
  expect(server.seen[1]).toMatchObject({
    path: "/api/threads/thread%2F1/compact",
    body: { force: true, agent_name: "research", model_name: "deepseek" },
  });
});

it("rejects late decoded create/compact results and expired clients before another request", async () => {
  const server = fixture();
  for (const action of ["create", "compact"]) {
    server.hold();
    const controller = new AbortController();
    const rest = client(P, controller);
    const pending = (
      action === "create"
        ? createThread("thread/1", "project", { rest })
        : compactThreadContext("thread/1", { rest })
    ).catch((error: unknown) => error);
    // Let the native response enter its deferred JSON decoder, not merely fetch.
    await server.waitForDecoder();
    controller.abort();
    server.release();
    expect(await pending).toMatchObject({ name: "AbortError" });
    const count = server.seen.length;
    await expect(
      createThread("thread/1", "project", { rest }),
    ).rejects.toMatchObject({ name: "AbortError" });
    await expect(
      compactThreadContext("thread/1", { rest }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(server.seen).toHaveLength(count);
  }
});
