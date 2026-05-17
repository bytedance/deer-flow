import { NextRequest } from "next/server";
import { describe, expect, test } from "vitest";

import { POST } from "@/app/logout-reset/route";

function createLogoutRequest(
  origin?: string,
  extraHeaders: HeadersInit = {},
): NextRequest {
  const headers = new Headers();
  for (const [key, value] of new Headers(extraHeaders)) {
    headers.set(key, value);
  }
  if (origin) {
    headers.set("origin", origin);
  }

  return new NextRequest("http://localhost:3000/logout-reset", {
    method: "POST",
    headers,
  });
}

describe("POST /logout-reset", () => {
  test("clears auth cookies for same-origin requests", async () => {
    const response = await POST(createLogoutRequest("http://localhost:3000"));

    expect(response.status).toBe(200);
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("access_token=");
    expect(setCookie).toContain("csrf_token=");
    expect(setCookie).toContain("Expires=Thu, 01 Jan 1970 00:00:00 GMT");
  });

  test("allows same-origin requests behind a forwarded HTTPS proxy", async () => {
    const response = await POST(
      createLogoutRequest("https://app.example.com", {
        host: "internal-frontend:3000",
        "x-forwarded-host": "app.example.com",
        "x-forwarded-proto": "https",
      }),
    );

    expect(response.status).toBe(200);
  });

  test("rejects cross-site logout requests", async () => {
    const response = await POST(createLogoutRequest("https://evil.example"));

    expect(response.status).toBe(403);
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});
