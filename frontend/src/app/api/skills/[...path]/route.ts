import type { NextRequest } from "next/server";

import { proxyRequest, resolveProxyPath } from "../../proxy";

function resolvePath(path: string[]) {
  return resolveProxyPath("/api/skills", path);
}

async function proxySkillsRequest(
  request: NextRequest,
  params: Promise<{ path: string[] }>,
) {
  const pathname = resolvePath((await params).path);

  if (!pathname) {
    return Response.json({ error: "Invalid path" }, { status: 400 });
  }

  return proxyRequest(request, pathname);
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxySkillsRequest(request, params);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxySkillsRequest(request, params);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxySkillsRequest(request, params);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxySkillsRequest(request, params);
}
