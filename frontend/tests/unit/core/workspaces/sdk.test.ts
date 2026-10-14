import { afterEach, describe, expect, it, rs } from "@rstest/core";

import { getAPIClient } from "@/core/api/api-client";

const A = "11111111-1111-1111-1111-111111111111";
const B = "22222222-2222-2222-2222-222222222222";

function scope(workspaceId: string, controller = new AbortController()) {
  return { actorUserId: "alice", workspaceId, signal: controller.signal };
}

function sse(body: string, headers?: HeadersInit) {
  return new Response(body, {
    headers: { "Content-Type": "text/event-stream", ...headers },
  });
}

afterEach(() => {
  rs.unstubAllGlobals();
});

describe("SDK private workspace lifetime", () => {
  it("separates clients and pins actor/workspace even if caller metadata changes", async () => {
    const controller = new AbortController();
    const selectedA = scope(A, controller);
    const selectedB = scope(B);
    const clientA = getAPIClient(false, selectedA);
    const clientB = getAPIClient(false, selectedB);
    expect(clientA).not.toBe(clientB);
    expect(getAPIClient(false, selectedA)).toBe(clientA);
    expect(getAPIClient(false, { ...selectedB, actorUserId: "bob" })).not.toBe(
      clientB,
    );
    const requests: RequestInit[] = [];
    rs.stubGlobal(
      "fetch",
      async (_url: RequestInfo | URL, init?: RequestInit) => {
        requests.push(init ?? {});
        return Response.json({ thread_id: "private-thread" });
      },
    );
    selectedA.workspaceId = B;
    await clientA.threads.get("private-thread");
    await clientB.threads.get("other-thread");
    expect(
      requests.map((init) =>
        new Headers(init.headers).get("X-Deerflow-Workspace"),
      ),
    ).toEqual([A, B]);
    expect(
      requests.every(
        (init) => init.credentials === "include" && init.redirect === "error",
      ),
    ).toBe(true);
    expect(new Headers(requests[0]?.headers).has("X-Deerflow-User")).toBe(
      false,
    );
    controller.abort();
    await expect(
      clientA.threads.get("must-not-dispatch"),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(requests).toHaveLength(2);
    await clientB.threads.get("still-live");
    expect(
      new Headers(requests.at(-1)?.headers).get("X-Deerflow-Workspace"),
    ).toBe(B);
  });

  it("keeps creation, durable reload and resumed stream on the original scope", async () => {
    const selectedA = scope(A);
    const clientA = getAPIClient(false, selectedA);
    const reconnect = new Map<string, string>();
    rs.stubGlobal("window", {
      location: { origin: "http://localhost:2026" },
      sessionStorage: {
        getItem: (key: string) => reconnect.get(key) ?? null,
        setItem: (key: string, value: string) => reconnect.set(key, value),
        removeItem: (key: string) => reconnect.delete(key),
      },
    });
    const requests: { path: string; init: RequestInit }[] = [];
    const gap = {
      code: "stream_replay_gap",
      run_id: "run-a",
      requested_event_id: "1-0",
      earliest_available_event_id: "3-0",
      latest_available_event_id: "5-0",
      recovery: "reload_durable_state",
    };
    rs.stubGlobal(
      "fetch",
      async (url: RequestInfo | URL, init?: RequestInit) => {
        const path =
          typeof url === "string"
            ? url
            : url instanceof URL
              ? url.href
              : url.url;
        requests.push({ path, init: init ?? {} });
        if (path.endsWith("/threads/thread-a/runs/stream")) {
          selectedA.workspaceId = B;
          getAPIClient(false, scope(B));
          return sse(`event: gap\ndata: ${JSON.stringify(gap)}\n\n`, {
            "Content-Location": "/threads/thread-a/runs/run-a",
          });
        }
        if (path.includes("/threads/thread-a/state"))
          return Response.json({
            values: { messages: [{ type: "ai", content: "A durable report" }] },
          });
        if (path.includes("/runs/run-a/stream"))
          return sse("event: end\ndata: null\n\n");
        throw new Error("Unexpected SDK request");
      },
    );
    const events: string[] = [];
    const lazy = clientA.runs.stream("thread-a", "lead_agent", {
      onDisconnect: "cancel",
    });
    expect(requests).toHaveLength(0);
    for await (const entry of lazy) events.push(entry.event);
    expect(events).toEqual(["custom", "values", "end"]);
    expect(
      requests.map(({ init }) =>
        new Headers(init.headers).get("X-Deerflow-Workspace"),
      ),
    ).toEqual([A, A, A]);
    expect(JSON.parse(requests[0]?.init.body as string).on_disconnect).toBe(
      "continue",
    );
    expect(new Headers(requests[2]?.init.headers).get("Last-Event-ID")).toBe(
      "5-0",
    );
    expect(reconnect.get(`lg:stream:workspace:alice:${A}:thread-a`)).toBe(
      "run-a",
    );
    expect(reconnect.has(`lg:stream:workspace:alice:${B}:thread-a`)).toBe(
      false,
    );
    expect(reconnect.has("lg:stream:thread-a")).toBe(false);
  });

  it("refuses a late HTTP reply and old stream frames after its lifetime ends", async () => {
    const httpController = new AbortController();
    const httpClient = getAPIClient(false, scope(A, httpController));
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
    const pending = httpClient.threads.get("thread-a");
    await dispatched;
    httpController.abort();
    reply(Response.json({ thread_id: "must-not-return" }));
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });

    for (const fault of ["stale-frame", "transport"]) {
      let attempts = 0;
      const streamController = new AbortController();
      const streamClient = getAPIClient(false, scope(A, streamController));
      let source!: ReadableStreamDefaultController<Uint8Array>;
      let sourceClosed = false;
      const encoder = new TextEncoder();
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          source = controller;
          source.enqueue(
            encoder.encode('event: updates\ndata: {"frame":"first"}\n\n'),
          );
        },
        cancel() {
          sourceClosed = true;
        },
      });
      rs.stubGlobal("fetch", async () => {
        attempts += 1;
        return new Response(body, {
          headers: {
            "Content-Type": "text/event-stream",
            "Content-Location": "/threads/thread-a/runs/run-a",
            Location: "/threads/thread-a/runs/run-a/stream",
          },
        });
      });
      const iterator = streamClient.runs
        .stream("thread-a", "lead_agent")
        [Symbol.asyncIterator]();
      expect((await iterator.next()).value?.event).toBe("updates");
      streamController.abort();
      if (!sourceClosed && fault === "transport") {
        source.error(new TypeError("connection interrupted"));
      } else if (!sourceClosed) {
        source.enqueue(
          encoder.encode('event: updates\ndata: {"frame":"stale"}\n\n'),
        );
        source.close();
      }
      await expect(iterator.next()).rejects.toMatchObject({
        name: "AbortError",
      });
      expect(attempts).toBe(1);
    }
  });
});
