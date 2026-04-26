import fs from "fs";
import path from "path";

import type { NextRequest } from "next/server";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ thread_id: string }> },
) {
  const threadId = (await params).thread_id;
  const jsonString = fs.readFileSync(
    path.resolve(process.cwd(), `public/demo/threads/${threadId}/thread.json`),
    "utf8",
  );
  const json = JSON.parse(jsonString);
  if (Array.isArray(json.history)) {
    return Response.json(json);
  }
  return Response.json([json]);
}
