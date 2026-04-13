import type { NextRequest } from "next/server";

import { proxyRequest } from "../../proxy";

function resolvePath(path: string[]) {
  return `/api/skills/${path.join("/")}`;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, resolvePath((await params).path));
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, resolvePath((await params).path));
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, resolvePath((await params).path));
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxyRequest(request, resolvePath((await params).path));
}
