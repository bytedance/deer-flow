import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

async function loadRoute() {
  vi.resetModules();
  return await import("@/app/api/langgraph/[[...path]]/route");
}

function makeContext(path?: string[]): RouteContext {
  return {
    params: Promise.resolve({ path }),
  };
}

describe("/api/langgraph route proxy", () => {
  const originalGatewayBaseUrl =
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL;

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL;
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL =
      "http://gateway.example/base/";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    if (originalGatewayBaseUrl === undefined) {
      delete process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL;
    } else {
      process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = originalGatewayBaseUrl;
    }
  });

  test("re-encodes path segments and preserves query strings", async () => {
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { GET } = await loadRoute();
    const request = new NextRequest(
      "http://localhost:3000/api/langgraph/ignored?after=a%2Fb",
    );
    await GET(request, makeContext(["threads", "a/b", "x?y", "#z"]));

    expect(fetchMock).toHaveBeenCalledWith(
      "http://gateway.example/base/api/threads/a%2Fb/x%3Fy/%23z?after=a%2Fb",
      expect.objectContaining({ method: "GET", signal: request.signal }),
    );
  });

  test("strips proxy headers while forwarding auth headers and streamed body", async () => {
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await loadRoute();
    const request = new NextRequest(
      "http://localhost:3000/api/langgraph/threads",
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

    await POST(request, makeContext(["threads"]));

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
    expect(headers.get("accept-encoding")).toBe("gzip, br");
  });

  test("requests identity encoding for streaming endpoints", async () => {
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { POST } = await loadRoute();
    await POST(
      new NextRequest(
        "http://localhost:3000/api/langgraph/threads/thread-id/runs/stream",
        {
          method: "POST",
          headers: {
            "accept-encoding": "gzip, br",
          },
          body: JSON.stringify({ ok: true }),
        },
      ),
      makeContext(["threads", "thread-id", "runs", "stream"]),
    );

    const fetchCalls = fetchMock.mock.calls as unknown as [
      string,
      RequestInit,
    ][];
    const headers = fetchCalls[0]?.[1].headers as Headers;
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

    const { GET } = await loadRoute();
    const response = await GET(
      new NextRequest("http://localhost:3000/api/langgraph/threads"),
      makeContext(["threads"]),
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

    const { GET } = await loadRoute();
    const response = await GET(
      new NextRequest("http://localhost:3000/api/langgraph/threads"),
      makeContext(["threads"]),
    );

    expect(response.headers.get("cache-control")).toBeNull();
  });

  test("forwards OPTIONS requests", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const { OPTIONS } = await loadRoute();
    const request = new NextRequest(
      "http://localhost:3000/api/langgraph/threads",
      {
        method: "OPTIONS",
        headers: {
          origin: "http://localhost:3000",
          "access-control-request-method": "POST",
        },
      },
    );
    const response = await OPTIONS(request, makeContext(["threads"]));

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
      "http://gateway.example/base/api/threads",
      expect.objectContaining({ method: "OPTIONS" }),
    );
  });

  test("forwards HEAD requests without a body", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const { HEAD } = await loadRoute();
    const response = await HEAD(
      new NextRequest("http://localhost:3000/api/langgraph/threads", {
        method: "HEAD",
      }),
      makeContext(["threads"]),
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
      "http://gateway.example/base/api/threads",
      expect.objectContaining({ method: "HEAD" }),
    );
  });

  test("uses default gateway URL for blank internal gateway env", async () => {
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = "  ";
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { GET } = await loadRoute();
    await GET(
      new NextRequest("http://localhost:3000/api/langgraph/threads"),
      makeContext(["threads"]),
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8001/api/threads",
      expect.objectContaining({ method: "GET" }),
    );
  });

  test("does not expose the same-origin proxy when external LangGraph URL is configured", async () => {
    process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL = "https://langgraph.example";
    const fetchMock = vi.fn(async () => new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);

    const { GET } = await loadRoute();
    const response = await GET(
      new NextRequest("http://localhost:3000/api/langgraph/threads"),
      makeContext(["threads"]),
    );

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
