import type { NextRequest } from "next/server";

/**
 * Streaming reverse proxy for all ``/api/*`` requests to the Gateway.
 *
 * Why this exists instead of ``next.config.js`` rewrites:
 *   Next.js dev-server rewrites buffer the entire response body before
 *   forwarding, which breaks SSE (``text/event-stream``) — every event arrives
 *   at the client in one batch at connection close. This route handler
 *   forwards ``req.body`` and ``upstream.body`` as ``ReadableStream``s so
 *   Server-Sent Events stay truly streaming.
 *
 * Path mapping (mirrors the previous rewrites):
 *   /api/langgraph/foo  -> gateway /api/foo   (strip ``langgraph`` prefix)
 *   /api/<anything>     -> gateway /api/<anything>
 */
const GATEWAY_URL =
  process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.trim().replace(/\/+$/, "") ??
  "http://127.0.0.1:8001";

const BODYLESS_METHODS = new Set(["GET", "HEAD"]);

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  // /api/langgraph/foo -> gateway /api/foo (strip the langgraph prefix the
  // LangGraph SDK uses as its public base URL).
  const targetSegments = path[0] === "langgraph" ? path.slice(1) : path;
  const target = new URL(`${GATEWAY_URL}/api/${targetSegments.join("/")}`);
  // Preserve query string.
  request.nextUrl.searchParams.forEach((value, key) => {
    target.searchParams.append(key, value);
  });

  const headers = new Headers(request.headers);
  // Let fetch set these based on the target URL / body.
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");

  const hasBody = !BODYLESS_METHODS.has(request.method);
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    redirect: "manual",
  };
  if (hasBody) {
    // Stream the request body instead of buffering it via arrayBuffer().
    init.body = request.body;
    init.duplex = "half";
  }

  const upstream = await fetch(target, init);

  // Copy upstream headers so we can mutate (fetch Response headers are
  // immutable). ``new Headers(src)`` preserves multi-valued headers like
  // ``Set-Cookie``. Drop content-length so Next.js recomputes it for the
  // streamed body (chunked transfer-encoding).
  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete("content-length");
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE, proxy as PATCH };
