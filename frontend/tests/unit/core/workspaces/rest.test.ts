import { afterEach, describe, expect, it, rs } from "@rstest/core";

import * as gateway from "@/core/api/fetcher";

const A = "11111111-1111-1111-1111-111111111111";
const B = "22222222-2222-2222-2222-222222222222";
const api = "http://localhost:2026/api/threads";
function scope(workspaceId: string, controller = new AbortController()) {
  return { actorUserId: "alice", workspaceId, signal: controller.signal };
}
function location() {
  const value = {
    origin: "http://localhost:2026",
    href: "http://localhost:2026/workspace",
    pathname: "/workspace",
    search: "",
  };
  rs.stubGlobal("window", { location: value });
  return value;
}
afterEach(() => {
  rs.unstubAllGlobals();
});

describe("workspace REST request lifetime", () => {
  it("pins the workspace and preserves native Request body, CSRF and cancellation", async () => {
    const here = location();
    here.href = "http://localhost:2026/workspace/chats/current";
    here.pathname = "/workspace/chats/current";
    rs.stubGlobal("document", { cookie: "csrf_token=rest-csrf" });
    const selected = scope(A);
    const first = gateway.createWorkspaceRESTClient(selected);
    const second = gateway.createWorkspaceRESTClient(scope(B));
    selected.workspaceId = B;
    const caller = new AbortController();
    const sourceHeaders = new Headers({
      "Content-Type": "application/json",
      "X-Custom": "kept",
    });
    const request = new Request(api, {
      method: "POST",
      headers: sourceHeaders,
      body: JSON.stringify({ title: "A report" }),
      signal: caller.signal,
    });
    const seen: {
      url: string;
      workspace: string | null;
      csrf: string | null;
      method: string;
      body: string;
      signal: AbortSignal;
      credentials: RequestCredentials;
      redirect: RequestRedirect;
      spoofedActor: boolean;
    }[] = [];
    rs.stubGlobal(
      "fetch",
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const outgoing = new Request(
          input instanceof Request ? input : new URL(input, here.href),
          init,
        );
        seen.push({
          url: outgoing.url,
          workspace: outgoing.headers.get("X-Deerflow-Workspace"),
          csrf: outgoing.headers.get("X-CSRF-Token"),
          method: outgoing.method,
          body: await outgoing.text(),
          signal: outgoing.signal,
          credentials: outgoing.credentials,
          redirect: outgoing.redirect,
          spoofedActor: outgoing.headers.has("X-Deerflow-User"),
        });
        return Response.json({ ok: true });
      },
    );
    await first.fetch(request);
    await second.json("api/threads");
    expect(seen.map((row) => row.workspace)).toEqual([A, B]);
    expect(seen[1]?.url).toBe(api);
    expect(seen[0]).toMatchObject({
      csrf: "rest-csrf",
      method: "POST",
      body: JSON.stringify({ title: "A report" }),
      credentials: "include",
      redirect: "error",
      spoofedActor: false,
    });
    expect(sourceHeaders.has("X-CSRF-Token")).toBe(false);
    expect(request.headers.has("X-Deerflow-Workspace")).toBe(false);
    caller.abort();
    expect(seen[0]?.signal.aborted).toBe(true);
    await first.fetch(new Request(api, { signal: caller.signal }), {
      signal: null,
    });
    expect(seen[2]?.signal.aborted).toBe(false);
  });

  it("refuses foreign destinations, conflicting selectors and expired lifetimes before dispatch", async () => {
    location();
    const controller = new AbortController();
    const client = gateway.createWorkspaceRESTClient(scope(A, controller));
    const network = rs.fn(async () => Response.json({ ok: true }));
    rs.stubGlobal("fetch", network);
    await expect(
      client.fetch("https://untrusted.example.test/api/threads"),
    ).rejects.toThrow();
    await expect(
      client.fetch("http://localhost:2026/unrelated"),
    ).rejects.toThrow();
    await expect(
      client.fetch(api, { headers: { "X-Deerflow-Workspace": B } }),
    ).rejects.toThrow();
    controller.abort();
    await expect(client.json(api)).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(network).not.toHaveBeenCalled();
  });

  it("rejects old HTTP/JSON results before redirects or publication, including caller cancellation", async () => {
    const here = location();
    const controller = new AbortController();
    const old = gateway.createWorkspaceRESTClient(scope(A, controller));
    let entered!: () => void;
    const dispatched = new Promise<void>((resolve) => {
      entered = resolve;
    });
    let reply!: (response: Response) => void;
    rs.stubGlobal(
      "fetch",
      () =>
        new Promise<Response>((resolve) => {
          reply = resolve;
          entered();
        }),
    );
    const pending = old.json(api);
    await dispatched;
    controller.abort();
    reply(Response.json({ detail: "old session" }, { status: 401 }));
    const outcomes = await Promise.allSettled([pending]);

    for (const cancelled of ["workspace", "caller"]) {
      const lifetime = new AbortController();
      const caller = new AbortController();
      const client = gateway.createWorkspaceRESTClient(scope(B, lifetime));
      let body!: ReadableStreamDefaultController<Uint8Array>;
      let parsing!: () => void;
      const started = new Promise<void>((resolve) => {
        parsing = resolve;
      });
      const stream = new ReadableStream<Uint8Array>({
        start(value) {
          body = value;
        },
      });
      const response = new Response(stream, {
        headers: { "Content-Type": "application/json" },
      });
      const originalJSON = response.json.bind(response);
      response.json = () => {
        parsing();
        return originalJSON();
      };
      rs.stubGlobal("fetch", async () => response);
      const reading = client.json(api, { signal: caller.signal });
      await started;
      (cancelled === "workspace" ? lifetime : caller).abort();
      body.enqueue(new TextEncoder().encode('{"report":"must not publish"}'));
      body.close();
      outcomes.push(...(await Promise.allSettled([reading])));
    }
    expect(outcomes).toMatchObject([
      { status: "rejected", reason: { name: "AbortError" } },
      { status: "rejected", reason: { name: "AbortError" } },
      { status: "rejected", reason: { name: "AbortError" } },
    ]);
    expect(here.href).toBe("http://localhost:2026/workspace");
  });
});
