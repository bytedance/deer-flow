import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

async function loadRunStreamRoute() {
  vi.resetModules();
  return await import("@/app/api/langgraph/threads/[threadId]/runs/stream/route");
}

async function loadJoinStreamRoute() {
  vi.resetModules();
  return await import("@/app/api/langgraph/threads/[threadId]/runs/[runId]/stream/route");
}

function makeRunContext(threadId: string) {
  return {
    params: Promise.resolve({ threadId }),
  };
}

function makeJoinContext(threadId: string, runId: string) {
  return {
    params: Promise.resolve({ threadId, runId }),
  };
}

describe("LangGraph stream route proxies", () => {
  const originalGatewayBaseUrl =
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL;

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL;
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL =
      "http://gateway.example/base/";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL;
    if (originalGatewayBaseUrl === undefined) {
      delete process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL;
    } else {
      process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = originalGatewayBaseUrl;
    }
  });

  test("proxies new run streams to the gateway stream endpoint", async () => {
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await loadRunStreamRoute();
    const request = new NextRequest(
      "http://localhost:3000/api/langgraph/threads/ignored/runs/stream?after=a%2Fb",
      {
        method: "POST",
        body: JSON.stringify({ ok: true }),
      },
    );
    await POST(request, makeRunContext("thread/a?b"));

    expect(fetchMock).toHaveBeenCalledWith(
      "http://gateway.example/base/api/threads/thread%2Fa%3Fb/runs/stream?after=a%2Fb",
      expect.objectContaining({ method: "POST", signal: request.signal }),
    );
  });

  test("proxies resumable join streams to the gateway stream endpoint", async () => {
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { GET } = await loadJoinStreamRoute();
    const request = new NextRequest(
      "http://localhost:3000/api/langgraph/threads/ignored/runs/ignored/stream",
    );
    await GET(request, makeJoinContext("thread-id", "run/id"));

    expect(fetchMock).toHaveBeenCalledWith(
      "http://gateway.example/base/api/threads/thread-id/runs/run%2Fid/stream",
      expect.objectContaining({ method: "GET", signal: request.signal }),
    );
  });

  test("strips proxy headers while forwarding auth headers and streamed body", async () => {
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await loadRunStreamRoute();
    const request = new NextRequest(
      "http://localhost:3000/api/langgraph/threads/thread-id/runs/stream",
      {
        method: "POST",
        headers: {
          host: "localhost:3000",
          connection: "keep-alive, x-remove",
          "content-length": "123",
          "transfer-encoding": "chunked",
          cookie: "access_token=abc",
          "x-csrf-token": "csrf",
          "accept-encoding": "gzip, br",
          "x-remove": "secret",
        },
        body: JSON.stringify({ ok: true }),
      },
    );
    const body = request.body;

    await POST(request, makeRunContext("thread-id"));

    const fetchCalls = fetchMock.mock.calls as unknown as [
      string,
      RequestInit & { duplex?: "half" },
    ][];
    const init = fetchCalls[0]?.[1];
    expect(init).toBeDefined();
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(body);
    expect(init?.duplex).toBe("half");
    const headers = init?.headers as Headers;
    expect(headers.get("host")).toBeNull();
    expect(headers.get("connection")).toBeNull();
    expect(headers.get("content-length")).toBeNull();
    expect(headers.get("transfer-encoding")).toBeNull();
    expect(headers.get("x-remove")).toBeNull();
    expect(headers.get("cookie")).toBe("access_token=abc");
    expect(headers.get("x-csrf-token")).toBe("csrf");
    expect(headers.get("accept-encoding")).toBe("identity");
  });

  test("streams upstream bodies while preserving response headers", async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("event: metadata\n\n"));
        controller.close();
      },
    });
    const fetchMock = vi.fn(
      async () =>
        new Response(stream, {
          status: 201,
          statusText: "Created",
          headers: {
            "cache-control": "private, no-store",
            "content-length": "999",
            connection: "close, x-response-remove",
            "transfer-encoding": "chunked",
            "x-response-remove": "secret",
          },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await loadRunStreamRoute();
    const response = await POST(
      new NextRequest(
        "http://localhost:3000/api/langgraph/threads/thread-id/runs/stream",
        {
          method: "POST",
          body: JSON.stringify({ ok: true }),
        },
      ),
      makeRunContext("thread-id"),
    );

    expect(response.status).toBe(201);
    expect(response.statusText).toBe("Created");
    expect(response.body).toBe(stream);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(response.headers.get("content-length")).toBeNull();
    expect(response.headers.get("connection")).toBeNull();
    expect(response.headers.get("transfer-encoding")).toBeNull();
    expect(response.headers.get("x-response-remove")).toBeNull();
  });

  test("does not synthesize cache-control when upstream omits it", async () => {
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await loadRunStreamRoute();
    const response = await POST(
      new NextRequest(
        "http://localhost:3000/api/langgraph/threads/thread-id/runs/stream",
        {
          method: "POST",
          body: JSON.stringify({ ok: true }),
        },
      ),
      makeRunContext("thread-id"),
    );

    expect(response.headers.get("cache-control")).toBeNull();
  });

  test("forwards OPTIONS requests without a body", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const { OPTIONS } = await loadRunStreamRoute();
    const request = new NextRequest(
      "http://localhost:3000/api/langgraph/threads/thread-id/runs/stream",
      {
        method: "OPTIONS",
        headers: {
          origin: "http://localhost:3000",
          "access-control-request-method": "POST",
        },
      },
    );
    const response = await OPTIONS(request, makeRunContext("thread-id"));

    const fetchCalls = fetchMock.mock.calls as unknown as [
      string,
      RequestInit & { duplex?: "half" },
    ][];
    const init = fetchCalls[0]?.[1];
    const headers = init?.headers as Headers;

    expect(response.status).toBe(204);
    expect(init?.method).toBe("OPTIONS");
    expect(init?.body).toBeUndefined();
    expect(init?.duplex).toBeUndefined();
    expect(headers.get("origin")).toBe("http://localhost:3000");
    expect(headers.get("access-control-request-method")).toBe("POST");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://gateway.example/base/api/threads/thread-id/runs/stream",
      expect.objectContaining({ method: "OPTIONS" }),
    );
  });

  test("forwards HEAD requests without a body", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const { HEAD } = await loadRunStreamRoute();
    const response = await HEAD(
      new NextRequest(
        "http://localhost:3000/api/langgraph/threads/thread-id/runs/stream",
        {
          method: "HEAD",
        },
      ),
      makeRunContext("thread-id"),
    );

    const fetchCalls = fetchMock.mock.calls as unknown as [
      string,
      RequestInit & { duplex?: "half" },
    ][];
    const init = fetchCalls[0]?.[1];
    expect(response.status).toBe(204);
    expect(init?.method).toBe("HEAD");
    expect(init?.body).toBeUndefined();
    expect(init?.duplex).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://gateway.example/base/api/threads/thread-id/runs/stream",
      expect.objectContaining({ method: "HEAD" }),
    );
  });

  test("uses default gateway URL for blank internal gateway env", async () => {
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = "  ";
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await loadRunStreamRoute();
    await POST(
      new NextRequest(
        "http://localhost:3000/api/langgraph/threads/thread-id/runs/stream",
        {
          method: "POST",
          body: JSON.stringify({ ok: true }),
        },
      ),
      makeRunContext("thread-id"),
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8001/api/threads/thread-id/runs/stream",
      expect.objectContaining({ method: "POST" }),
    );
  });

  test("does not expose same-origin stream routes when external LangGraph URL is configured", async () => {
    process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL = "https://langgraph.example";
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await loadRunStreamRoute();
    const response = await POST(
      new NextRequest(
        "http://localhost:3000/api/langgraph/threads/thread-id/runs/stream",
        {
          method: "POST",
          body: JSON.stringify({ ok: true }),
        },
      ),
      makeRunContext("thread-id"),
    );

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
