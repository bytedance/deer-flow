import type { NextRequest } from "next/server";

const BACKEND_BASE_URL =
  process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "http://127.0.0.1:8001";

const INVALID_PATH_SEGMENTS = new Set(["", ".", ".."]);

export function hasInvalidPathSegments(pathSegments: string[]) {
  return pathSegments.some((segment) => INVALID_PATH_SEGMENTS.has(segment));
}

export function resolveProxyPath(prefix: string, pathSegments: string[]) {
  if (hasInvalidPathSegments(pathSegments)) {
    return null;
  }

  return `${prefix}/${pathSegments.join("/")}`;
}

export function buildBackendUrl(pathname: string, search = "") {
  return new URL(`${pathname}${search}`, BACKEND_BASE_URL);
}

function stripProxyHeaders(headers: Headers) {
  for (const headerName of [
    "host",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
  ]) {
    headers.delete(headerName);
  }
}

export async function proxyRequest(request: NextRequest, pathname: string) {
  const headers = new Headers(request.headers);
  stripProxyHeaders(headers);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const response = await fetch(
    buildBackendUrl(pathname, request.nextUrl.search),
    {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
    },
  );

  return new Response(await response.arrayBuffer(), {
    status: response.status,
    headers: response.headers,
  });
}
