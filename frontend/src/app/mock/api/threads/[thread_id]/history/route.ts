import fs from "fs";

import type { NextRequest } from "next/server";

import {
  rejectDisabledMockApi,
  resolveDemoThreadFile,
} from "@/core/mock-api/server-security";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ thread_id: string }> },
) {
  const rejected = rejectDisabledMockApi();
  if (rejected) return rejected;

  const threadId = (await params).thread_id;
  const historyPath = resolveDemoThreadFile(threadId, ["thread.json"]);
  if (!historyPath) {
    return new Response("Thread not found", { status: 404 });
  }

  const jsonString = fs.readFileSync(historyPath, "utf8");
  const json = JSON.parse(jsonString);
  if (Array.isArray(json.history)) {
    return Response.json(json);
  }
  return Response.json([json]);
}
