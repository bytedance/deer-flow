import type { NextRequest } from "next/server";

import { proxyRequest } from "../proxy";

export async function GET(request: NextRequest) {
  return proxyRequest(request, "/api/skills");
}

export async function POST(request: NextRequest) {
  return proxyRequest(request, "/api/skills");
}
