import { type NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DEFAULT_GATEWAY_BASE_URL = "http://127.0.0.1:8001";

const HOP_BY_HOP_HEADERS = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
] as const;

function getGatewayBaseUrl() {
  const configured = process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.trim();
  return (
    configured && configured.length > 0 ? configured : DEFAULT_GATEWAY_BASE_URL
  ).replace(/\/+$/, "");
}

function getConnectionHeaderNames(headers: Headers) {
  return (
    headers
      .get("connection")
      ?.split(",")
      .map((name) => name.trim().toLowerCase())
      .filter(Boolean) ?? []
  );
}

function deleteHopByHopHeaders(
  headers: Headers,
  additionalNames: string[] = [],
) {
  for (const name of [...HOP_BY_HOP_HEADERS, ...additionalNames]) {
    headers.delete(name);
  }
}

function buildGatewayUrl(path: string[] | undefined, search: string) {
  const pathname = ["api", ...(path ?? []).map(encodeURIComponent)].join("/");
  return `${getGatewayBaseUrl()}/${pathname}${search}`;
}

function buildHeaders(request: NextRequest, isStreamRequest: boolean) {
  const headers = new Headers(request.headers);
  deleteHopByHopHeaders(headers, getConnectionHeaderNames(headers));
  for (const name of ["host", "content-length"]) {
    headers.delete(name);
  }
  if (isStreamRequest) {
    headers.set("accept-encoding", "identity");
  }
  return headers;
}

async function proxyRequest(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> },
) {
  if (process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
    return new Response(null, { status: 404 });
  }

  // Keep LangGraph SSE out of Next rewrites because the dev proxy can buffer
  // events on Windows. Returning the upstream body directly preserves streaming.
  const { path } = await context.params;
  const target = buildGatewayUrl(path, request.nextUrl.search);
  const method = request.method.toUpperCase();
  const hasBody = !["GET", "HEAD", "OPTIONS"].includes(method);
  const isStreamRequest = path?.at(-1) === "stream";
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers: buildHeaders(request, isStreamRequest),
    redirect: "manual",
    cache: "no-store",
    signal: request.signal,
  };

  if (hasBody) {
    init.body = request.body;
    init.duplex = "half";
  }

  const upstream = await fetch(target, init);
  const headers = new Headers(upstream.headers);
  deleteHopByHopHeaders(headers, getConnectionHeaderNames(headers));
  headers.delete("content-length");
  headers.set("X-Accel-Buffering", "no");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  });
}

export const GET = proxyRequest;
export const HEAD = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
export const OPTIONS = proxyRequest;
