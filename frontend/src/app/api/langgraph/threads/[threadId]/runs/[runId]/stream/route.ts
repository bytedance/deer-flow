import { type NextRequest } from "next/server";

import { proxyLangGraphStream } from "@/app/api/langgraph/_lib/stream-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type RouteContext = {
  params:
    | { threadId: string; runId: string }
    | Promise<{ threadId: string; runId: string }>;
};

async function proxyRunJoinStream(request: NextRequest, context: RouteContext) {
  // Keep resumable/join streams on the same direct proxy path as new run streams.
  const { threadId, runId } = await Promise.resolve(context.params);
  return proxyLangGraphStream(request, [
    "threads",
    threadId,
    "runs",
    runId,
    "stream",
  ]);
}

export const GET = proxyRunJoinStream;
export const HEAD = proxyRunJoinStream;
export const POST = proxyRunJoinStream;
export const OPTIONS = proxyRunJoinStream;
