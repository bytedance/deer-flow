import type { NextRequest } from "next/server";

// Server-side proxying reaches the Gateway over the internal network, so the
// server-only variable wins; the public one only covers split-origin setups.
// A blank value counts as unset, as in the rewrite and auth resolvers: `new
// URL()` would throw on it instead of falling back.
const BACKEND_BASE_URL =
  (process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL ?? "").trim() ||
  (process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "").trim() ||
  "http://127.0.0.1:8001";

function buildBackendUrl(request: NextRequest, pathname: string) {
  const url = new URL(pathname, BACKEND_BASE_URL);
  url.search = request.nextUrl.search;
  return url;
}

async function proxyRequest(request: NextRequest, pathname: string) {
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const response = await fetch(buildBackendUrl(request, pathname), {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
  });

  return new Response(await response.arrayBuffer(), {
    status: response.status,
    headers: response.headers,
  });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, `/api/memory/${(await params).path.join("/")}`);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, `/api/memory/${(await params).path.join("/")}`);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, `/api/memory/${(await params).path.join("/")}`);
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, `/api/memory/${(await params).path.join("/")}`);
}
