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

  const upstream = await fetch(
    new URL(publicPath, request.nextUrl.origin).toString(),
    { signal: request.signal },
  );
  if (!upstream.ok || !upstream.body) {
    return new Response("File not found", { status: 404 });
  }

  const headers = new Headers();
  const contentType = upstream.headers.get("Content-Type");
  const contentLength = upstream.headers.get("Content-Length");
  if (contentType) headers.set("Content-Type", contentType);
  if (contentLength) headers.set("Content-Length", contentLength);
  if (request.nextUrl.searchParams.get("download") === "true") {
    headers.set(
      "Content-Disposition",
      `attachment; filename="${artifactSegments.at(-1)}"`,
    );
  }
  return new Response(upstream.body, { status: 200, headers });
}
