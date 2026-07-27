import fs from "fs";
import path from "path";

import type { NextRequest } from "next/server";

import {
  rejectDisabledMockApi,
  resolveDemoThreadFile,
} from "@/core/mock-api/server-security";

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
  const rejected = rejectDisabledMockApi();
  if (rejected) return rejected;

  const { thread_id: threadId, artifact_path: artifactPath = [] } =
    await params;
  if (artifactPath[0] !== "mnt") {
    return new Response("File not found", { status: 404 });
  }

  const resolvedArtifactPath = resolveDemoThreadFile(
    threadId,
    artifactPath.slice(1),
  );
  if (!resolvedArtifactPath) {
    return new Response("File not found", { status: 404 });
  }

  if (request.nextUrl.searchParams.get("download") === "true") {
    const headers = new Headers();
    headers.set(
      "Content-Disposition",
      `attachment; filename="${path.basename(resolvedArtifactPath)}"`,
    );
    return new Response(fs.readFileSync(resolvedArtifactPath), {
      status: 200,
      headers,
    });
  }
  if (resolvedArtifactPath.endsWith(".mp4")) {
    return new Response(fs.readFileSync(resolvedArtifactPath), {
      status: 200,
      headers: {
        "Content-Type": "video/mp4",
      },
    });
  }
  return new Response(fs.readFileSync(resolvedArtifactPath), { status: 200 });
}
