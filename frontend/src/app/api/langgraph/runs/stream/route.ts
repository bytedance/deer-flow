import { type NextRequest } from "next/server";

import { proxyLangGraphStream } from "@/app/api/langgraph/_lib/stream-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function proxyStatelessRunStream(request: NextRequest) {
  // Covers the LangGraph SDK's threadId == null stream endpoint.
  return proxyLangGraphStream(request, ["runs", "stream"]);
}

export const GET = proxyStatelessRunStream;
export const HEAD = proxyStatelessRunStream;
export const POST = proxyStatelessRunStream;
export const OPTIONS = proxyStatelessRunStream;
