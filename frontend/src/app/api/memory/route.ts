import type { NextRequest } from "next/server";

import { getGatewayConfig } from "@/core/auth/gateway-config";

function buildBackendUrl(request: NextRequest, pathname: string) {
  // This route shadows the /api/* rewrite in next.config.js, so it must reach
  // the same Gateway: DEER_FLOW_INTERNAL_GATEWAY_BASE_URL, not a fixed port.
  // Append (not resolve) the path so a base like http://host/prefix keeps
  // its /prefix, as the rewrite's `${gatewayURL}/api/...` destination does.
  const base =
    process.env.NEXT_PUBLIC_BACKEND_BASE_URL ??
    getGatewayConfig().internalGatewayUrl;
  const url = new URL(`${base.trim().replace(/\/+$/, "")}${pathname}`);
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

export async function GET(request: NextRequest) {
  return proxyRequest(request, "/api/memory");
}

export async function DELETE(request: NextRequest) {
  return proxyRequest(request, "/api/memory");
}
