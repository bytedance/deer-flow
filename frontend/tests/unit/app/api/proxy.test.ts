import { NextRequest } from "next/server";
import { afterEach, expect, test, vi } from "vitest";

import { GET as getMcpRoute } from "@/app/api/mcp/[...path]/route";
import {
  buildBackendUrl,
  hasInvalidPathSegments,
  proxyRequest,
  resolveProxyPath,
} from "@/app/api/proxy";
import { GET as getSkillsRoute } from "@/app/api/skills/[...path]/route";

afterEach(() => {
  vi.restoreAllMocks();
});

test("rejects empty and dot path segments", () => {
  expect(hasInvalidPathSegments(["valid", "."])).toBe(true);
  expect(hasInvalidPathSegments(["valid", ".."])).toBe(true);
  expect(hasInvalidPathSegments(["valid", ""])).toBe(true);
  expect(hasInvalidPathSegments(["valid", "segment"])).toBe(false);
});

test("returns null for invalid nested proxy paths", () => {
  expect(resolveProxyPath("/api/skills", ["..", "mcp", "config"])).toBeNull();
  expect(resolveProxyPath("/api/mcp", ["", "skills"])).toBeNull();
});

test("builds backend URLs without dropping query strings", () => {
  expect(buildBackendUrl("/api/mcp/config", "?view=full").toString()).toBe(
    "http://127.0.0.1:8001/api/mcp/config?view=full",
  );
});

test("passes the incoming query string through proxy requests", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );

  const request = new NextRequest(
    "http://127.0.0.1:3000/api/mcp/config?view=full",
  );

  await proxyRequest(request, "/api/mcp/config");

  expect(fetchMock).toHaveBeenCalledWith(
    new URL("http://127.0.0.1:8001/api/mcp/config?view=full"),
    expect.objectContaining({
      method: "GET",
    }),
  );
});

test("returns 400 for invalid skills catch-all path segments", async () => {
  const request = new NextRequest(
    "http://127.0.0.1:3000/api/skills/%2e%2e/mcp/config",
  );

  const response = await getSkillsRoute(request, {
    params: Promise.resolve({ path: ["..", "mcp", "config"] }),
  });

  expect(response.status).toBe(400);
  await expect(response.json()).resolves.toEqual({ error: "Invalid path" });
});

test("returns 400 for invalid mcp catch-all path segments", async () => {
  const request = new NextRequest(
    "http://127.0.0.1:3000/api/mcp/%2e%2e/skills",
  );

  const response = await getMcpRoute(request, {
    params: Promise.resolve({ path: ["..", "skills"] }),
  });

  expect(response.status).toBe(400);
  await expect(response.json()).resolves.toEqual({ error: "Invalid path" });
});
