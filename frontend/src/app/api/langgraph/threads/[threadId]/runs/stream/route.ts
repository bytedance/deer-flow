import { type NextRequest } from "next/server";

import { proxyLangGraphStream } from "@/app/api/langgraph/_lib/stream-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type RouteContext = {
  params: { threadId: string } | Promise<{ threadId: string }>;
};

async function proxyRunStream(request: NextRequest, context: RouteContext) {
  // Keep run streams out of Next rewrites because the dev proxy can buffer SSE
  // events on Windows. Returning the upstream body directly preserves streaming.
  const { threadId } = await Promise.resolve(context.params);
  return proxyLangGraphStream(request, ["threads", threadId, "runs", "stream"]);
}

export const GET = proxyRunStream;
export const HEAD = proxyRunStream;
export const POST = proxyRunStream;
export const OPTIONS = proxyRunStream;
