import type { NextRequest } from "next/server";

import { resolveStaticDemoArtifact } from "@/core/threads/static-demo";

export async function GET(
  request: NextRequest,
  {
    params,
  }: {
    params: Promise<{
      thread_id: string;
      artifact_path?: string[] | undefined;
    }>;
  },
) {
  const { thread_id: threadId, artifact_path: artifactSegments = [] } =
    await params;
  const publicPath = resolveStaticDemoArtifact(threadId, artifactSegments);
  if (!publicPath) return new Response("File not found", { status: 404 });

  const upstreamRequestHeaders: Record<string, string> = {};
  for (const headerName of ["Range", "If-Range"] as const) {
    const value = request.headers.get(headerName);
    if (value) upstreamRequestHeaders[headerName] = value;
  }
  const upstream = await fetch(
    new URL(publicPath, request.nextUrl.origin).toString(),
    { headers: upstreamRequestHeaders, signal: request.signal },
  );
  if (
    (!upstream.ok && upstream.status !== 416) ||
    (!upstream.body && upstream.status !== 416)
  ) {
    return new Response("File not found", { status: 404 });
  }

  const headers = new Headers();
  for (const headerName of [
    "Accept-Ranges",
    "Content-Length",
    "Content-Range",
    "Content-Type",
  ]) {
    const value = upstream.headers.get(headerName);
    if (value) headers.set(headerName, value);
  }
  if (request.nextUrl.searchParams.get("download") === "true") {
    headers.set(
      "Content-Disposition",
      `attachment; filename="${artifactSegments.at(-1)}"`,
    );
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}
