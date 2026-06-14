import { type NextRequest } from "next/server";

import {
  hasConfiguredEnvValue,
  resolveInternalGatewayUrl,
} from "@/core/gateway-url.js";

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

function buildGatewayUrl(path: string[], search: string) {
  const pathname = ["api", ...path.map(encodeURIComponent)].join("/");
  return `${resolveInternalGatewayUrl()}/${pathname}${search}`;
}

function buildHeaders(request: NextRequest) {
  const headers = new Headers(request.headers);
  deleteHopByHopHeaders(headers, getConnectionHeaderNames(headers));
  for (const name of ["host", "content-length"]) {
    headers.delete(name);
  }
  headers.set("accept-encoding", "identity");
  return headers;
}

export async function proxyLangGraphStream(
  request: NextRequest,
  path: string[],
) {
  if (hasConfiguredEnvValue(process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL)) {
    return new Response(null, { status: 404 });
  }

  const target = buildGatewayUrl(path, request.nextUrl.search);
  const method = request.method.toUpperCase();
  const hasBody = !["GET", "HEAD", "OPTIONS"].includes(method);
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers: buildHeaders(request),
    redirect: "manual",
    cache: "no-store",
    signal: request.signal,
  };

  if (hasBody) {
    init.body = request.body;
    init.duplex = "half";
  }

  let upstream;
  try {
    upstream = await fetch(target, init);
  } catch {
    return new Response(
      JSON.stringify({ error: "Gateway connection failed" }),
      {
        status: 502,
        headers: { "content-type": "application/json" },
      },
    );
  }

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
